import json
from copy import deepcopy

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

from harness import registry
from harness.middleware.tool_auth import error_message, is_allowed
from harness.middleware.trace import record
from harness.store.pending_inputs import PendingInput, utc_now


class GateAwaitingApproval(Exception):
    def __init__(self, run_id, pending_ids):
        self.run_id = run_id
        self.pending_ids = pending_ids
        super().__init__("Waiting for human decisions")


def should_gate(ctx, name):
    if not is_allowed(ctx, name):
        return False
    metadata = registry.get(name).metadata
    if metadata["input_required"]:
        return True
    mode = ctx["definition"].tool_modes.get(name)
    return mode == "ask" if mode else metadata["confirmation_required"]


def validated_arguments(call):
    tool = registry.get(call["name"])
    return tool.args_schema.model_validate(call["args"]).model_dump(exclude={"runtime"})


class ApprovalGate(AgentMiddleware):
    @hook_config(can_jump_to=["tools"])
    async def abefore_agent(self, state, runtime):
        if not runtime.context.get("gate_decisions"):
            return None
        messages = state["messages"]
        assistant = next(
            (message for message in reversed(messages) if isinstance(message, AIMessage)), None
        )
        answered = {
            message.tool_call_id for message in messages if isinstance(message, ToolMessage)
        }
        if assistant and any(call["id"] not in answered for call in assistant.tool_calls):
            return {"jump_to": "tools"}
        return None

    async def awrap_tool_call(self, request, handler):
        ctx = request.runtime.context
        call = request.tool_call
        decision = ctx.get("gate_decisions", {}).get(call["id"])
        if decision is not None:
            return await self.apply_decision(request, handler, decision)
        if not should_gate(ctx, call["name"]):
            return await handler(request)
        self.validate_card(call)
        run = ctx["run"]
        assistant = next(
            message
            for message in reversed(request.state["messages"])
            if isinstance(message, AIMessage)
        )
        pending_ids = []
        for sibling in assistant.tool_calls:
            if sibling["id"] in ctx["receipts"] or sibling["id"] in ctx.get("gate_decisions", {}):
                continue
            # Apply the outer retry policy to siblings before registering their cards.
            from harness.middleware.error_recovery import MAX_CONSECUTIVE_ERRORS

            if ctx["failures"].get(sibling["name"], 0) >= MAX_CONSECUTIVE_ERRORS:
                continue
            if not should_gate(ctx, sibling["name"]):
                continue
            try:
                arguments = self.validate_card(sibling)
            except (ValueError, TypeError):
                continue
            kind = (
                arguments.get("kind", "approve")
                if sibling["name"] == "request_input"
                else "approve"
            )
            choice = None
            if kind == "choose":
                choice = {
                    key: arguments[key]
                    for key in ("prompt", "options", "mode", "option_type", "allow_other")
                }
            row = ctx["pending_inputs"].register(
                PendingInput(
                    run_id=run.id,
                    firm_id=run.firm_id,
                    tool_call_id=sibling["id"],
                    tool_name=sibling["name"],
                    kind=kind,
                    tool_args=deepcopy(sibling["args"]),
                    rationale=assistant.text or None,
                    context=arguments.get("context"),
                    choose=choice,
                    approve_payload=arguments.get("payload", sibling["args"])
                    if kind == "approve"
                    else None,
                    safe_default=arguments.get("safe_default") if kind == "choose" else None,
                    timeout_at=utc_now() + ctx["ttl"],
                )
            )
            pending_ids.append(row.id)
        rows = ctx["pending_inputs"].for_run(run.id)
        run.status = (
            "paused_input"
            if any(row.kind == "choose" for row in rows if row.status == "pending")
            else "paused_approval"
        )
        record(
            ctx,
            "gate",
            tool=call["name"],
            args=call["args"],
            status="paused",
            pending_ids=pending_ids,
        )
        raise GateAwaitingApproval(run.id, pending_ids)

    def validate_card(self, call):
        if call["name"] != "request_input":
            return call["args"]
        arguments = validated_arguments(call)
        if arguments["kind"] == "choose":
            options = arguments["options"] or []
            if not options and not arguments["allow_other"]:
                raise ValueError("Offer options or allow a typed answer")
            option_ids = [option.get("id") for option in options]
            if any(not isinstance(option_id, str) or not option_id for option_id in option_ids):
                raise ValueError("Each option needs a nonempty string id")
            if len(set(option_ids)) != len(option_ids):
                raise ValueError("Option ids must be unique")
            if any(not option.get("label") for option in options):
                raise ValueError("Each option needs a label")
            if arguments["option_type"] == "entity" and any(
                not option.get("entity_id") for option in options
            ):
                raise ValueError("Entity options require entity_id")
            arguments["options"] = options
        return arguments

    async def apply_decision(self, request, handler, decision):
        call = request.tool_call
        action = decision.get("action")
        record(request.runtime.context, "decision", tool=call["name"], args=decision, status=action)
        if action == "choose" and call["name"] == "request_input":
            return ToolMessage(
                content=json.dumps(decision.get("args", {})),
                tool_call_id=call["id"],
                name=call["name"],
            )
        if action == "approve":
            return await handler(request)
        if action == "modify" and isinstance(decision.get("args"), dict):
            return await handler(request.override(tool_call={**call, "args": decision["args"]}))
        return error_message(
            call, "REJECTED: " + decision.get("rationale", "Cancelled or rejected")
        )

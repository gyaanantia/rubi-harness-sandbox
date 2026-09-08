from langchain.agents.middleware import AgentMiddleware

from harness.middleware.approval_gate import GateAwaitingApproval
from harness.middleware.tool_auth import error_message
from harness.middleware.trace import record

MAX_CONSECUTIVE_ERRORS = 2


class ErrorRecovery(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        ctx = request.runtime.context
        call = request.tool_call
        receipts = ctx["receipts"]
        if call["id"] in receipts:
            return receipts[call["id"]]
        failures = ctx["failures"]
        if failures.get(call["name"], 0) >= MAX_CONSECUTIVE_ERRORS:
            result = error_message(
                call,
                "REJECTED: retry limit reached. Do not retry this tool; "
                "report the failure and continue other work.",
            )
            record(ctx, "tool", tool=call["name"], args=call["args"], status="rejected")
        else:
            try:
                result = await handler(request)
            except GateAwaitingApproval:
                raise
            except Exception as error:
                failures[call["name"]] = failures.get(call["name"], 0) + 1
                result = error_message(call, f"{type(error).__name__}: {error}")
            else:
                if result.status == "success":
                    failures[call["name"]] = 0
        # A failed graph superstep may replay already executed sibling calls.
        receipts[call["id"]] = result
        return result

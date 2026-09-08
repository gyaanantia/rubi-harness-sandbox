from copy import deepcopy

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage

from harness.store.pending_inputs import utc_now


class IncompleteModelResponse(RuntimeError):
    pass


def response_error(messages):
    assistant_messages = [message for message in messages if isinstance(message, AIMessage)]
    if not assistant_messages:
        return "Model returned no assistant response"
    for message in assistant_messages:
        finish_reason = message.response_metadata.get("finish_reason")
        if finish_reason in {"length", "content_filter"}:
            return f"Model response is incomplete (finish_reason={finish_reason})"
        if message.invalid_tool_calls:
            return "Model returned malformed tool calls"
        if not message.text.strip() and not message.tool_calls:
            return "Model returned an empty response without tool calls"
    return None


def record(ctx, kind, *, tool=None, args=None, status="success", **details):
    ctx["run"].trace.append(
        {
            "kind": kind,
            "tool": tool,
            "args": deepcopy(args),
            "status": status,
            "ts": utc_now().isoformat(),
            **details,
        }
    )


class Trace(AgentMiddleware):
    async def awrap_model_call(self, request, handler):
        ctx = request.runtime.context
        record(
            ctx,
            "model",
            status="started",
            input_messages=[
                message.model_dump(mode="json")
                for message in [request.system_message, *request.messages]
                if message is not None
            ],
        )
        try:
            response = await handler(request)
        except Exception as error:
            record(ctx, "model", status="error", error=type(error).__name__)
            raise
        error = response_error(response.result)
        record(
            ctx,
            "model",
            status="error" if error else "success",
            error=error,
            messages=[message.model_dump(mode="json") for message in response.result],
        )
        if error:
            raise IncompleteModelResponse(error)
        return response

    async def awrap_tool_call(self, request, handler):
        ctx = request.runtime.context
        call = request.tool_call
        record(
            ctx,
            "tool",
            tool=call["name"],
            args=call["args"],
            status="started",
            tool_call_id=call["id"],
        )
        try:
            result = await handler(request)
        except Exception as error:
            record(
                ctx,
                "tool",
                tool=call["name"],
                args=call["args"],
                status="error",
                tool_call_id=call["id"],
                error=str(error),
            )
            raise
        record(
            ctx,
            "tool",
            tool=call["name"],
            args=call["args"],
            status=result.status,
            tool_call_id=call["id"],
            result=result.content,
        )
        return result

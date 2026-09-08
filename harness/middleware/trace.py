from copy import deepcopy

from langchain.agents.middleware import AgentMiddleware

from harness.store.pending_inputs import utc_now


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
        record(ctx, "model", status="started")
        try:
            response = await handler(request)
        except Exception as error:
            record(ctx, "model", status="error", error=type(error).__name__)
            raise
        record(
            ctx, "model", messages=[message.model_dump(mode="json") for message in response.result]
        )
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

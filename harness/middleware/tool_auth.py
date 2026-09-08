from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage

from harness.middleware.trace import record


def is_allowed(ctx, name):
    definition = ctx["definition"]
    return (name == "request_input" or name in definition.tools) and (
        definition.tool_modes.get(name) != "block"
    )


def error_message(call, reason):
    return ToolMessage(content=reason, tool_call_id=call["id"], name=call["name"], status="error")


class ToolAuth(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        ctx = request.runtime.context
        call = request.tool_call
        if not is_allowed(ctx, call["name"]):
            record(ctx, "tool", tool=call["name"], args=call["args"], status="blocked")
            return error_message(call, "REJECTED: tool is outside this definition's allowlist")
        return await handler(request)

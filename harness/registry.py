from langchain_core.tools import StructuredTool

_TOOLS: dict[str, StructuredTool] = {}


def tool_def(name, confirmation_required=False, input_required=False, kind="approve"):
    def register(function):
        registered = StructuredTool.from_function(
            coroutine=function,
            name=name,
            metadata={
                "confirmation_required": confirmation_required,
                "input_required": input_required,
                "kind": kind,
            },
        )
        _TOOLS[name] = registered
        return registered

    return register


def get(name):
    return _TOOLS[name]


def list_tools():
    return list(_TOOLS.values())

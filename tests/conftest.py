import socket

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from harness.fake_model import ScriptedModel
from seed.bootstrap import bootstrap


class SequenceModel(ScriptedModel):
    replies: list[AIMessage] = Field(default_factory=list)
    observed: list = Field(default_factory=list)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        # A provider would reject unresolved tool calls before another model turn.
        outstanding = set()
        for message in messages:
            if isinstance(message, AIMessage):
                assert not outstanding, "Model received orphaned tool calls"
                outstanding.update(call["id"] for call in message.tool_calls)
            elif isinstance(message, ToolMessage):
                outstanding.discard(message.tool_call_id)
        assert not outstanding, "Resume invoked the model before replaying tools"
        self.observed.append(messages)
        response = self.replies.pop(0) if self.replies else AIMessage(content="Done")
        return ChatResult(generations=[ChatGeneration(message=response)])


@pytest.fixture
def runtime():
    return bootstrap(fake=True)


@pytest.fixture(autouse=True)
def prevent_external_connections(monkeypatch):
    original_connect = socket.socket.connect

    def local_only(connection, address):
        if connection.family in {socket.AF_INET, socket.AF_INET6}:
            raise AssertionError("Tests must not open network connections")
        return original_connect(connection, address)

    monkeypatch.setattr(socket.socket, "connect", local_only)

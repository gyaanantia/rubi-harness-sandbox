import json
from pathlib import Path

import httpx
from dotenv import dotenv_values
from langchain_openai import ChatOpenAI

from scenarios.common import auto_answer
from seed.deals import DOCUMENT_A


async def test_openai_adapter_pause_resume_and_hidden_context(runtime):
    requests = []
    model_name = dotenv_values(Path(__file__).parents[1] / ".env.example")["SANDBOX_MODEL"]

    def respond(request):
        payload = json.loads(request.content)
        requests.append(payload)
        if len(requests) == 1:
            message = {
                "role": "assistant",
                "content": "Document check and a choice.",
                "tool_calls": [
                    {
                        "id": "read",
                        "type": "function",
                        "function": {
                            "name": "read_document",
                            "arguments": json.dumps({"document_id": DOCUMENT_A}),
                        },
                    },
                    {
                        "id": "pick",
                        "type": "function",
                        "function": {
                            "name": "request_input",
                            "arguments": json.dumps(
                                {"prompt": "Choose", "options": [{"id": "skip", "label": "Skip"}]}
                            ),
                        },
                    },
                ],
            }
        else:
            assert {
                message["tool_call_id"]
                for message in payload["messages"]
                if message["role"] == "tool"
            } == {"read", "pick"}
            message = {"role": "assistant", "content": "Done"}
        return httpx.Response(
            200,
            json={
                "id": "synthetic-completion",
                "object": "chat.completion",
                "created": 1,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if len(requests) == 1 else "stop",
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(
            model=model_name, api_key="synthetic-test-key", http_async_client=client, max_retries=0
        )
        result = await runtime.run(
            runtime.definitions.get("firm-a", "teaser_intake"),
            "Read the supplied document",
            {"private_binding": "not-for-the-model"},
            "user-a1",
            model=model,
        )
        assert result["paused"]
        await auto_answer(runtime, result)
    assert len(requests) == 2
    for request in requests:
        assert "not-for-the-model" not in json.dumps(request)
        for tool in request["tools"]:
            assert "runtime" not in tool["function"]["parameters"]["properties"]

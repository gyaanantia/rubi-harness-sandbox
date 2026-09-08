import json
from pathlib import Path

import httpx
import pytest
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
                "content": "",
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


@pytest.mark.parametrize(
    "status_code,error_code",
    [
        (400, "invalid_request_error"),
        (401, "invalid_api_key"),
        (429, "credit_balance_exhausted"),
        (500, "server_error"),
    ],
)
async def test_provider_error_fails_without_tools_or_retry(runtime, status_code, error_code):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(
            status_code,
            json={
                "error": {
                    "message": "Synthetic provider failure",
                    "type": error_code,
                    "param": None,
                    "code": error_code,
                }
            },
        )

    model_name = dotenv_values(Path(__file__).parents[1] / ".env.example")["SANDBOX_MODEL"]
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(
            model=model_name, api_key="synthetic-test-key", http_async_client=client, max_retries=0
        )
        result = await runtime.run(
            runtime.definitions.get("firm-a", "teaser_intake"),
            "Synthetic task",
            {},
            "user-a1",
            model=model,
        )
    run = runtime.runs.rows[result["run_id"]]
    assert error_code in result["error"]
    assert run.status == "failed" and not result["paused"]
    assert len(requests) == 1
    assert not runtime.pending_inputs.rows and not runtime.gateway.writes
    assert any(event["kind"] == "model" and event["status"] == "error" for event in run.trace)


@pytest.mark.parametrize(
    "finish_reason,content,arguments",
    [
        ("length", "Partial answer", None),
        ("content_filter", "", None),
        ("stop", "", None),
        ("tool_calls", "", "{malformed"),
        ("length", "", '{"prompt":"Pick","options":[{"id":"one","label":"One"}]}'),
    ],
)
async def test_incomplete_model_response_is_not_completed(
    runtime, finish_reason, content, arguments
):
    model_name = dotenv_values(Path(__file__).parents[1] / ".env.example")["SANDBOX_MODEL"]

    def respond(request):
        message = {"role": "assistant", "content": content}
        if arguments is not None:
            message["tool_calls"] = [
                {
                    "id": "incomplete-call",
                    "type": "function",
                    "function": {"name": "request_input", "arguments": arguments},
                }
            ]
        return httpx.Response(
            200,
            json={
                "id": "synthetic-incomplete",
                "object": "chat.completion",
                "created": 1,
                "model": model_name,
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": finish_reason,
                    }
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 4096, "total_tokens": 4116},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = ChatOpenAI(
            model=model_name, api_key="synthetic-test-key", http_async_client=client, max_retries=0
        )
        result = await runtime.run(
            runtime.definitions.get("firm-a", "teaser_intake"),
            "Synthetic task",
            {},
            "user-a1",
            model=model,
        )
    assert runtime.runs.rows[result["run_id"]].status == "failed"
    assert "error" in result and not result["paused"]
    assert not runtime.pending_inputs.rows and not runtime.gateway.writes
    events = runtime.runs.rows[result["run_id"]].trace
    failed_response = next(
        event for event in events if event["kind"] == "model" and event["status"] == "error"
    )
    assert failed_response["messages"][0]["usage_metadata"]["output_tokens"] == 4096

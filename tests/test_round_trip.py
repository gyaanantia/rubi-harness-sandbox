import asyncio
import json
from datetime import timedelta

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from harness.fake_model import choice_options, question, tool_call
from harness.store.pending_inputs import utc_now
from scenarios.common import auto_answer, start
from seed.deals import DEAL_A, DEAL_B, DOCUMENT_A, DOCUMENT_B
from tests.conftest import SequenceModel


async def scripted(runtime, calls, *, tools=None, modes=None, more=None):
    definition = runtime.definitions.get("firm-a", "cim_screener")
    if tools is not None:
        definition.tools = tools
    if modes is not None:
        definition.tool_modes = modes
    model = SequenceModel(
        replies=[AIMessage(content="Model rationale", tool_calls=calls), *(more or [])]
    )
    result = await runtime.run(
        definition, "Synthetic task", {"deal_id": DEAL_A}, "user-a1", model=model
    )
    return result, model


def answer(runtime, row, response):
    return runtime.pending_inputs.respond(row.id, response, firm_id="firm-a", user_id="user-a1")


async def test_batch_waits_for_all_answers_and_resumes_same_thread(runtime):
    result = await start(runtime, "cim_screener")
    run = runtime.runs.rows[result["run_id"]]
    thread_id = run.thread_id
    rows = result["pending"]
    assert len(rows) == 2 and all(row.kind == "choose" for row in rows)
    assert len(rows[0].choose["options"]) == 3
    answer(runtime, rows[0], {"action": "choose", "args": {"selected": "contact-a-1"}})
    partial = await runtime.resume(run.id, firm_id="firm-a")
    assert partial["paused"] and len(partial["pending"]) == 1
    assert runtime.gateway.writes == []
    answer(runtime, rows[1], {"action": "choose", "args": {"selected": "override"}})
    result = await runtime.resume(run.id, firm_id="firm-a")
    assert len(result["pending"]) == 2
    assert all(row.kind == "approve" for row in result["pending"])
    await auto_answer(runtime, result)
    assert run.status == "completed" and run.thread_id == thread_id
    assert len(runtime.gateway.writes) == 2
    assert runtime.gateway.deals[DEAL_A]["fields"]["deal_source_individual"] == "contact-a-1"


async def test_choose_bypasses_tool_body_and_preserves_rationale(runtime, monkeypatch):
    from harness import registry

    async def forbidden(**kwargs):
        raise AssertionError("Choose must not run the tool body")

    monkeypatch.setattr(registry.get("request_input"), "coroutine", forbidden)
    result, model = await scripted(runtime, [question("Pick", choice_options("one", "two"))])
    row = result["pending"][0]
    assert row.rationale == "Model rationale"
    answer(runtime, row, {"action": "choose", "args": {"selected": "two"}})
    result = await runtime.resume(row.run_id, firm_id="firm-a")
    assert not result.get("error")
    assert len(model.observed) == 2
    reply = next(message for message in model.observed[-1] if isinstance(message, ToolMessage))
    assert json.loads(reply.content) == {"selected": "two"}


@pytest.mark.parametrize("action", ["approve", "modify", "reject", "cancel"])
async def test_approval_decisions(runtime, action):
    result, _ = await scripted(
        runtime, [tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="Original")]
    )
    row = result["pending"][0]
    response = {"action": action}
    if action == "modify":
        response["args"] = {"deal_id": DEAL_A, "field": "geography", "value": "Changed"}
    answer(runtime, row, response)
    result = await runtime.resume(row.run_id, firm_id="firm-a")
    assert "error" not in result
    expected = {"geography": "Changed" if action == "modify" else "Original"}
    assert runtime.gateway.deals[DEAL_A]["fields"] == (
        expected if action in {"approve", "modify"} else {}
    )


@pytest.mark.parametrize("modes,allowed_tools", [({"write_crm_field": "block"}, None), ({}, [])])
async def test_tool_auth_blocks_before_gate(runtime, modes, allowed_tools):
    result, model = await scripted(
        runtime,
        [tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="Blocked")],
        modes=modes,
        tools=allowed_tools,
    )
    assert "error" not in result and not result["paused"]
    assert not runtime.pending_inputs.rows and not runtime.gateway.writes
    assert any(
        isinstance(message, ToolMessage) and message.status == "error"
        for message in model.observed[-1]
    )


async def test_input_always_gates_even_with_allow_mode(runtime):
    result, _ = await scripted(
        runtime,
        [question("Pick", choice_options("one"))],
        tools=[],
        modes={"request_input": "allow"},
    )
    assert result["paused"]


async def test_allowed_write_sibling_is_executed_once(runtime):
    result, model = await scripted(
        runtime,
        [
            tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="Once"),
            question("Pick", choice_options("one")),
        ],
        modes={"write_crm_field": "allow"},
    )
    await auto_answer(runtime, result)
    assert len(runtime.gateway.writes) == 1
    assert len(model.observed) == 2
    assert len(runtime.pending_inputs.rows) == 1


async def test_retry_cap_precedes_gate_and_run_continues(runtime):
    for _ in range(3):
        runtime.gateway.fail_next("write_crm_field", "auth_error")

    def write():
        return tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="North")

    result, model = await scripted(
        runtime,
        [write()],
        more=[
            AIMessage(content="retry", tool_calls=[write()]),
            AIMessage(
                content="retry again",
                tool_calls=[write(), question("Other task", choice_options("one"))],
            ),
        ],
    )
    await auto_answer(runtime, result)
    run = runtime.runs.rows[result["run_id"]]
    assert run.status == "completed"
    assert len(runtime.pending_inputs.rows) == 3  # two writes and the unrelated question
    assert len(runtime.gateway.failures["write_crm_field"]) == 1
    assert not runtime.gateway.writes
    assert any(
        isinstance(message, ToolMessage) and "retry limit" in message.content
        for message in model.observed[-1]
    )


async def test_error_string_does_not_count_as_raised_exception(runtime):
    from harness import registry
    from seed.crm import SECTIONS

    schema = registry.get("get_deal_info").tool_call_schema.model_json_schema()
    assert schema["properties"]["sections"]["items"]["enum"] == SECTIONS
    result, _ = await scripted(
        runtime, [tool_call("get_deal_info", deal_id=DEAL_A, sections=["wrong"])]
    )
    context = runtime.contexts[result["run_id"]]
    assert context["failures"]["get_deal_info"] == 0
    receipt = next(iter(context["receipts"].values()))
    assert receipt.status == "success" and "Valid sections" in receipt.content


async def test_invalid_write_arguments_never_create_approval_cards(runtime):
    def invalid_status():
        return tool_call(
            "set_deal_status", deal_id="10000000-0000-4000-8000-0000-000000000001", status="open"
        )

    result, model = await scripted(
        runtime,
        [invalid_status()],
        more=[
            AIMessage(content="Retry", tool_calls=[invalid_status()]),
            AIMessage(content="Retry again", tool_calls=[invalid_status()]),
        ],
    )
    assert not result["paused"] and "error" not in result
    assert not runtime.pending_inputs.rows and not runtime.gateway.writes
    replies = [message for message in model.observed[-1] if isinstance(message, ToolMessage)]
    assert len(replies) == 3 and all(message.status == "error" for message in replies)
    assert "retry limit" in replies[-1].content


@pytest.mark.parametrize(
    "default,expected",
    [({"selected": "skip"}, "completed"), ({"selected": "missing"}, "expired"), (None, "expired")],
)
async def test_ttl_and_safe_default(runtime, default, expected):
    result, _ = await scripted(
        runtime, [question("Choose", choice_options("skip"), safe_default=default)]
    )
    row = result["pending"][0]
    await runtime.pending_inputs.sweep_expired(row.timeout_at - timedelta(seconds=1), runtime)
    assert row.status == "pending"
    await runtime.pending_inputs.sweep_expired(row.timeout_at, runtime)
    assert runtime.runs.rows[row.run_id].status == expected
    assert row.decided_by_user_id is None
    if expected == "completed":
        assert row.response == {"action": "choose", "args": {"selected": "skip"}}
        assert row.decided_at == row.timeout_at
    await runtime.pending_inputs.sweep_expired(row.timeout_at + timedelta(days=1), runtime)
    assert runtime.runs.rows[row.run_id].status == expected


async def test_mixed_expiry_never_executes_a_write(runtime):
    result, _ = await scripted(
        runtime,
        [
            question("Pick", choice_options("skip"), safe_default={"selected": "skip"}),
            tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="Never"),
        ],
    )
    await runtime.pending_inputs.sweep_expired(utc_now() + timedelta(days=4), runtime)
    assert runtime.runs.rows[result["run_id"]].status == "expired"
    assert not runtime.gateway.writes


async def test_answer_validation_and_deadline(runtime):
    result, _ = await scripted(runtime, [question("Pick", choice_options("one"))])
    row = result["pending"][0]
    for response in [
        {"action": "approve"},
        {"action": "choose", "args": {"selected": "unknown"}},
        {"action": "choose", "args": {"other_text": "No"}},
    ]:
        with pytest.raises(ValueError):
            answer(runtime, row, response)
    with pytest.raises(ValueError, match="deadline"):
        runtime.pending_inputs.respond(
            row.id,
            {"action": "choose", "args": {"selected": "one"}},
            firm_id="firm-a",
            user_id="user-a1",
            now=row.timeout_at,
        )
    assert row.status == "pending"


async def test_free_text_and_multiple_selection(runtime):
    result, model = await scripted(
        runtime,
        [
            question("Type", [], allow_other=True),
            question("Pick several", choice_options("one", "two"), mode="multi"),
        ],
    )
    first, second = result["pending"]
    answer(runtime, first, {"action": "choose", "args": {"other_text": "Typed answer"}})
    answer(runtime, second, {"action": "choose", "args": {"selected": ["one", "two"]}})
    await runtime.resume(first.run_id, firm_id="firm-a")
    replies = [
        json.loads(message.content)
        for message in model.observed[-1]
        if isinstance(message, ToolMessage)
    ]
    assert replies == [{"other_text": "Typed answer"}, {"selected": ["one", "two"]}]


async def test_duplicate_answer_and_concurrent_resume(runtime):
    result, _ = await scripted(
        runtime, [tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="Once")]
    )
    row = result["pending"][0]
    answer(runtime, row, {"action": "approve"})
    with pytest.raises(ValueError):
        answer(runtime, row, {"action": "approve"})
    results = await asyncio.gather(
        *[runtime.resume(row.run_id, firm_id="firm-a") for _ in range(2)], return_exceptions=True
    )
    assert sum(isinstance(result, ValueError) for result in results) == 1
    assert len(runtime.gateway.writes) == 1


async def test_firm_isolation_and_prompt_inputs(runtime):
    runtime.memory.put("firm-a", "user-a1", "private memory", DEAL_A)
    runtime.memory.put("firm-b", "user-b1", "other firm secret", DEAL_B)
    runtime.preferences.set("firm-a", "cim_screener", {"preference": "A"}, "user-a1")
    assert runtime.preferences.get("firm-b", "cim_screener", "user-a1") == {}
    result, model = await scripted(runtime, [question("Pick", choice_options("one"))])
    row = result["pending"][0]
    with pytest.raises(KeyError):
        runtime.pending_inputs.respond(
            row.id, {"action": "reject"}, firm_id="firm-b", user_id="user-b1"
        )
    with pytest.raises(KeyError):
        await runtime.resume(row.run_id, firm_id="firm-b")
    with pytest.raises(KeyError):
        runtime.gateway.read_document("firm-a", DOCUMENT_B)
    with pytest.raises(KeyError):
        runtime.gateway.write_crm_field("firm-a", DEAL_B, "geography", "No")
    system = model.observed[0][0].text
    assert "private memory" in system and "other firm secret" not in system
    assert "EBITDA above $12" in system and "EBITDA above $30" not in system
    assert DEAL_A not in system
    model_event = next(
        event for event in runtime.runs.rows[result["run_id"]].trace if event["kind"] == "model"
    )
    assert model_event["input_messages"][0]["content"] == system
    assert "other firm secret" not in json.dumps(model_event["input_messages"])
    result_b = await start(
        runtime,
        "cim_screener",
        firm_id="firm-b",
        user="user-b1",
        deal_id=DEAL_B,
        document_id=DOCUMENT_B,
    )
    assert len(result_b["pending"]) == 1


def banker_question(*numbers):
    return question(
        "Which banker should be the deal source?",
        [
            {"id": f"contact-a-{n}", "label": f"Contact {n}", "entity_id": f"contact-a-{n}"}
            for n in numbers
        ],
        option_type="entity",
    )


async def learn_the_source_contact(runtime):
    result, _ = await scripted(runtime, [banker_question(1, 2, 3)])
    row = result["pending"][0]
    answer(runtime, row, {"action": "choose", "args": {"selected": "contact-a-1"}})
    await runtime.resume(row.run_id, firm_id="firm-a")


async def test_a_learned_answer_skips_its_card_but_never_a_write_approval(runtime):
    await learn_the_source_contact(runtime)
    asked_once = len(runtime.pending_inputs.rows)
    result, _ = await scripted(
        runtime,
        [
            banker_question(1, 2, 3),
            question("Approve the draft", [], kind="approve", action_summary="A draft"),
            tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="North"),
        ],
    )
    assert [row.tool_name for row in result["pending"]] == ["request_input", "write_crm_field"]
    assert all(row.kind == "approve" for row in result["pending"])
    assert len(runtime.pending_inputs.rows) == asked_once + 2  # no card for the banker question
    reused = [
        event
        for event in runtime.runs.rows[result["run_id"]].trace
        if event["kind"] == "decision" and event["status"] == "reused"
    ]
    assert len(reused) == 1 and reused[0]["args"] == {"selected": "contact-a-1"}
    assert reused[0]["feedback_id"] and not runtime.gateway.writes


async def test_a_recovery_ask_is_never_answered_from_feedback(runtime):
    await learn_the_source_contact(runtime)
    asked_once = len(runtime.pending_inputs.rows)
    runtime.gateway.fail_next("write_crm_field", "auth_error")
    result, _ = await scripted(
        runtime,
        [
            tool_call(
                "write_crm_field",
                deal_id=DEAL_A,
                field="deal_source_individual",
                value="contact-a-1",
            )
        ],
        # After the failed write the model asks for a replacement contact with the
        # same options, so the question carries the learned answer's signature.
        more=[AIMessage(content="Select a replacement.", tool_calls=[banker_question(1, 2, 3)])],
    )
    assert [row.tool_name for row in result["pending"]] == ["write_crm_field"]
    answer(runtime, result["pending"][0], {"action": "approve"})
    result = await runtime.resume(result["run_id"], firm_id="firm-a")
    assert result["paused"] and [row.kind for row in result["pending"]] == ["choose"]
    assert result["pending"][0].choose["prompt"] == "Which banker should be the deal source?"
    assert len(runtime.pending_inputs.rows) == asked_once + 2  # the replacement ask is a card
    trace = runtime.runs.rows[result["run_id"]].trace
    assert not [e for e in trace if e["kind"] == "decision" and e["status"] == "reused"]
    assert not runtime.gateway.writes


async def test_reuse_needs_the_definition_to_declare_the_guard(runtime):
    await learn_the_source_contact(runtime)
    definition = runtime.definitions.get("firm-a", "cim_screener")
    definition.guards = []
    definition.version = 2
    runtime.definitions.append(definition)
    result, _ = await scripted(runtime, [banker_question(1, 2, 3)])
    assert len(result["pending"]) == 1


async def test_a_changed_option_set_is_a_different_question(runtime):
    await learn_the_source_contact(runtime)
    result, _ = await scripted(runtime, [banker_question(1, 2, 3, 4)])
    assert len(result["pending"]) == 1  # a fourth banker means the agent asks again


async def test_reach_is_rejected_where_there_is_no_choice_to_learn(runtime):
    result, _ = await scripted(
        runtime,
        [
            tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="North"),
            question("Pick", choice_options("one", "two")),
        ],
    )
    approval = next(row for row in result["pending"] if row.kind == "approve")
    choice = next(row for row in result["pending"] if row.kind == "choose")
    with pytest.raises(ValueError, match="Reach cannot be set on an approval"):
        answer(runtime, approval, {"action": "approve", "remember": "deal"})
    with pytest.raises(ValueError, match="Reach requires a choice"):
        answer(runtime, choice, {"action": "reject", "remember": "deal"})
    assert approval.status == "pending" and choice.status == "pending"


def test_definition_append_is_immutable(runtime):
    original = runtime.definitions.get("firm-a", "cim_screener")
    original.version = 2
    original.instructions = "New version"
    runtime.definitions.append(original)
    original.instructions = "Mutated later"
    assert runtime.definitions.get("firm-a", "cim_screener").instructions == "New version"
    assert runtime.definitions.get("firm-a", "cim_screener", 1).instructions != "New version"
    with pytest.raises(ValueError):
        runtime.definitions.append(original)


def test_gateway_validation_and_snapshots(runtime):
    with pytest.raises(ValueError, match="single-select"):
        runtime.gateway.write_crm_field(
            "firm-a", DEAL_A, "deal_source_individual", ["contact-a-1", "contact-a-2"]
        )
    snapshot = runtime.gateway.snapshot()
    snapshot["deals"][DEAL_A]["fields"]["geography"] = "Mutated"
    assert runtime.gateway.deals[DEAL_A]["fields"] == {}
    assert "Mosswheel" in runtime.gateway.read_document("firm-a", DOCUMENT_A)


async def test_success_resets_the_consecutive_error_counter(runtime):
    invalid_id = "20000000-0000-4000-8000-000000000099"
    result, model = await scripted(
        runtime,
        [tool_call("read_document", document_id=invalid_id)],
        more=[
            AIMessage(
                content="Read valid document",
                tool_calls=[tool_call("read_document", document_id=DOCUMENT_A)],
            ),
            AIMessage(
                content="Another error",
                tool_calls=[tool_call("read_document", document_id=invalid_id)],
            ),
            AIMessage(
                content="Read valid again",
                tool_calls=[tool_call("read_document", document_id=DOCUMENT_A)],
            ),
        ],
    )
    assert "error" not in result
    receipts = [message for message in model.observed[-1] if isinstance(message, ToolMessage)]
    assert [message.status for message in receipts] == ["error", "success", "error", "success"]
    assert runtime.contexts[result["run_id"]]["failures"]["read_document"] == 0

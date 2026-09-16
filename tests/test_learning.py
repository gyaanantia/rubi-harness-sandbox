from langchain_core.messages import AIMessage

from harness.fake_model import choice_options, question, tool_call
from harness.learning import signature
from scenarios import SCENARIOS
from scenarios.common import auto_answer, start
from seed.deals import DEAL_A, DEAL_B, DOCUMENT_B
from tests.test_round_trip import answer, scripted

HARD_FAIL = "Hard fail: kill or override?"


def entity_options(*numbers):
    return [
        {
            "id": f"contact-a-{number}",
            "label": f"Contact {number}",
            "entity_id": f"contact-a-{number}",
        }
        for number in numbers
    ]


def learning_events(runtime, run_id):
    return [event for event in runtime.runs.rows[run_id].trace if event["kind"] == "learning"]


def test_entity_questions_key_on_their_records_not_their_wording():
    asked = signature("request_input", {"prompt": "Which banker?", "options": entity_options(1, 2)})
    paraphrased = signature(
        "request_input", {"prompt": "Who introduced this deal?", "options": entity_options(2, 1)}
    )
    widened = signature(
        "request_input", {"prompt": "Which banker?", "options": entity_options(1, 2, 3)}
    )
    assert asked == paraphrased
    assert asked != widened


def test_text_and_free_questions_key_on_the_normalised_prompt():
    options = choice_options("kill", "override")
    asked = signature("request_input", {"prompt": HARD_FAIL, "options": options})
    assert asked == signature(
        "request_input", {"prompt": "  Hard   FAIL: kill or override?? ", "options": options}
    )
    assert asked != signature("request_input", {"prompt": HARD_FAIL, "options": []})
    assert signature("request_input", {"prompt": "Why?", "options": []}).startswith(
        "request_input|free:"
    )


async def test_a_timeout_default_is_not_human_feedback(runtime):
    await SCENARIOS["unattended"].run(runtime, auto_answer)
    assert runtime.feedback.rows == {}
    assert runtime.memory.rows == {}
    refusals = [
        event
        for run in runtime.runs.rows.values()
        for event in learning_events(runtime, run.id)
        if event["status"] == "refused"
    ]
    assert refusals and {event["reason"] for event in refusals} == {"default"}


async def test_a_recovery_ask_teaches_nothing(runtime):
    await SCENARIOS["sync_failure"].run(runtime, auto_answer)
    reasons = [
        event["reason"]
        for run in runtime.runs.rows.values()
        for event in learning_events(runtime, run.id)
    ]
    assert "recovery" in reasons
    assert all(
        row.prompt != "Sync failed: retry, exclude or map?"
        for row in runtime.feedback.rows.values()
    )


async def test_reach_cannot_rescue_a_recovery_ask(runtime):
    runtime.gateway.fail_next("write_crm_field", "auth_error")
    result, _ = await scripted(
        runtime,
        [tool_call("write_crm_field", deal_id=DEAL_A, field="geography", value="North")],
        more=[
            AIMessage(
                content="CRM sync failed.",
                tool_calls=[
                    question(
                        "Sync failed: retry, exclude or map?",
                        choice_options("retry", "exclude", "map"),
                    )
                ],
            )
        ],
    )
    write = result["pending"][0]
    answer(runtime, write, {"action": "approve"})
    result = await runtime.resume(write.run_id, firm_id="firm-a")
    ask = result["pending"][0]
    answer(runtime, ask, {"action": "choose", "args": {"selected": "exclude"}, "remember": "deal"})
    await runtime.resume(ask.run_id, firm_id="firm-a")
    events = learning_events(runtime, ask.run_id)
    assert any(event["reason"] == "recovery" for event in events)
    assert runtime.feedback.rows == {}


async def test_feedback_never_crosses_a_firm(runtime):
    await SCENARIOS["day1_screen"].run(runtime, auto_answer)
    assert runtime.feedback.active("firm-a") and runtime.feedback.active("firm-b") == []
    result = await start(
        runtime,
        "cim_screener",
        firm_id="firm-b",
        user="user-b1",
        deal_id=DEAL_B,
        document_id=DOCUMENT_B,
    )
    assert len(result["pending"]) == 1  # firm B still has to ask for itself
    trace = runtime.runs.rows[result["run_id"]].trace
    model_event = next(event for event in trace if event["kind"] == "model")
    assert "Decision for this deal" not in model_event["input_messages"][0]["content"]


async def test_a_newer_answer_supersedes_the_older_one(runtime):
    await SCENARIOS["day2_repeat"].run(runtime, auto_answer)
    hard_fail = [row for row in runtime.feedback.rows.values() if row.prompt == HARD_FAIL]
    assert [row.status for row in hard_fail] == ["superseded", "active"]
    lines = runtime.memory.search("firm-a", "user-a1", DEAL_A)
    assert sum(f'on "{HARD_FAIL}"' in line for line in lines) == 1


async def test_firm_reach_proposes_a_skill_change_instead_of_making_one(runtime):
    result, _ = await scripted(runtime, [question(HARD_FAIL, choice_options("kill", "override"))])
    row = result["pending"][0]
    answer(
        runtime,
        row,
        {
            "action": "choose",
            "args": {"selected": "override"},
            "remember": "firm",
            "reason": "Board cleared the size breach",
        },
    )
    await runtime.resume(row.run_id, firm_id="firm-a")

    proposal = runtime.proposals.pending("firm-a")[0]
    assert proposal.target == "screening_criteria" and proposal.status == "pending"
    original = runtime.skills.get("firm-a", "screening_criteria")
    assert original.version == 1
    assert any(
        "not yet accepted" in line for line in runtime.memory.search("firm-a", "user-a1", DEAL_A)
    )
    repeat, _ = await scripted(runtime, [question(HARD_FAIL, choice_options("kill", "override"))])
    assert len(repeat["pending"]) == 1  # a suggestion is not a rule; the agent still asks

    runtime.proposals.accept(proposal.id, firm_id="firm-a", user_id="user-a2", runtime=runtime)
    updated = runtime.skills.get("firm-a", "screening_criteria")
    assert updated.version == 2
    assert updated.body == f"{original.body}\n\n{proposal.proposed_text}"
    assert runtime.skills.get("firm-a", "screening_criteria", version=1).body == original.body
    assert not any(
        "not yet accepted" in line for line in runtime.memory.search("firm-a", "user-a1", DEAL_A)
    )

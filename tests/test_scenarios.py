import pytest
from langchain_core.messages import AIMessage

from eval.assertions import did_not_reask, scenario_completed
from harness.fake_model import choice_options, question, tool_call
from scenarios import SCENARIOS
from scenarios.common import auto_answer
from seed.deals import DEAL_A
from tests.test_round_trip import scripted


@pytest.mark.parametrize("name", list(SCENARIOS))
async def test_scenarios(runtime, name):
    await SCENARIOS[name].run(runtime, auto_answer)
    scenario_completed(runtime, name)


async def test_day1_answers_become_memory_a_later_run_can_read(runtime):
    await SCENARIOS["day1_screen"].run(runtime, auto_answer)
    lines = runtime.memory.search("firm-a", "user-a2", DEAL_A)
    assert any(line.startswith('Decision for this deal on "Which banker') for line in lines)
    assert any(line.startswith('Context for this deal on "Hard fail') for line in lines)
    assert all(DEAL_A not in line for line in lines)


async def test_day2_repeat_stops_reasking_the_answered_question(runtime):
    await SCENARIOS["day2_repeat"].run(runtime, auto_answer)
    did_not_reask(runtime)
    rows = runtime.pending_inputs.rows.values()
    banker = [row for row in rows if row.choose and row.choose["option_type"] == "entity"]
    assert len(rows) == 8 and len(banker) == 1
    assert len(runtime.gateway.writes) == 5


async def test_day2_remember_skips_the_flagged_question_on_the_second_run(runtime):
    await SCENARIOS["day2_remember"].run(runtime, auto_answer)
    first, second = (runtime.pending_inputs.for_run(run.id) for run in runtime.runs.rows.values())
    assert len(first) == 4
    assert [row.tool_name for row in second] == ["write_crm_field", "set_deal_status"]
    assert all(row.kind == "approve" for row in second)
    status = next(row for row in second if row.tool_name == "set_deal_status")
    assert status.tool_args["status"] == "open"  # the remembered override, still approved by hand


async def test_replay_rejects_status_that_contradicts_screening_answer(runtime):
    result, _ = await scripted(
        runtime,
        [question("Kill or override?", choice_options("kill", "override"))],
        more=[
            AIMessage(
                content="Wrong decision",
                tool_calls=[tool_call("set_deal_status", deal_id=DEAL_A, status="kill")],
            )
        ],
    )
    await auto_answer(runtime, result)
    with pytest.raises(AssertionError, match="contradicts screening decision"):
        scenario_completed(runtime, "day1_screen")

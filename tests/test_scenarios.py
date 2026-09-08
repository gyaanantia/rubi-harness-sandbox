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
    if name == "day2_repeat":
        with pytest.raises(AssertionError, match="Repeated source-contact"):
            did_not_reask(runtime)


async def test_deliberate_learning_gap(runtime):
    await SCENARIOS["day1_screen"].run(runtime, auto_answer)
    assert runtime.memory.rows == {}
    assert runtime.preferences.rows == {}


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

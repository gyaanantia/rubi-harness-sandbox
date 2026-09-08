import pytest

from eval.assertions import did_not_reask, scenario_completed
from scenarios import SCENARIOS
from scenarios.common import auto_answer


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

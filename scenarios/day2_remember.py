from functools import partial

from scenarios.common import auto_answer, start

REACH = {"Hard fail: kill or override?": "deal"}


async def run(runtime, answer):
    # Under replay the policy sets the reach flag; a person answering by CLI passes --remember.
    flagged = partial(answer, reach_by_prompt=REACH) if answer is auto_answer else answer
    first = await flagged(runtime, await start(runtime, "cim_screener"))
    second = await answer(runtime, await start(runtime, "cim_screener"))
    return [first, second]

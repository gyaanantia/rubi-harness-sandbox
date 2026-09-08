from scenarios.common import start


async def run(runtime, answer):
    results = []
    for agent_id in ["cim_screener", "teaser_intake", "cim_screener"]:
        results.append(await answer(runtime, await start(runtime, agent_id)))
    return results

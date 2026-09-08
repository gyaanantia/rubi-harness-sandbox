from scenarios.common import start


async def run(runtime, answer):
    return [await answer(runtime, await start(runtime, "cim_screener"))]

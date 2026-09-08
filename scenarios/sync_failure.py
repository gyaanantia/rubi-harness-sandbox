from scenarios.common import start


async def run(runtime, answer):
    results = []
    for failures in [1, 3]:
        for _ in range(failures):
            runtime.gateway.fail_next("write_crm_field", "auth_error")
        results.append(await answer(runtime, await start(runtime, "cim_screener")))
    return results

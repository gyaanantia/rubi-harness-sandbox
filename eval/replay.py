import argparse
import asyncio

from dotenv import load_dotenv

from eval.assertions import did_not_reask, scenario_completed
from scenarios import SCENARIOS
from scenarios.common import auto_answer
from seed.bootstrap import bootstrap


async def replay(name, count, fake):
    print("iteration | asks | writes | assertion")
    failures = 0
    for iteration in range(1, count + 1):
        runtime = bootstrap(fake=fake)
        try:
            await SCENARIOS[name].run(runtime, auto_answer)
            scenario_completed(runtime, name)
            if name == "day2_repeat":
                did_not_reask(runtime)
            outcome = "PASS"
        except (AssertionError, RuntimeError) as error:
            failures += 1
            outcome = f"\033[31mFAIL: {error}\033[0m"
        print(
            f"{iteration:9} | {len(runtime.pending_inputs.rows):4} | "
            f"{len(runtime.gateway.writes):6} | {outcome}"
        )
    return int(failures > 0)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--fake", action="store_true")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n must be positive")
    raise SystemExit(asyncio.run(replay(args.scenario, args.n, args.fake)))


if __name__ == "__main__":
    main()

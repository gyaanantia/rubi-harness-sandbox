import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from eval.assertions import did_not_reask, scenario_completed
from eval.report import write_report
from scenarios import SCENARIOS
from scenarios.common import auto_answer
from seed.bootstrap import bootstrap


async def replay(name, count, fake, output_dir=None):
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)
    print("iteration | asks | writes | assertion")
    failures = 0
    for iteration in range(1, count + 1):
        runtime = bootstrap(fake=fake)
        failure = None
        try:
            await SCENARIOS[name].run(runtime, auto_answer)
            scenario_completed(runtime, name)
            if name == "day2_repeat":
                did_not_reask(runtime)
            outcome = "PASS"
        except (AssertionError, RuntimeError) as error:
            failures += 1
            failure = str(error)
            outcome = f"\033[31mFAIL: {failure}\033[0m"
        print(
            f"{iteration:9} | {len(runtime.pending_inputs.rows):4} | "
            f"{len(runtime.gateway.writes):6} | {outcome}"
        )
        if output_dir is not None:
            path = write_report(
                output_dir, runtime, scenario=name, iteration=iteration, error=failure
            )
            print(f"Report: {path}")
    return int(failures > 0)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=SCENARIOS)
    parser.add_argument("--n", type=int, default=5)
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--output-dir", type=Path, help="Save each iteration's trace as JSON")
    args = parser.parse_args()
    if args.n < 1:
        parser.error("--n must be positive")
    raise SystemExit(asyncio.run(replay(args.scenario, args.n, args.fake, args.output_dir)))


if __name__ == "__main__":
    main()

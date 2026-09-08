"""One local process owns all state; other commands connect over a Unix socket."""

import argparse
import asyncio
import hashlib
import json
import os
import stat
import tempfile
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from scenarios import SCENARIOS
from seed.bootstrap import bootstrap


def encode(value):
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def output(value):
    print(json.dumps(value, default=encode, indent=2), flush=True)


def socket_path():
    # macOS socket paths are limited to 104 bytes; its temp paths can exceed that.
    session_key = hashlib.sha256(tempfile.gettempdir().encode()).hexdigest()[:8]
    directory = Path("/tmp") / f"rubi-harness-{os.getuid()}-{session_key}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("Sandbox socket directory must be private to the current user")
    return directory / "session.sock"


class Session:
    def __init__(self, runtime):
        self.runtime = runtime
        self.changed = asyncio.Event()

    async def answer(self, runtime, result):
        while result.get("paused"):
            output(result)
            print(
                "Another terminal: uv run sandbox answer <pending_id> <option-id|approve|reject>",
                flush=True,
            )
            while runtime.pending(result["run_id"]):
                self.changed.clear()
                await self.changed.wait()
            run = runtime.runs.rows[result["run_id"]]
            result = await runtime.resume(run.id, firm_id=run.firm_id)
        output(result)
        if "error" in result:
            raise RuntimeError(result["error"])
        return result

    async def handle(self, reader, writer):
        try:
            request = json.loads(await reader.readline())
            if request["command"] == "inspect":
                run = self.runtime.runs.rows[request["run_id"]]
                result = {
                    "run": run,
                    "pending_inputs": self.runtime.pending_inputs.for_run(run.id),
                    "gateway": self.runtime.gateway.snapshot(),
                }
            elif request["command"] == "answer":
                row = self.runtime.pending_inputs.rows[request["pending_id"]]
                run = self.runtime.runs.rows[row.run_id]
                if run.status not in {"paused_input", "paused_approval"}:
                    raise ValueError("Run is not waiting for input")
                if run.user_id is None:
                    raise ValueError("This is an unattended run")
                response = self.response(row, request)
                self.runtime.pending_inputs.respond(
                    row.id, response, firm_id=run.firm_id, user_id=run.user_id
                )
                self.changed.set()
                result = {"accepted": True, "run_id": run.id}
            else:
                raise ValueError("Unknown command")
        except (KeyError, ValueError, TypeError) as error:
            result = {"error": str(error)}
        writer.write((json.dumps(result, default=encode) + "\n").encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    def response(self, row, request):
        option = request["option"]
        if request.get("json_response"):
            return json.loads(option)
        if option in {"reject", "cancel"}:
            return {"action": option, "rationale": "Declined by the user"}
        if row.kind == "approve":
            return {"action": option}
        if request.get("other"):
            return {"action": "choose", "args": {"other_text": option}}
        selected = option.split(",") if row.choose["mode"] == "multi" else option
        return {"action": "choose", "args": {"selected": selected}}


async def serve(name, fake):
    path = socket_path()
    if path.exists():
        try:
            _, writer = await asyncio.open_unix_connection(path)
        except (ConnectionRefusedError, FileNotFoundError):
            path.unlink(missing_ok=True)
        else:
            writer.close()
            await writer.wait_closed()
            raise ValueError("A sandbox session is already running; stop it with Ctrl+C first")
    runtime = bootstrap(fake=fake)
    session = Session(runtime)
    server = await asyncio.start_unix_server(session.handle, path=str(path), limit=1_000_000)
    path.chmod(0o600)
    try:
        async with server:
            await SCENARIOS[name].run(runtime, session.answer)
            output(
                {
                    "runs": [asdict(run) for run in runtime.runs.rows.values()],
                    "gateway": runtime.gateway.snapshot(),
                }
            )
            print(
                "Scenario finished. Inspect from another terminal; Ctrl+C clears this session.",
                flush=True,
            )
            await server.serve_forever()
    finally:
        path.unlink(missing_ok=True)


async def client(request):
    try:
        reader, writer = await asyncio.open_unix_connection(socket_path(), limit=10_000_000)
    except (FileNotFoundError, ConnectionRefusedError) as error:
        raise ValueError(
            "No active sandbox. Start sandbox run <scenario> in another terminal."
        ) from error
    writer.write((json.dumps(request) + "\n").encode())
    await writer.drain()
    response = json.loads(await reader.readline())
    writer.close()
    await writer.wait_closed()
    output(response)
    return int("error" in response)


def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("scenario", choices=SCENARIOS)
    run_parser.add_argument("--fake", action="store_true")
    answer_parser = subparsers.add_parser("answer")
    answer_parser.add_argument("pending_id")
    answer_parser.add_argument("option")
    answer_parser.add_argument("--other", action="store_true")
    answer_parser.add_argument("--json-response", action="store_true")
    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("run_id")
    args = parser.parse_args()
    try:
        if args.command == "run":
            asyncio.run(serve(args.scenario, args.fake or os.getenv("SANDBOX_FAKE_MODEL") == "1"))
        else:
            raise SystemExit(asyncio.run(client(vars(args))))
    except KeyboardInterrupt:
        pass
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

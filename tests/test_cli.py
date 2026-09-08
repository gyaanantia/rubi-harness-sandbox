import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path


async def next_json(reader):
    buffer = ""
    while True:
        line = await asyncio.wait_for(reader.readline(), timeout=15)
        if not line:
            raise AssertionError("CLI exited before producing its result")
        if not buffer and not line.startswith(b"{"):
            continue
        buffer += line.decode()
        try:
            return json.loads(buffer)
        except json.JSONDecodeError:
            pass


async def command(environment, *arguments):
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "cli.py",
        *arguments,
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
    assert process.returncode == 0, stderr.decode()
    return json.loads(stdout)


async def test_cli_separate_process_answer_inspect_and_cleanup(tmp_path):
    environment = {**os.environ, "TMPDIR": str(tmp_path)}
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "cli.py",
        "run",
        "day1_screen",
        "--fake",
        env=environment,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        first = await next_json(process.stdout)
        run_id = first["run_id"]
        assert len(first["pending"]) == 2
        for row in first["pending"]:
            option = "contact-a-1" if row["choose"]["option_type"] == "entity" else "override"
            result = await command(environment, "answer", row["id"], option)
            assert result["accepted"]
        second = await next_json(process.stdout)
        assert len(second["pending"]) == 2
        for row in second["pending"]:
            await command(environment, "answer", row["id"], "approve")
        completed = await next_json(process.stdout)
        assert not completed["paused"]
        snapshot = await command(environment, "inspect", run_id)
        assert snapshot["run"]["status"] == "completed"
        assert len(snapshot["gateway"]["writes"]) == 2
    finally:
        import signal

        process.send_signal(signal.SIGINT)
        await asyncio.wait_for(process.communicate(), timeout=10)
    session_key = hashlib.sha256(str(tmp_path).encode()).hexdigest()[:8]
    directory = Path("/tmp") / f"rubi-harness-{os.getuid()}-{session_key}"
    assert not (directory / "session.sock").exists()
    directory.rmdir()

import asyncio
import json
import sys

import pytest
from langchain_core.messages import AIMessage

from eval.replay import replay
from scenarios import SCENARIOS
from scenarios.common import auto_answer
from tests.conftest import SequenceModel


@pytest.mark.parametrize(
    "scenario,exit_code", [("day1_screen", 0), ("day2_repeat", 0), ("day2_remember", 0)]
)
async def test_replay_exports_each_iteration(tmp_path, monkeypatch, scenario, exit_code):
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key-never-include-in-reports")
    output_dir = tmp_path / "reports"
    assert await replay(scenario, 2, True, output_dir) == exit_code
    paths = sorted(output_dir.glob("*.json"))
    assert len(paths) == 2
    for iteration, path in enumerate(paths, start=1):
        content = path.read_text()
        assert "synthetic-key-never-include-in-reports" not in content
        assert str(tmp_path) not in content
        report = json.loads(content)
        assert report["scenario"] == scenario and report["iteration"] == iteration
        assert report["model_mode"] == "fake"
        assert report["passed"] == (exit_code == 0)
        # The fake acts on the memory lines, so no repeated card ever reaches the guard.
        assert report["reused"] == 0 and report["proposals"] == []
        assert [row["category"] for row in report["feedback"]][:2] == ["fact", "judgement"]
        assert report["asks"] == len(report["pending_inputs"])
        assert report["writes"] == len(report["gateway"]["writes"]) > 0
        events = [event for run in report["runs"] for event in run["trace"]]
        request = next(event for event in events if event["kind"] == "model")
        assert request["input_messages"][0]["type"] == "system"
        assert any(event["kind"] == "decision" for event in events)
        assert all(row["decided_at"] for row in report["pending_inputs"])


async def test_replay_cli_preserves_previous_reports(tmp_path):
    for _ in range(2):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "eval.replay",
            "day1_screen",
            "--n",
            "1",
            "--fake",
            "--output-dir",
            str(tmp_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=15)
        assert process.returncode == 0, stderr.decode()
        assert b"Report:" in stdout
    assert len(list(tmp_path.glob("*.json"))) == 2


async def test_replay_retains_failed_model_response(tmp_path, monkeypatch):
    async def incomplete_run(runtime, answer):
        model = SequenceModel(
            replies=[AIMessage(content="", response_metadata={"finish_reason": "length"})]
        )
        result = await runtime.run(
            runtime.definitions.get("firm-a", "cim_screener"),
            "Synthetic task",
            {},
            "user-a1",
            model=model,
        )
        await auto_answer(runtime, result)

    monkeypatch.setattr(SCENARIOS["day1_screen"], "run", incomplete_run)
    assert await replay("day1_screen", 1, True, tmp_path) == 1
    report = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert not report["passed"] and "finish_reason=length" in report["error"]
    assert report["runs"][0]["status"] == "failed"
    assert report["asks"] == report["writes"] == 0
    failed_event = next(
        event
        for event in report["runs"][0]["trace"]
        if event["kind"] == "model" and event["status"] == "error"
    )
    assert failed_event["messages"][0]["response_metadata"]["finish_reason"] == "length"

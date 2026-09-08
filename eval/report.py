import json
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4


def encode(value):
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def write_report(directory, runtime, *, scenario, iteration, error):
    report = {
        "scenario": scenario,
        "iteration": iteration,
        "model_mode": "fake" if runtime.fake else "live",
        "passed": error is None,
        "error": error,
        "asks": len(runtime.pending_inputs.rows),
        "writes": len(runtime.gateway.writes),
        "runs": [asdict(run) for run in runtime.runs.rows.values()],
        "pending_inputs": [asdict(row) for row in runtime.pending_inputs.rows.values()],
        "gateway": runtime.gateway.snapshot(),
    }
    path = directory / f"{scenario}-{iteration:03}-{uuid4().hex}.json"
    path.write_text(json.dumps(report, default=encode, indent=2) + "\n", encoding="utf-8")
    return path

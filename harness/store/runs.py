from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4


@dataclass
class Run:
    agent_id: str
    agent_version: int
    firm_id: str
    user_id: str | None
    bindings: dict
    kickoff: str
    id: str = field(default_factory=lambda: str(uuid4()))
    thread_id: str = field(default_factory=lambda: str(uuid4()))
    status: Literal[
        "running", "paused_input", "paused_approval", "completed", "failed", "expired"
    ] = "running"
    trace: list[dict] = field(default_factory=list)


class RunStore:
    def __init__(self):
        self.rows: dict[str, Run] = {}

    def get(self, run_id: str, firm_id: str):
        run = self.rows[run_id]
        if run.firm_id != firm_id:
            raise KeyError("Run not found")
        return run

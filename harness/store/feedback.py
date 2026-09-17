from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

from harness.store.pending_inputs import utc_now


@dataclass
class Feedback:
    firm_id: str
    agent_id: str
    run_id: str
    pending_id: str
    user_id: str
    deal_id: str | None
    signature: str
    category: Literal["fact", "judgement", "free_text"]
    answer: dict
    prompt: str
    label: str | None
    reason: str | None
    reach: Literal["once", "deal", "firm"]
    id: str = field(default_factory=lambda: str(uuid4()))
    status: Literal["active", "superseded", "retracted"] = "active"
    created_at: datetime = field(default_factory=utc_now)


class FeedbackStore:
    def __init__(self):
        self.rows: dict[str, Feedback] = {}

    def add(self, row: Feedback):
        for existing in self.rows.values():
            if (
                existing.status == "active"
                and existing.firm_id == row.firm_id
                and existing.deal_id == row.deal_id
                and existing.signature == row.signature
            ):
                existing.status = "superseded"
        self.rows[row.id] = row
        return row

    def active(self, firm_id: str, *, deal_id: str | None = None, reach: str | None = None):
        rows = [
            row
            for row in self.rows.values()
            if row.status == "active"
            and row.firm_id == firm_id
            and (deal_id is None or row.deal_id == deal_id)
            and (reach is None or row.reach == reach)
        ]
        return sorted(rows, key=lambda row: row.created_at)

    def match(self, firm_id: str, deal_id: str | None, signature: str, *, reach: str = "deal"):
        # An explicit deal comparison: a run without a deal must not reuse a deal's answer.
        rows = [
            row
            for row in self.active(firm_id, reach=reach)
            if row.deal_id == deal_id and row.signature == signature
        ]
        return rows[-1] if rows else None

    def for_run(self, run_id: str):
        return [row for row in self.rows.values() if row.run_id == run_id]

    def retract(self, feedback_id: str):
        self.rows[feedback_id].status = "retracted"

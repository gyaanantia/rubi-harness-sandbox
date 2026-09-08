from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import uuid4

DEFAULT_TTL = timedelta(hours=72)


def utc_now():
    return datetime.now(timezone.utc)


@dataclass
class PendingInput:
    run_id: str
    firm_id: str
    tool_call_id: str
    tool_name: str
    kind: Literal["approve", "choose"]
    tool_args: dict
    rationale: str | None
    context: str | None
    choose: dict | None
    approve_payload: dict | None
    safe_default: dict | None
    timeout_at: datetime | None
    id: str = field(default_factory=lambda: str(uuid4()))
    status: Literal["pending", "resolved", "expired", "cancelled"] = "pending"
    response: dict | None = None
    decided_by_user_id: str | None = None
    decided_at: datetime | None = None


def validate_response(row: PendingInput, response: dict):
    if not isinstance(response, dict):
        raise ValueError("Response must be an object")
    action = response.get("action")
    if action in {"cancel", "reject"}:
        return
    if row.kind == "approve":
        if action not in {"approve", "modify"}:
            raise ValueError("Approval requires approve, modify, reject or cancel")
        if action == "modify" and not isinstance(response.get("args"), dict):
            raise ValueError("Modified arguments must be an object")
        return
    if action != "choose":
        raise ValueError("Choice requires choose, reject or cancel")
    arguments = response.get("args", {})
    if not isinstance(arguments, dict):
        raise ValueError("Choice arguments must be an object")
    choice = row.choose or {}
    selected = arguments.get("selected")
    has_other = bool(arguments.get("other_text")) and choice.get("allow_other", False)
    if selected is None and has_other:
        return
    if choice.get("mode", "single") == "multi":
        if not isinstance(selected, list) or not selected:
            raise ValueError("Select one or more option ids")
        selections = selected
    else:
        if not isinstance(selected, str):
            raise ValueError("Select exactly one option id")
        selections = [selected]
    option_ids = {option["id"] for option in choice.get("options", [])}
    if any(selection not in option_ids for selection in selections):
        raise ValueError("Unknown option id")
    if arguments.get("other_text") and not has_other:
        raise ValueError("Free text is not allowed")


class PendingInputStore:
    def __init__(self):
        self.rows: dict[str, PendingInput] = {}
        self.by_call: dict[tuple[str, str], str] = {}

    def register(self, row: PendingInput):
        key = (row.run_id, row.tool_call_id)
        if key not in self.by_call:
            self.by_call[key] = row.id
            self.rows[row.id] = row
        return self.rows[self.by_call[key]]

    def for_run(self, run_id: str):
        return [row for row in self.rows.values() if row.run_id == run_id]

    def respond(self, pending_id, response, *, firm_id, user_id, now=None):
        row = self.rows[pending_id]
        if row.firm_id != firm_id:
            raise KeyError("Pending input not found")
        if row.status != "pending":
            raise ValueError("Input is no longer pending")
        decision_time = now or utc_now()
        if row.timeout_at and decision_time >= row.timeout_at:
            raise ValueError("Input deadline has passed; sweep expired inputs")
        validate_response(row, response)
        self._resolve(row, response, user_id, decision_time)
        return row

    def _resolve(self, row, response, user_id, now):
        row.response = deepcopy(response)
        row.status = "cancelled" if response["action"] == "cancel" else "resolved"
        row.decided_by_user_id = user_id
        row.decided_at = now

    async def sweep_expired(self, now, runtime):
        affected = set()
        for row in list(self.rows.values()):
            if row.status != "pending" or not row.timeout_at or row.timeout_at > now:
                continue
            affected.add(row.run_id)
            response = {"action": "choose", "args": row.safe_default}
            try:
                if row.kind != "choose" or not row.safe_default:
                    raise ValueError("No safe default")
                validate_response(row, response)
            except (ValueError, TypeError):
                row.status = "expired"
            else:
                self._resolve(row, response, None, now)
        for run_id in affected:
            run = runtime.runs.rows[run_id]
            rows = self.for_run(run_id)
            if any(row.status == "expired" for row in rows):
                run.status = "expired"
                for row in rows:
                    if row.status == "pending":
                        row.status = "cancelled"
                continue
            if all(row.status in {"resolved", "cancelled"} for row in rows):
                await runtime.resume(run_id, firm_id=run.firm_id)
        return sorted(affected)

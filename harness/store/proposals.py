from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal
from uuid import uuid4

from harness import learning
from harness.store.pending_inputs import utc_now


@dataclass
class Proposal:
    firm_id: str
    feedback_id: str
    target: str
    proposed_text: str
    id: str = field(default_factory=lambda: str(uuid4()))
    status: Literal["pending", "accepted", "rejected"] = "pending"
    decided_by_user_id: str | None = None
    decided_at: datetime | None = None


class ProposalStore:
    def __init__(self):
        self.rows: dict[str, Proposal] = {}

    def create(self, *, firm_id: str, feedback_id: str, target: str, proposed_text: str):
        proposal = Proposal(firm_id, feedback_id, target, proposed_text)
        self.rows[proposal.id] = proposal
        return proposal

    def for_feedback(self, feedback_id: str):
        return next(
            (row for row in self.rows.values() if row.feedback_id == feedback_id),
            None,
        )

    def pending(self, firm_id: str):
        return [
            row for row in self.rows.values() if row.firm_id == firm_id and row.status == "pending"
        ]

    def _open(self, proposal_id, firm_id):
        proposal = self.rows[proposal_id]
        if proposal.firm_id != firm_id:
            raise KeyError("Proposal not found")
        if proposal.status != "pending":
            raise ValueError(f"Proposal is already {proposal.status}")
        return proposal

    def accept(self, proposal_id: str, *, firm_id: str, user_id: str, runtime):
        """PLAN 10.8: append the proposed text as a new skill or definition version."""
        proposal = self._open(proposal_id, firm_id)
        if (firm_id, proposal.target) in runtime.skills.rows:
            runtime.skills.append(firm_id, proposal.target, proposal.proposed_text)
        else:
            definition = runtime.definitions.get(firm_id, proposal.target)
            definition.version += 1
            definition.instructions = f"{definition.instructions}\n\n{proposal.proposed_text}"
            runtime.definitions.append(definition)
        self._decide(proposal, "accepted", user_id)
        row = runtime.feedback.rows[proposal.feedback_id]
        runtime.feedback.retract(row.id)
        learning.rebuild(runtime.feedback, runtime.memory, firm_id, row.deal_id)
        return proposal

    def reject(self, proposal_id: str, *, firm_id: str, user_id: str):
        return self._decide(self._open(proposal_id, firm_id), "rejected", user_id)

    def _decide(self, proposal, status, user_id):
        proposal.status = status
        proposal.decided_by_user_id = user_id
        proposal.decided_at = utc_now()
        return proposal

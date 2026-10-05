import uuid
from dataclasses import dataclass
from enum import Enum

from app.actions.model import DecisionSnapshot


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


_TERMINAL = {ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.EXPIRED}


@dataclass(frozen=True)
class Approval:
    approval_id: str
    snapshot: DecisionSnapshot
    status: ApprovalStatus
    decided_by: str | None = None


class ApprovalStore:
    def __init__(self) -> None:
        self._by_id: dict[str, Approval] = {}

    def request(self, snapshot: DecisionSnapshot) -> Approval:
        aid = uuid.uuid4().hex
        ap = Approval(aid, snapshot, ApprovalStatus.PENDING)
        self._by_id[aid] = ap
        return ap

    def get(self, approval_id: str) -> Approval | None:
        return self._by_id.get(approval_id)

    def _transition(self, approval_id: str, to: ApprovalStatus,
                    actor: str | None = None) -> Approval:
        cur = self._by_id.get(approval_id)
        if cur is None:
            raise KeyError(approval_id)
        if cur.status in _TERMINAL:
            raise ValueError(
                f"approval 已终态（{cur.status.value}），不可变更；重新审批请新建 Approval")
        new = Approval(cur.approval_id, cur.snapshot, to, actor)
        self._by_id[approval_id] = new
        return new

    def approve(self, approval_id: str, actor: str) -> Approval:
        return self._transition(approval_id, ApprovalStatus.APPROVED, actor)

    def reject(self, approval_id: str, actor: str) -> Approval:
        return self._transition(approval_id, ApprovalStatus.REJECTED, actor)

    def expire(self, approval_id: str) -> Approval:
        return self._transition(approval_id, ApprovalStatus.EXPIRED)

    def is_valid_for(self, approval_id: str, proposal_fingerprint: str) -> bool:
        ap = self._by_id.get(approval_id)
        return (ap is not None
                and ap.status is ApprovalStatus.APPROVED
                and ap.snapshot.proposal_fingerprint == proposal_fingerprint)

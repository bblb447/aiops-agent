from dataclasses import dataclass

from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor, seal
from app.actions.gateway import ActionGateway
from app.actions.model import (
    AdmissionOutcome, DecisionResult, ExecutionResult, GatewayOutcome,
)
from app.auth.model import ActorContext


@dataclass(frozen=True)
class FlowResult:
    status: str
    decision: DecisionResult | None = None
    approval_id: str | None = None
    execution: ExecutionResult | None = None


class ActionFlow:
    """编排 Gateway→Approval→Executor→Audit；只推进状态，不重新决策。"""

    def __init__(self, gateway: ActionGateway, approval_store: ApprovalStore,
                 executor: ActionExecutor, audit: AuditLog) -> None:
        self._gateway = gateway
        self._approvals = approval_store
        self._executor = executor
        self._audit = audit

    @staticmethod
    def _action_id(res: DecisionResult) -> str | None:
        return res.snapshot.action_id if res.snapshot else None

    def _run_execution(self, order, incident_id: str) -> ExecutionResult:
        res = self._executor.execute(order)
        if res.admission is AdmissionOutcome.REJECTED:
            self._audit.append("EXECUTION_REJECTED", incident_id=incident_id,
                               action_id=order.action_id,
                               proposal_fingerprint=order.proposal_fingerprint,
                               detail={"reason_kind": res.reason})
        else:
            self._audit.append("EXECUTION_ACCEPTED", incident_id=incident_id,
                               action_id=order.action_id,
                               proposal_fingerprint=order.proposal_fingerprint)
            self._audit.append(res.outcome.value, incident_id=incident_id,
                               action_id=order.action_id,
                               proposal_fingerprint=order.proposal_fingerprint,
                               detail={"execution_outcome": res.outcome.value})
        return res

    def propose(self, incident_id: str, payload: dict, actor_context: ActorContext) -> FlowResult:
        self._audit.append("PROPOSED", incident_id=incident_id)
        res = self._gateway.evaluate(incident_id, payload, actor_context)
        fp = res.proposal_fingerprint
        aid = self._action_id(res)
        if res.outcome is GatewayOutcome.REJECT:
            self._audit.append("EXECUTION_REJECTED", incident_id=incident_id, action_id=aid,
                               proposal_fingerprint=fp, detail={"reason_kind": "gateway_reject"})
            return FlowResult("REJECTED", decision=res)
        self._audit.append("RISK_EVALUATED", incident_id=incident_id, action_id=aid,
                           proposal_fingerprint=fp, detail={"final_risk": res.final_risk.value})
        self._audit.append("POLICY_DECIDED", incident_id=incident_id, action_id=aid,
                           proposal_fingerprint=fp,
                           detail={"policy_decision": res.policy_decision.value})
        if res.outcome is GatewayOutcome.DENY:
            self._audit.append("EXECUTION_REJECTED", incident_id=incident_id, action_id=aid,
                               proposal_fingerprint=fp, detail={"reason_kind": "denied"})
            return FlowResult("DENIED", decision=res)
        if res.outcome is GatewayOutcome.APPROVAL_REQUIRED:
            ap = self._approvals.request(res.snapshot)
            self._audit.append("APPROVAL_REQUESTED", incident_id=incident_id, action_id=aid,
                               proposal_fingerprint=fp, detail={"approval_id": ap.approval_id})
            return FlowResult("AWAITING_APPROVAL", decision=res, approval_id=ap.approval_id)
        # ALLOW：自动路径
        order = seal(res.snapshot, self._approvals, None)
        ex = self._run_execution(order, incident_id)
        return FlowResult("EXECUTED", decision=res, execution=ex)

    def decide_approval(self, approval_id: str, approved: bool,
                        actor_context: ActorContext) -> FlowResult:
        ap = self._approvals.get(approval_id)
        if ap is None:
            raise KeyError(approval_id)
        actor = actor_context.principal_id
        if not approved:
            self._approvals.reject(approval_id, actor)
            self._audit.append("REJECTED", action_id=ap.snapshot.action_id,
                               proposal_fingerprint=ap.snapshot.proposal_fingerprint,
                               detail={"approval_id": approval_id})
            return FlowResult("REJECTED", approval_id=approval_id)
        self._approvals.approve(approval_id, actor)
        self._audit.append("APPROVED", action_id=ap.snapshot.action_id,
                           proposal_fingerprint=ap.snapshot.proposal_fingerprint,
                           detail={"approval_id": approval_id})
        # 只消费已批准的 Approval.snapshot；不重跑 Gateway/Risk/Policy。
        order = seal(ap.snapshot, self._approvals, approval_id)
        ex = self._run_execution(order, incident_id=ap.snapshot.context.incident_id)
        return FlowResult("EXECUTED", approval_id=approval_id, execution=ex)

    def approval_status(self, approval_id: str):
        """只读查询（不改变状态）；供 API 使用，避免外部直取内部 store。"""
        return self._approvals.get(approval_id)

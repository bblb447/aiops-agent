from dataclasses import dataclass, field

from app.actions.approval import ApprovalStatus, ApprovalStore
from app.actions.gateway import proposal_fingerprint
from app.actions.model import (
    AdmissionOutcome, DecisionSnapshot, ExecutionOutcome, ExecutionResult,
    PermissionLevel, PolicyDecision, TargetDescriptor,
)
from app.actions.registry import ActionRegistry


class _SealCapability:
    __slots__ = ()


_CAPABILITY = _SealCapability()      # 模块私有：只有本模块的 seal() 会盖此标记


@dataclass(frozen=True)
class SealedOrder:
    """不可变执行凭单。_cap 为私有 capability 标记（compare=False），防绕过 seal 直接伪造。"""
    snapshot: DecisionSnapshot
    approval_id: str | None
    _cap: object = field(default=None, repr=False, compare=False)

    @property
    def action_id(self) -> str:
        return self.snapshot.action_id

    @property
    def target_descriptor(self) -> TargetDescriptor:
        return self.snapshot.target_descriptor

    @property
    def registry_version(self) -> str:
        return self.snapshot.registry_version

    @property
    def proposal_fingerprint(self) -> str:
        return self.snapshot.proposal_fingerprint


def seal(snapshot: DecisionSnapshot, approval_store: ApprovalStore,
         approval_id: str | None = None) -> SealedOrder:
    """只有『已批准且 fingerprint 一致』的 Approval（或 ALLOW 自动路径）才能封 order。"""
    if approval_id is None:
        if snapshot.policy_decision is not PolicyDecision.ALLOW:
            raise ValueError("无审批的 sealed order 仅允许 ALLOW 决策")
    else:
        if snapshot.policy_decision is not PolicyDecision.APPROVAL_REQUIRED:
            raise ValueError("带审批的 sealed order 仅允许 APPROVAL_REQUIRED 决策")
        ap = approval_store.get(approval_id)
        if ap is None or ap.status is not ApprovalStatus.APPROVED:
            raise ValueError("seal 需要已批准的 Approval")
        if ap.snapshot.proposal_fingerprint != snapshot.proposal_fingerprint:
            raise ValueError("Approval 与 snapshot 的 fingerprint 不一致")
    return SealedOrder(snapshot=snapshot, approval_id=approval_id, _cap=_CAPABILITY)


class ActionExecutor:
    """唯一持有执行 backend 的组件；只做 defensive admission，不重跑 Risk/Policy。"""

    def __init__(self, backend, registry: ActionRegistry,
                 approval_store: ApprovalStore) -> None:
        self._backend = backend
        self._registry = registry
        self._approvals = approval_store

    def execute(self, order: SealedOrder) -> ExecutionResult:
        snap = order.snapshot
        # --- defensive admission（不重跑 Risk/Policy）---
        if order._cap is not _CAPABILITY:
            return ExecutionResult(AdmissionOutcome.REJECTED, "order 未经 seal（capability 缺失）")
        if order.approval_id is None and snap.policy_decision is not PolicyDecision.ALLOW:
            return ExecutionResult(AdmissionOutcome.REJECTED, "policy↔order 不一致（无审批非 ALLOW）")
        if order.approval_id is not None and snap.policy_decision is not PolicyDecision.APPROVAL_REQUIRED:
            return ExecutionResult(AdmissionOutcome.REJECTED, "policy↔order 不一致（有审批非 APPROVAL_REQUIRED）")
        entry = self._registry.get(snap.action_id)
        if entry is None:
            return ExecutionResult(AdmissionOutcome.REJECTED, "action 不在 Registry")
        if entry.permission_level is PermissionLevel.CRITICAL:
            return ExecutionResult(AdmissionOutcome.REJECTED, "CRITICAL 永不执行")
        if snap.registry_version != self._registry.version:
            return ExecutionResult(AdmissionOutcome.REJECTED, "registry_version 不一致")
        recomputed = proposal_fingerprint(
            snap.context, snap.action_id, snap.target_descriptor, dict(snap.parameters),
            snap.final_risk, snap.policy_decision, snap.registry_version)
        if recomputed != snap.proposal_fingerprint:
            return ExecutionResult(AdmissionOutcome.REJECTED, "sealed order 完整性校验失败")
        if order.approval_id is not None:
            ap = self._approvals.get(order.approval_id)
            if ap is None or ap.status is not ApprovalStatus.APPROVED:
                return ExecutionResult(AdmissionOutcome.REJECTED, "Approval 未批准或不存在")
            if ap.snapshot.proposal_fingerprint != snap.proposal_fingerprint:
                return ExecutionResult(AdmissionOutcome.REJECTED, "Approval 与 sealed order 不一致")
        # --- 执行（唯一持有 backend）---
        try:
            outcome = self._backend.execute(snap.action_id, snap.target_descriptor,
                                            dict(snap.parameters))
        except TimeoutError:
            return ExecutionResult(AdmissionOutcome.ACCEPTED, outcome=ExecutionOutcome.TIMEOUT)
        except Exception:
            return ExecutionResult(AdmissionOutcome.ACCEPTED, outcome=ExecutionOutcome.FAILED)
        return ExecutionResult(AdmissionOutcome.ACCEPTED, outcome=outcome)

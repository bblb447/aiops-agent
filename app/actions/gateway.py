import hashlib
import json
from types import MappingProxyType

from app.actions.context import V1DecisionContext, build_context, is_eligible
from app.actions.model import (
    ALLOWED_PROPOSAL_KEYS, FORBIDDEN_PROPOSAL_KEYS, DecisionResult,
    DecisionSnapshot, GatewayOutcome, PolicyDecision, RiskLevel, TargetDescriptor,
)
from app.actions.policy import decide
from app.actions.registry import ActionRegistry, validate_parameters
from app.actions.risk import evaluate_risk


def proposal_fingerprint(ctx: V1DecisionContext, action_id: str,
                         target_descriptor: TargetDescriptor, parameters: dict,
                         final_risk: RiskLevel, policy_decision: PolicyDecision,
                         registry_version: str) -> str:
    blob = json.dumps({
        "context": {"version": ctx.version, "incident_id": ctx.incident_id,
                    "status": ctx.status, "verdict": ctx.verdict,
                    "confidence": ctx.confidence,
                    "evidence": [[e.source, e.fact] for e in ctx.evidence],
                    "failure_code": ctx.failure_code},
        "action_id": action_id,
        "target": {"kind": target_descriptor.kind,
                   "environment": target_descriptor.environment,
                   "replicas": target_descriptor.replicas},
        "parameters": parameters,
        "final_risk": final_risk.value,
        "policy_decision": policy_decision.value,
        "registry_version": registry_version,
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class ActionGateway:
    def __init__(self, registry: ActionRegistry, resolver, incident_reader) -> None:
        self._registry = registry
        self._resolver = resolver
        self._read_incident = incident_reader

    def evaluate(self, incident_id: str, payload: dict, actor_context: dict) -> DecisionResult:
        # 0) payload 类型 fail-closed（非 dict 一律拒，不猜测）
        if not isinstance(payload, dict):
            return DecisionResult(GatewayOutcome.REJECT, reason="proposal 必须是对象")
        # 1) zero-trust：禁止字段 / 未知顶层字段 → fail-closed 拒收
        keys = set(payload)
        forbidden = sorted(FORBIDDEN_PROPOSAL_KEYS & keys)
        if forbidden:
            return DecisionResult(GatewayOutcome.REJECT,
                                  reason=f"proposal 含禁止字段: {forbidden}")
        unknown = sorted(keys - ALLOWED_PROPOSAL_KEYS)
        if unknown:
            return DecisionResult(GatewayOutcome.REJECT,
                                  reason=f"proposal 含不允许的顶层字段: {unknown}")
        # 2) action ∈ Registry
        action_id = payload.get("action_id")
        entry = self._registry.get(action_id) if isinstance(action_id, str) else None
        if entry is None:
            return DecisionResult(GatewayOutcome.REJECT, reason=f"未知 action: {action_id!r}")
        # 3) target 解析 + kind 校验
        target = payload.get("target")
        td = self._resolver.resolve(target) if isinstance(target, str) else None
        if td is None or td.kind not in entry.target_kinds:
            return DecisionResult(GatewayOutcome.REJECT, reason=f"target 不合法: {target!r}")
        # 4) parameters 校验
        params = payload.get("parameters", {})
        perr = validate_parameters(entry.parameter_schema, params)
        if perr:
            return DecisionResult(GatewayOutcome.REJECT, reason=f"参数不合法: {perr}")
        # 5) eligibility（Gateway 独立计算，不采信 payload）
        inc = self._read_incident(incident_id)
        if inc is None:
            return DecisionResult(GatewayOutcome.REJECT, reason="incident 不存在")
        ctx = build_context(inc)
        if not is_eligible(ctx):
            return DecisionResult(GatewayOutcome.REJECT,
                                  reason=f"not eligible: verdict={ctx.verdict}")
        # 6) risk / 7) policy（纯函数）
        final_risk = evaluate_risk(entry, td, params)
        decision = decide(entry, final_risk, actor_context)
        # 8) fingerprint + canonical snapshot（P2→P3 seam）
        fp = proposal_fingerprint(ctx, entry.action_id, td, params, final_risk, decision,
                                  self._registry.version)
        snapshot = DecisionSnapshot(
            context=ctx, action_id=entry.action_id, target_descriptor=td,
            parameters=MappingProxyType(dict(params)), registry_version=self._registry.version,
            final_risk=final_risk, policy_decision=decision, proposal_fingerprint=fp)
        return DecisionResult(outcome=GatewayOutcome(decision.value), final_risk=final_risk,
                              policy_decision=decision, proposal_fingerprint=fp, snapshot=snapshot)

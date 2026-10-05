from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Mapping

if TYPE_CHECKING:                      # 仅类型注解；运行时无循环依赖
    from app.actions.context import V1DecisionContext


class PermissionLevel(str, Enum):
    READ = "READ"
    LOW_WRITE = "LOW_WRITE"
    HIGH_WRITE = "HIGH_WRITE"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyDecision(str, Enum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"


class GatewayOutcome(str, Enum):
    ALLOW = "ALLOW"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    DENY = "DENY"
    REJECT = "REJECT"      # 校验/资格失败；未进入决策，与三态区分


# I2 fail-closed：proposal 顶层唯一允许的 key；其余一律拒（含未知名）。
ALLOWED_PROPOSAL_KEYS = frozenset({"action_id", "target", "parameters", "reason"})

# spec §4 / I2：Agent 不得自报的权威字段；即使顶层 allowlist 有遗漏，这些也专门拒。
FORBIDDEN_PROPOSAL_KEYS = frozenset({
    "risk_level", "permission_level", "approval_required", "eligibility",
    "requested_by", "actor", "actor_context",
})


@dataclass(frozen=True)
class TargetDescriptor:
    kind: str
    environment: str
    replicas: int | None = None


@dataclass(frozen=True)
class Proposal:
    action_id: str
    target: str
    parameters: dict
    reason: str = ""


@dataclass(frozen=True)
class DecisionSnapshot:
    """P2→P3 seam：Gateway 已验证的 canonical 决策快照（不可变）。

    P3 构造 sealed order 时必须消费它，而不是重新读取原始 proposal。
    context 为**完整的** V1DecisionContext 快照（不可变）；parameters 为只读视图。
    """
    context: "V1DecisionContext"
    action_id: str
    target_descriptor: TargetDescriptor
    parameters: Mapping[str, object]
    registry_version: str
    final_risk: RiskLevel
    policy_decision: PolicyDecision
    proposal_fingerprint: str


@dataclass(frozen=True)
class DecisionResult:
    outcome: GatewayOutcome
    reason: str = ""
    final_risk: RiskLevel | None = None
    policy_decision: PolicyDecision | None = None
    proposal_fingerprint: str | None = None
    snapshot: DecisionSnapshot | None = None   # REJECT 时为 None

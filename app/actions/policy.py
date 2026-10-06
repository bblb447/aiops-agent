from app.actions.model import PermissionLevel, PolicyDecision, RiskLevel
from app.actions.registry import ActionEntry
from app.auth.model import ActorContext


def decide(entry: ActionEntry, final_risk: RiskLevel, actor_context: ActorContext) -> PolicyDecision:
    """纯函数：三态决策；CRITICAL 无条件 DENY；三态与 risk 不一一绑定。"""
    if entry.permission_level is PermissionLevel.CRITICAL:
        return PolicyDecision.DENY
    if entry.permission_level is PermissionLevel.HIGH_WRITE:
        return PolicyDecision.APPROVAL_REQUIRED
    if final_risk is RiskLevel.HIGH:
        return PolicyDecision.APPROVAL_REQUIRED
    return PolicyDecision.ALLOW

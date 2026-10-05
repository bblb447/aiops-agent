from app.actions.model import PermissionLevel, RiskLevel, TargetDescriptor
from app.actions.registry import ActionEntry

_RANK = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
_BY_RANK = {v: k for k, v in _RANK.items()}


def risk_rank(level: RiskLevel) -> int:
    return _RANK[level]


def evaluate_risk(entry: ActionEntry, target: TargetDescriptor, parameters: dict) -> RiskLevel:
    """纯函数：final_risk >= base_risk；示例上调规则（prod 写操作 / 单副本 → 至少 HIGH）。"""
    rank = _RANK[entry.base_risk]
    is_write = entry.permission_level in (PermissionLevel.LOW_WRITE,
                                          PermissionLevel.HIGH_WRITE,
                                          PermissionLevel.CRITICAL)
    if target.environment == "prod" and is_write:
        rank = max(rank, _RANK[RiskLevel.HIGH])
    if target.replicas is not None and target.replicas <= 1:
        rank = max(rank, _RANK[RiskLevel.HIGH])
    return _BY_RANK[rank]

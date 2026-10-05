from app.actions.model import PolicyDecision, RiskLevel
from app.actions.policy import decide
from app.actions.registry import default_registry


def _entry(action_id):
    return default_registry().get(action_id)


def test_critical_always_denied():
    assert decide(_entry("delete_namespace"), RiskLevel.LOW, {}) is PolicyDecision.DENY


def test_high_write_requires_approval():
    assert decide(_entry("scale_deployment"), RiskLevel.LOW, {}) is PolicyDecision.APPROVAL_REQUIRED


def test_low_write_high_risk_requires_approval():
    assert decide(_entry("restart_pod"), RiskLevel.HIGH, {}) is PolicyDecision.APPROVAL_REQUIRED


def test_low_write_low_risk_allowed():
    assert decide(_entry("restart_pod"), RiskLevel.LOW, {}) is PolicyDecision.ALLOW


def test_decision_not_bijective_with_risk():
    # 同一 risk 下不同 permission 得到不同 decision（证明非一一映射）。
    low_write = decide(_entry("restart_pod"), RiskLevel.LOW, {})
    high_write = decide(_entry("scale_deployment"), RiskLevel.LOW, {})
    assert low_write is not high_write

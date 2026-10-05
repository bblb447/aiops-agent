from app.actions.model import RiskLevel, TargetDescriptor
from app.actions.registry import default_registry
from app.actions.risk import evaluate_risk, risk_rank


def _entry(action_id):
    return default_registry().get(action_id)


def test_risk_rank_ordering():
    assert risk_rank(RiskLevel.LOW) < risk_rank(RiskLevel.MEDIUM) < risk_rank(RiskLevel.HIGH)


def test_risk_never_below_base():
    e = _entry("restart_pod")            # base_risk=MEDIUM
    r = evaluate_risk(e, TargetDescriptor(kind="pod", environment="staging", replicas=5), {})
    assert risk_rank(r) >= risk_rank(e.base_risk)


def test_prod_write_escalates_to_high():
    r = evaluate_risk(_entry("restart_pod"),
                      TargetDescriptor(kind="pod", environment="prod", replicas=5), {})
    assert r is RiskLevel.HIGH


def test_single_replica_escalates_to_high():
    r = evaluate_risk(_entry("restart_pod"),
                      TargetDescriptor(kind="pod", environment="staging", replicas=1), {})
    assert r is RiskLevel.HIGH


def test_staging_multi_replica_stays_at_base():
    r = evaluate_risk(_entry("restart_pod"),
                      TargetDescriptor(kind="pod", environment="staging", replicas=3), {})
    assert r is RiskLevel.MEDIUM


def test_risk_engine_is_pure_no_side_effects():
    e = _entry("restart_pod")
    td = TargetDescriptor(kind="pod", environment="prod", replicas=5)
    assert evaluate_risk(e, td, {}) == evaluate_risk(e, td, {})

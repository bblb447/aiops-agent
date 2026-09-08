"""L3 判定纯函数单测（L0，可进 CI；不含真实 LLM/后端调用）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.l3_real_backend import (  # noqa: E402
    a_no_false_positive_cpu,
    budget_compliance,
    evaluate_expect,
    scene_success,
)


def _rca(evidence_facts):
    class E:
        def __init__(self, source, fact):
            self.source, self.fact = source, fact

    class R:
        def __init__(self):
            self.evidence = [E("prometheus", f) for f in evidence_facts]

    return R()


def _obs(name, **over):
    base = {
        "name": name, "kind": "B", "read_tool_calls": 2, "budget": 4,
        "rca_valid": False, "rca": None, "status": "INSUFFICIENT_EVIDENCE",
        "submit_attempted": False, "rca_source": None, "evidence_sources": set(),
        "system_error": False,
    }
    base.update(over)
    return base


def test_budget_compliance():
    assert budget_compliance(3, 4) is True
    assert budget_compliance(4, 4) is True
    assert budget_compliance(5, 4) is False


def test_a_no_false_positive_cpu():
    # 无 rca（负向正确收敛为 INSUFFICIENT）→ 无虚构，通过。
    assert a_no_false_positive_cpu(None) is True
    # 真实证据（workload/error）不含 CPU 异常声称 → 通过。
    assert a_no_false_positive_cpu(_rca(["error_rate 0.2", "logs upstream timeout"])) is True
    # 虚构 CPU 异常 → 失败。
    assert a_no_false_positive_cpu(_rca(["CPU usage above 90%"])) is False
    assert a_no_false_positive_cpu(_rca(["high cpu caused the incident"])) is False
    # 局部否定守卫：marker 紧邻前文是否定词 → 不算虚构（首跑 A 的 "并未出现 CPU 高负载"）。
    assert a_no_false_positive_cpu(_rca(["实际 CPU 远低于 80% 阈值，服务本身并未出现 CPU 高负载"])) is True
    assert a_no_false_positive_cpu(_rca(["没有观察到 CPU 高负载，但 cpu 占用过高 持续存在"])) is False
    assert a_no_false_positive_cpu(_rca(["no high cpu observed in the logs"])) is True


def test_scene_success_a_negative_control():
    # 预算内 + INSUFFICIENT + 无虚构 + 无系统错误 → 负向控制通过。
    ok, reason = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca=None,
        status="INSUFFICIENT_EVIDENCE", submit_attempted=False, rca_source=None,
    ))
    assert ok, reason
    # 虚构 CPU 异常 → A 失败。
    ok2, reason2 = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca_valid=True,
        rca=_rca(["CPU saturation detected"]), status="ROOT_CAUSE_FOUND",
        submit_attempted=True, rca_source="tool",
    ))
    assert not ok2 and "false positive" in reason2
    # 臆造非 CPU 根因但终态 ROOT_CAUSE_FOUND（负向控制不允许臆造任何根因）→ A 失败。
    ok2b, reason2b = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca_valid=True,
        rca=_rca(["database overloaded caused the incident"]), status="ROOT_CAUSE_FOUND",
        submit_attempted=True, rca_source="tool",
    ))
    assert not ok2b and "INSUFFICIENT_EVIDENCE" in reason2b
    # 超预算 → A 失败。
    ok3, _ = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", read_tool_calls=6,
    ))
    assert not ok3


def test_scene_success_b_positive_multisource():
    ok, reason = scene_success("error_spike_multisource", _obs(
        "error_spike_multisource", rca_valid=True, status="ROOT_CAUSE_FOUND",
        evidence_sources={"prometheus", "loki"}, submit_attempted=True,
        rca_source="tool",
    ))
    assert ok, reason
    # 单源不算正向多源成功。
    ok2, _ = scene_success("error_spike_multisource", _obs(
        "error_spike_multisource", rca_valid=True, status="ROOT_CAUSE_FOUND",
        evidence_sources={"prometheus"}, submit_attempted=True, rca_source="tool",
    ))
    assert not ok2


def test_scene_success_c_fallback():
    ok, reason = scene_success("hybrid_fallback_observation", _obs(
        "hybrid_fallback_observation", rca_valid=True, status="ROOT_CAUSE_FOUND",
        submit_attempted=False, rca_source="final_answer",
    ))
    assert ok, reason
    # 尝试过 submit 再兜底 ≠ 干净 fallback → C 失败。
    ok2, _ = scene_success("hybrid_fallback_observation", _obs(
        "hybrid_fallback_observation", rca_valid=True, status="ROOT_CAUSE_FOUND",
        submit_attempted=True, rca_source="final_answer",
    ))
    assert not ok2


def test_evaluate_expect():
    def rec(name, ok=True, rca_source=None, sa=None, bc=True):
        return {"name": name, "success": ok, "rca_source": rca_source,
                "submit_attempted": sa, "budget_compliance": bc}

    ok_a = rec("cpu_alert_negative_control")
    ok_b = rec("error_spike_multisource", rca_source="tool", sa=False)
    ok_c = rec("hybrid_fallback_observation", rca_source="final_answer", sa=False)
    assert evaluate_expect({"convergence"}, [ok_a, ok_b, ok_c]) is True
    assert evaluate_expect({"rca"}, [ok_a, ok_b, ok_c]) is True
    assert evaluate_expect({"tool"}, [ok_b, ok_c]) is True      # B/C 至少一个 tool
    assert evaluate_expect({"fallback"}, [ok_c]) is True          # C 干净 final
    assert evaluate_expect({"tool"}, [ok_c]) is False             # C 无 tool → 失败
    # C 先试 submit 再兜底 → fallback 门禁失败。
    assert evaluate_expect({"fallback"}, [rec("hybrid_fallback_observation",
                                              rca_source="final_answer", sa=True)]) is False
    # 有一场景超预算 → convergence 失败。
    assert evaluate_expect({"convergence"}, [ok_a, ok_b, rec("hybrid_fallback_observation",
                                                             rca_source="final_answer", sa=False, bc=False)]) is False

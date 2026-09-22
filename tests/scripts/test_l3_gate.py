"""L3 判定纯函数单测（L0，可进 CI；不含真实 LLM/后端调用）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.l3_real_backend import (  # noqa: E402
    a_no_false_positive_cpu,
    budget_compliance,
    build_trace,
    classify_loki_failure,
    evaluate_expect,
    evidence_correlation,
    loki_contract_success,
    loki_preflight_ok,
    merge_tool_calls,
    scene_success,
    select_scenarios,
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
        "verdict": None, "system_error": False,
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


def test_scene_success_a_negative_control_now_verdict_no_anomaly():
    # V1.7：负向正确 = verdict NO_ANOMALY（status RESOLVED），而非硬塞 INSUFFICIENT_EVIDENCE。
    ok, reason = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca_valid=True,
        verdict="NO_ANOMALY", status="RESOLVED", submit_attempted=True, rca_source="tool",
        rca=_rca(["实际 CPU 6.8% 低于阈值"]),
    ))
    assert ok, reason
    # 负向仍虚构 CPU 异常 → A 失败。
    ok2, reason2 = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca_valid=True,
        verdict="NO_ANOMALY", status="RESOLVED", submit_attempted=True, rca_source="tool",
        rca=_rca(["CPU saturation detected"]),
    ))
    assert not ok2 and "false positive" in reason2
    # 模型自报 ROOT_CAUSE_FOUND（即使无 CPU 声称、臆造非 CPU 根因）→ A 失败。
    ok2b, reason2b = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", rca_valid=True,
        verdict="ROOT_CAUSE_FOUND", status="ROOT_CAUSE_FOUND", submit_attempted=True,
        rca_source="tool", rca=_rca(["database overloaded caused the incident"]),
    ))
    assert not ok2b and "NO_ANOMALY" in reason2b
    # 超预算 → A 失败。
    ok3, _ = scene_success("cpu_alert_negative_control", _obs(
        "cpu_alert_negative_control", kind="A", verdict="NO_ANOMALY", read_tool_calls=6,
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


# ===== #11 L3 Loki contract（spec docs/superpowers/specs/2026-09-22-l3-loki-contract-design.md）=====


def _loki_obs(**over):
    base = {"name": "real_loki_contract", "kind": "L", "preflight_ok": True,
            "loki_calls": [], "evidence_sources": set(), "budget_compliance": True,
            "system_error": None, "rca": None}
    base.update(over)
    return base


def _ev(source, fact):
    class E:
        pass
    e = E()
    e.source, e.fact = source, fact
    return e


def test_loki_preflight_ok_against_real_contract_text():
    # 用真实 `_build_extra_description` 产物做断言，证明 preflight 能真识别出契约。
    from app.tools.logging import _build_extra_description

    ok, reason = loki_preflight_ok(_build_extra_description(["app"]), ["app"])
    assert ok, reason
    # 未声明 label key → 失败（L3 环境未配 LOKI_LABEL_KEYS）。
    ok2, _ = loki_preflight_ok(_build_extra_description([]), [])
    assert ok2 is False
    # description 里没有该 key → 失败。
    ok3, _ = loki_preflight_ok(_build_extra_description([]), ["app"])
    assert ok3 is False
    # 多 key 时首个 key 的推荐 selector 形态必须出现。
    ok4, _ = loki_preflight_ok(_build_extra_description(["app", "service_name"]),
                               ["app", "service_name"])
    assert ok4, reason


def test_loki_contract_success_three_invariants():
    # 三条全满足 → 通过，且不要求 RCA 正确、不要求调用顺序。
    ok, reason = loki_contract_success(_loki_obs(
        loki_calls=[{"query": "{app=\"order-service\"}", "success": True,
                     "result_count": 2, "error": None}],
        evidence_sources={"loki", "prometheus"},
    ))
    assert ok, reason
    # L3-2：没有成功调用 → 失败。
    ok2, r2 = loki_contract_success(_loki_obs(
        loki_calls=[{"query": "bad", "success": False, "result_count": 0,
                     "error": "Loki 返回错误（HTTP 400）：parse error"}]))
    assert ok2 is False and "L3-2" in r2
    # L3-3：成功但全空结果 → 失败。
    ok3, r3 = loki_contract_success(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 0}]))
    assert ok3 is False and "L3-3" in r3
    # L3-4：拿到非空日志但 evidence 无 loki → 失败。
    ok4, r4 = loki_contract_success(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 3}],
        evidence_sources={"prometheus"}))
    assert ok4 is False and "L3-4" in r4
    # 超预算 + system_error 均不参与 gate（spec §5.1）。
    ok5, reason5 = loki_contract_success(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 1}],
        evidence_sources={"loki"}, budget_compliance=False,
        system_error="APIError: boom"))
    assert ok5, reason5


def test_classify_loki_failure():
    assert classify_loki_failure(_loki_obs(preflight_ok=False)) == "F1_contract_not_exposed"
    assert classify_loki_failure(_loki_obs()) == "F2_no_loki_call"
    assert classify_loki_failure(_loki_obs(
        loki_calls=[{"query": "bare string", "success": False, "result_count": 0}])
    ) == "F2_invalid_logql_only"
    assert classify_loki_failure(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 0}])
    ) == "F3_valid_query_empty_result"
    assert classify_loki_failure(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 2}],
        evidence_sources={"prometheus"})
    ) == "F4_obtained_but_not_submitted"
    assert classify_loki_failure(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 2}],
        evidence_sources={"loki"}, budget_compliance=False)
    ) == "F5_budget_exhausted"
    # 全满足 → none。
    assert classify_loki_failure(_loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 2}],
        evidence_sources={"loki"})
    ) == "none"


def test_evidence_correlation_never_fails_and_ignores_non_loki():
    logs = ["HTTP 500 Internal Server Error", "order-service request failed status=500"]
    corr = evidence_correlation(
        [_ev("loki", "order-service returned HTTP 500 errors"),
         _ev("prometheus", "error rate 0.2")],
        logs)
    # 只对 loki 证据产出信号。
    assert [c["evidence_index"] for c in corr] == [0]
    assert corr[0]["status"] == "CORRELATED"
    assert "500" in corr[0]["overlap"]
    # 无重叠 → UNCERTAIN（合法摘要场景），且【没有】任何 FAIL 状态。
    corr2 = evidence_correlation([_ev("loki", "服务出现错误")], logs)
    assert corr2[0]["status"] == "UNCERTAIN"
    assert all(c["status"] in ("CORRELATED", "UNCERTAIN") for c in corr2)
    # 无日志 → 全部 UNCERTAIN，不抛异常。
    assert evidence_correlation([_ev("loki", "x y")], [])[0]["status"] == "UNCERTAIN"


def test_merge_tool_calls_pairs_loki_records_in_order():
    order = ["query_workload", "search_logs", "search_logs", "submit_rca_result"]
    calls = [{"query": "q1", "success": True, "error": None, "result_count": 1},
             {"query": "q2", "success": False, "error": "HTTP 400", "result_count": 0}]
    merged = merge_tool_calls(order, calls)
    assert [m["tool"] for m in merged] == order
    assert merged[1]["query"] == "q1" and merged[1]["result_count"] == 1
    assert merged[2]["query"] == "q2" and merged[2]["success"] is False
    # 非 loki 工具只记名字（最小插桩）。
    assert set(merged[0]) == {"tool"}


def test_build_trace_shape():
    class _R:
        evidence = [_ev("loki", "order-service returned HTTP 500 errors")]

    trace = build_trace(
        {"name": "real_loki_contract"}, "deepseek-v4-flash",
        {"tool_order": ["search_logs"], "rca": _R(),
         "loki_calls": [{"query": "{app=\"x\"}", "success": True, "status": None,
                         "result_count": 1, "logs": ["line"]}],
         "evidence_correlation": [{"evidence_index": 0, "source": "loki",
                                   "status": "CORRELATED", "overlap": ["500"]}]})
    assert trace["scene"] == "real_loki_contract"
    assert trace["model"] == "deepseek-v4-flash"
    assert trace["tool_calls"] == [{"tool": "search_logs", "query": "{app=\"x\"}",
                                    "success": True, "error": None, "result_count": 1}]
    assert trace["evidence"] == [{"source": "loki", "fact": "order-service returned HTTP 500 errors"}]
    assert trace["loki"][0]["logs"] == ["line"]
    assert trace["evidence_correlation"][0]["status"] == "CORRELATED"
    # 无 rca 时不抛异常。
    assert build_trace({"name": "x"}, "m", {})["evidence"] == []


def test_scene_success_delegates_to_loki_contract():
    # real_loki_contract 走专用判据：不含 system_error / budget 前置。
    ok, reason = scene_success("real_loki_contract", _loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 2}],
        evidence_sources={"loki"}, budget_compliance=False, system_error="APIError: boom"))
    assert ok, reason
    # 未满足 L3-3 → 失败。
    ok2, reason2 = scene_success("real_loki_contract", _loki_obs(
        loki_calls=[{"query": "{app=\"x\"}", "success": True, "result_count": 0}]))
    assert not ok2 and "L3-3" in reason2


def test_scene_success_legacy_scenes_unaffected_by_new_scene():
    # A/B/C 语义零改动：既有用例已在上面覆盖，这里只钉住"新场景不影响它们"。
    ok, reason = scene_success("error_spike_multisource", _obs(
        "error_spike_multisource", rca_valid=True, status="ROOT_CAUSE_FOUND",
        evidence_sources={"prometheus", "loki"}, submit_attempted=True, rca_source="tool"))
    assert ok, reason


def test_evaluate_expect_loki_contract_is_separate_from_legacy_gates():
    def rec(name, ok=True, rca_source=None, sa=None, bc=True, lc=True):
        return {"name": name, "success": ok, "rca_source": rca_source,
                "submit_attempted": sa, "budget_compliance": bc,
                "loki_contract_ok": lc}

    ok_a = rec("cpu_alert_negative_control")
    ok_b = rec("error_spike_multisource", rca_source="tool", sa=False)
    lk = rec("real_loki_contract", lc=True)
    # loki_contract 只验证该场景自身。
    assert evaluate_expect({"loki_contract"}, [lk]) is True
    # 该场景失败 → loki_contract 门禁失败。
    assert evaluate_expect({"loki_contract"}, [rec("real_loki_contract", lc=False)]) is False
    # 没有该场景 → 门禁失败。
    assert evaluate_expect({"loki_contract"}, [ok_a]) is False
    # 既有门禁【不】把该场景算进去：lk 的 success/budget 均为 False 也不影响它们。
    ok_c = rec("hybrid_fallback_observation", rca_source="final_answer", sa=False)
    bad_lk = rec("real_loki_contract", ok=False, bc=False, lc=True)
    assert evaluate_expect({"all"}, [ok_a, ok_b, ok_c, bad_lk]) is True
    assert evaluate_expect({"rca"}, [ok_a, ok_b, ok_c, bad_lk]) is True
    assert evaluate_expect({"convergence"}, [ok_a, ok_b, ok_c, bad_lk]) is True
    # 对照：若把同一份 bad 记录换成既有场景，既有门禁必须失败。
    assert evaluate_expect({"rca"}, [ok_a, rec("error_spike_multisource", ok=False)]) is False


def _scenes():
    return [{"name": "cpu_alert_negative_control"},
            {"name": "error_spike_multisource"},
            {"name": "hybrid_fallback_observation"},
            {"name": "real_loki_contract"}]


def test_default_selection_excludes_loki_contract():
    # 默认运行集必须仍是 A/B/C —— 既有命令不得额外启动真实模型。
    names = [s["name"] for s in select_scenarios(_scenes(), [], [])]
    assert names == ["cpu_alert_negative_control", "error_spike_multisource",
                     "hybrid_fallback_observation"]
    # 既有门禁同理。
    for exp in (["rca"], ["all"], ["convergence"], ["tool"], ["fallback"]):
        assert "real_loki_contract" not in [s["name"] for s in
                                            select_scenarios(_scenes(), [], exp)]


def test_explicit_selection_includes_loki_contract():
    # 位置参数精确命中。
    assert [s["name"] for s in select_scenarios(_scenes(), ["real_loki_contract"], [])] \
        == ["real_loki_contract"]
    # --expect loki_contract → 只跑该场景（spec §9）。
    assert [s["name"] for s in select_scenarios(_scenes(), [], ["loki_contract"])] \
        == ["real_loki_contract"]
    # A/B/C 的既有子串过滤行为不变。
    assert [s["name"] for s in select_scenarios(_scenes(), ["error"], [])] \
        == ["error_spike_multisource"]
    # 对 L 只认精确名：`loki` 子串不得命中它。
    assert [s["name"] for s in select_scenarios(_scenes(), ["loki"], [])] == []

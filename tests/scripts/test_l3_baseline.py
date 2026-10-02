"""L3 Evaluation declarative baseline 单测（L0；纯函数、离线；不含真实 LLM/后端）。"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.l3_real_backend import (  # noqa: E402
    BASELINE_PATH,
    BaselineConfigError,
    load_baseline,
)

ROOT = Path(__file__).resolve().parents[2]


def _valid():
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def test_committed_baseline_path_exists():
    assert BASELINE_PATH.exists(), f"缺少 committed baseline：{BASELINE_PATH}"
    assert BASELINE_PATH.parent.name == "baselines"


def test_load_baseline_reads_committed_file():
    data = load_baseline()
    assert data["matrix"] == "l3-4-scenarios"
    assert set(data["scenarios"]) == {
        "cpu_alert_negative_control", "error_spike_multisource",
        "hybrid_fallback_observation", "real_loki_contract",
    }


def test_load_baseline_missing_file_raises(tmp_path):
    with pytest.raises(BaselineConfigError):
        load_baseline(tmp_path / "nope.json")


def test_load_baseline_bad_json_raises(tmp_path):
    p = tmp_path / "b.json"
    p.write_text("{ not json", encoding="utf-8")
    with pytest.raises(BaselineConfigError):
        load_baseline(p)

from scripts.l3_real_backend import validate_baseline  # noqa: E402

KNOWN = ("cpu_alert_negative_control", "error_spike_multisource",
         "hybrid_fallback_observation", "real_loki_contract")


def _scene(**over):
    base = {"kind": "B", "fields": [], "checks": [], "observation_only": []}
    base.update(over)
    return base


def _wrap(scenarios):
    return {"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": scenarios}


def test_committed_baseline_is_valid():
    assert validate_baseline(_valid()) == []


@pytest.mark.parametrize("data,needle", [
    ({"matrix": "l3-4-scenarios", "scenarios": {}}, "schema_version"),
    ({"schema_version": 1, "scenarios": {}}, "matrix"),
    ({"schema_version": 1, "matrix": "wrong", "scenarios": {}}, "matrix"),
    ({"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": []}, "scenarios"),
    (_wrap({"unknown_scene": _scene()}), "未知场景"),
    (_wrap({"error_spike_multisource": _scene(kind="Z")}), "kind"),
    (_wrap({"error_spike_multisource": _scene(fields=[{"id": "x", "field": "status", "op": "gte", "value": 1}])}), "op"),
    (_wrap({"error_spike_multisource": _scene(checks=[{"id": "c", "fn": "nope", "requires": "obs", "expect": True}])}), "fn"),
    (_wrap({"error_spike_multisource": _scene(checks=[{"id": "c", "fn": "loki_contract_success", "requires": "ip", "expect": True}])}), "requires"),
    (_wrap({"error_spike_multisource": _scene(fields=[{"field": "status", "op": "equals", "value": "x"}])}), "id"),
    (_wrap({"error_spike_multisource": _scene(fields=[
        {"id": "dup", "field": "status", "op": "equals", "value": "a"},
        {"id": "dup", "field": "status", "op": "equals", "value": "b"}])}), "重复"),
    (_wrap({"error_spike_multisource": _scene(fields=[{"id": "v", "field": "status", "op": "equals"}])}), "value"),
    (_wrap({"error_spike_multisource": _scene(observation_only=[1])}), "字符串"),
    (_wrap({"error_spike_multisource": {"kind": "B"}}), "checks"),
    ([1, 2], "对象"),
])
def test_validate_baseline_rejects(data, needle):
    errors = validate_baseline(data, known_scenes=KNOWN)
    assert errors, f"应当报错：{needle}"
    assert any(needle in e for e in errors), errors


from scripts.l3_real_backend import compare_run  # noqa: E402


class _E:
    def __init__(self, source, fact):
        self.source, self.fact = source, fact


class _R:
    def __init__(self, facts, sources=("prometheus", "loki")):
        self.evidence = [_E(s, f) for s, f in zip(sources, facts)]
        self.root_cause = "x"


def _obs(**over):
    base = {
        "name": "error_spike_multisource", "kind": "B",
        "rca_valid": True, "rca": _R(["a"]), "status": "ROOT_CAUSE_FOUND",
        "evidence_sources": {"prometheus", "loki"},
        "read_tool_calls": 3, "budget": 4, "budget_compliance": True,
        "total_steps": 5, "duration": 1.0, "rca_source": "tool",
        "submit_attempted": True, "tool_order": ["query_metric", "submit_rca_result"],
        "loki_calls": [], "system_error": None, "verdict": "ROOT_CAUSE_FOUND",
    }
    base.update(over)
    return base


BSC = {"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": {
    "error_spike_multisource": {
        "kind": "B",
        "fields": [
            {"id": "rca-valid", "field": "rca_valid", "op": "equals", "value": True},
            {"id": "terminal-status", "field": "status", "op": "equals", "value": "ROOT_CAUSE_FOUND"},
            {"id": "required-sources", "field": "evidence_sources", "op": "contains", "value": ["prometheus", "loki"]},
        ],
        "checks": [],
        "observation_only": ["read_tool_calls", "budget_compliance"],
    },
}}


def _res(rep, cid):
    return {c["id"]: c["result"] for c in rep["scenarios"][0]["constraints"]}[cid]


def test_no_observation_all_unobserved():
    rep = compare_run(BSC, {})
    assert rep["scenarios"][0]["coverage"] == "covered"
    assert {c["result"] for c in rep["scenarios"][0]["constraints"]} == {"UNOBSERVED"}


def test_all_pass_when_satisfied():
    rep = compare_run(BSC, {"error_spike_multisource": _obs()})
    assert {c["result"] for c in rep["scenarios"][0]["constraints"]} == {"PASS"}


def test_contains_accepts_superset():
    rep = compare_run(BSC, {"error_spike_multisource": _obs(
        evidence_sources={"prometheus", "loki", "runbook"})})
    assert _res(rep, "required-sources") == "PASS"


def test_contains_rejects_subset():
    rep = compare_run(BSC, {"error_spike_multisource": _obs(evidence_sources={"prometheus"})})
    assert _res(rep, "required-sources") == "FAIL"


def test_equals_set_is_exact_operator():
    from scripts.l3_real_backend import OPS
    assert OPS["equals_set"]({"a", "b"}, ["a", "b"]) is True
    assert OPS["equals_set"]({"a", "b", "c"}, ["a", "b"]) is False
    assert OPS["contains"]({"a", "b", "c"}, ["a", "b"]) is True


def test_null_field_fails_concrete_constraint():
    rep = compare_run(BSC, {"error_spike_multisource": _obs(status=None)})
    assert _res(rep, "terminal-status") == "FAIL"


def test_missing_field_is_unobserved():
    obs = _obs()
    del obs["evidence_sources"]
    rep = compare_run(BSC, {"error_spike_multisource": obs})
    assert _res(rep, "required-sources") == "UNOBSERVED"


def test_run_scene_not_in_baseline_is_not_covered():
    rep = compare_run(BSC, {"real_loki_contract": _obs(name="real_loki_contract", kind="L")})
    cov = {s["name"]: s for s in rep["scenarios"]}
    assert cov["error_spike_multisource"]["coverage"] == "covered"
    assert cov["real_loki_contract"]["coverage"] == "not covered"
    assert cov["real_loki_contract"]["constraints"] == []


def test_check_requires_missing_artifact_is_unobserved():
    b = {"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": {
        "cpu_alert_negative_control": {
            "kind": "A", "fields": [],
            "checks": [{"id": "no-fabricated-cpu", "fn": "a_no_false_positive_cpu",
                        "requires": "rca", "expect": True}],
            "observation_only": ["verdict"],
        }}}
    rep = compare_run(b, {"cpu_alert_negative_control": _obs(name="cpu_alert_negative_control",
                                                             kind="A", rca=None)})
    assert rep["scenarios"][0]["constraints"][0]["result"] == "UNOBSERVED"


def test_derived_observation_loki_failure_class():
    b = {"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": {
        "real_loki_contract": {"kind": "L", "fields": [], "checks": [],
                               "observation_only": ["loki_failure_class"]}}}
    obs = _obs(name="real_loki_contract", kind="L")
    rep = compare_run(b, {"real_loki_contract": obs})
    assert rep["scenarios"][0]["observations"]["loki_failure_class"] is not None


def test_observation_normalizes_set_to_sorted_list():
    b = {"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": {
        "error_spike_multisource": {"kind": "B", "fields": [], "checks": [],
                                    "observation_only": ["evidence_sources"]}}}
    rep = compare_run(b, {"error_spike_multisource": _obs(
        evidence_sources={"loki", "prometheus"})})
    assert rep["scenarios"][0]["observations"]["evidence_sources"] == ["loki", "prometheus"]


from scripts.l3_real_backend import (  # noqa: E402
    EXIT_BASELINE_CONFIG_ERROR,
    build_snapshot,
    compare_exit_code,
    format_baseline_report,
    main,
)
from scripts.l3_real_backend import SNAPSHOT_FIELDS  # noqa: E402


def _rep(result):
    return {"scenarios": [{"name": "error_spike_multisource", "kind": "B",
                           "coverage": "covered",
                           "constraints": [{"id": "x", "result": result, "detail": ""}],
                           "observations": {}}]}


@pytest.mark.parametrize("result,strict,expected", [
    ("PASS", False, 0),
    ("UNOBSERVED", False, 0),
    ("UNOBSERVED", True, 1),
    ("FAIL", False, 1),
    ("FAIL", True, 1),
])
def test_compare_exit_code(result, strict, expected):
    assert compare_exit_code(_rep(result), strict) == expected


def test_format_report_shows_scene_success_separately():
    obs = _obs()
    text = format_baseline_report(compare_run(BSC, {"error_spike_multisource": obs}),
                                  {"error_spike_multisource": obs})
    assert "coverage: covered" in text
    assert "scene_success:" in text
    assert "overall" not in text.lower()


def test_snapshot_excludes_forbidden_content():
    obs = _obs(root_cause="SECRET MODEL TEXT",
               evidence=[_E("loki", "SECRET LOG LINE")])
    obs["loki_calls"] = [{"query": 'SECRET QUERY {app="x"}', "logs": ["SECRET LOG LINE"],
                          "success": True, "status": None, "result_count": 2}]
    snap = build_snapshot([obs])[0]
    raw = json.dumps(snap, ensure_ascii=False)
    assert "SECRET" not in raw
    assert "root_cause" not in snap
    assert "query" not in raw
    assert "logs" not in raw
    assert snap["loki_calls"] == [{"success": True, "status": None, "result_count": 2}]


def test_snapshot_fields_are_exactly_the_allowlist():
    snap = build_snapshot([_obs()])[0]
    assert set(snap) == {"name", "kind", "loki_calls"} | set(SNAPSHOT_FIELDS)


def test_main_returns_config_error_on_broken_baseline(tmp_path):
    bad = tmp_path / "b.json"
    bad.write_text('{"schema_version": 1, "matrix": "l3-4-scenarios", "scenarios": {}}'
                   .replace("l3-4-scenarios", "wrong"), encoding="utf-8")
    rc = main(["--compare", "--baseline", str(bad)])
    assert rc == EXIT_BASELINE_CONFIG_ERROR


def test_main_returns_config_error_on_missing_baseline(tmp_path):
    rc = main(["--compare", "--baseline", str(tmp_path / "nope.json")])
    assert rc == EXIT_BASELINE_CONFIG_ERROR

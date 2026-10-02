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

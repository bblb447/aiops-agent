"""<rca_result> 区块解析与 RCAResult schema 校验测试（final JSON 兜底通道）。"""
import json

from app.agent.final_parse import extract_rca_result


def _block(data) -> str:
    return "调查结论：问题在发布。\n\n<rca_result>\n" + json.dumps(data, ensure_ascii=False) + "\n</rca_result>\n结束。"


def test_extract_valid_block():
    text = _block({
        "root_cause": "deployment_regression",
        "confidence": 0.87,
        "evidence": [{"source": "prometheus", "fact": "CPU 涨到 95%"}],
    })
    r, code = extract_rca_result(text)
    assert code is None
    assert r is not None
    assert r.root_cause == "deployment_regression"
    assert r.evidence[0].source == "prometheus"


def test_no_block_returns_none_none():
    r, code = extract_rca_result("没有任何区块的普通文本。")
    assert r is None and code is None


def test_empty_text():
    r, code = extract_rca_result("")
    assert r is None and code is None


def test_block_invalid_json_is_missing_evidence():
    r, code = extract_rca_result("x<rca_result>{not json}</rca_result>y")
    assert r is None
    assert code == "MISSING_EVIDENCE"


def test_block_evidence_as_strings_rejected():
    # 模型把 evidence 写成字符串数组 → schema 必须拒绝 → MISSING_EVIDENCE。
    r, code = extract_rca_result(_block({
        "root_cause": "x",
        "confidence": 0.8,
        "evidence": ["CPU 很高", "GC 增加"],
    }))
    assert r is None
    assert code == "MISSING_EVIDENCE"


def test_block_bad_confidence_is_low_confidence():
    r, code = extract_rca_result(_block({
        "root_cause": "x",
        "confidence": 1.5,
        "evidence": [{"source": "prometheus", "fact": "f"}],
    }))
    assert r is None
    assert code == "LOW_CONFIDENCE"


def test_block_string_confidence_rejected_low_confidence():
    # final 路径也必须拒绝字符串 confidence（P1：与工具路径同一 schema 语义）。
    r, code = extract_rca_result(_block({
        "root_cause": "x",
        "confidence": "0.8",
        "evidence": [{"source": "prometheus", "fact": "f"}],
    }))
    assert r is None
    assert code == "LOW_CONFIDENCE"


def test_block_missing_end_tag_rejected():
    r, code = extract_rca_result("x<rca_result>" + json.dumps({
        "root_cause": "x", "confidence": 0.8,
        "evidence": [{"source": "prometheus", "fact": "f"}],
    }))
    assert r is None
    assert code == "MISSING_EVIDENCE"


def test_block_embedded_in_long_text():
    # 区块嵌在自然语言里也能只取区块内容，不误读其他 JSON。
    text = ("根据分析……\n<rca_result>\n" + json.dumps(
        {"root_cause": "disk_full", "confidence": 0.95,
         "evidence": [{"source": "prometheus", "fact": "disk 99%"}]}) +
        "\n</rca_result>\n还需要继续观察。")
    r, code = extract_rca_result(text)
    assert r is not None
    assert r.root_cause == "disk_full"


# ===== V1.7 verdict-aware（spec §6：final 通道与 tool 同源） =====


def test_extract_no_anomaly_block():
    r, code = extract_rca_result(_block({
        "verdict": "NO_ANOMALY", "root_cause": None, "confidence": 0.96,
        "evidence": [{"source": "prometheus", "fact": "实际 CPU 6.8% 低于阈值"}]}))
    assert code is None
    assert r.verdict.value == "NO_ANOMALY"
    assert r.root_cause is None


def test_extract_inconclusive_block_ok_without_confidence():
    r, code = extract_rca_result(_block({
        "verdict": "INCONCLUSIVE", "root_cause": None,
        "evidence": [{"source": "prometheus", "fact": "波动但无法定因"}]}))
    assert code is None
    assert r.verdict.value == "INCONCLUSIVE"


def test_extract_no_anomaly_conflict_rejected():
    r, code = extract_rca_result(_block({
        "verdict": "NO_ANOMALY", "root_cause": "metric_alert_false_positive",
        "confidence": 0.9, "evidence": [{"source": "prometheus", "fact": "f"}]}))
    assert r is None
    assert code == "MISSING_EVIDENCE"


def test_extract_root_cause_found_missing_confidence_low_confidence():
    r, code = extract_rca_result(_block({
        "verdict": "ROOT_CAUSE_FOUND", "root_cause": "x",
        "evidence": [{"source": "prometheus", "fact": "f"}]}))
    assert r is None
    assert code == "LOW_CONFIDENCE"

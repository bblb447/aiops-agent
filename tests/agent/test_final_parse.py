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
        "evidence": [{"source": "s", "fact": "f"}],
    }))
    assert r is None
    assert code == "LOW_CONFIDENCE"


def test_block_missing_end_tag_rejected():
    r, code = extract_rca_result("x<rca_result>" + json.dumps({
        "root_cause": "x", "confidence": 0.8,
        "evidence": [{"source": "s", "fact": "f"}],
    }))
    assert r is None
    assert code == "MISSING_EVIDENCE"


def test_block_embedded_in_long_text():
    # 区块嵌在自然语言里也能只取区块内容，不误读其他 JSON。
    text = ("根据分析……\n<rca_result>\n" + json.dumps(
        {"root_cause": "disk_full", "confidence": 0.95,
         "evidence": [{"source": "node_exporter", "fact": "disk 99%"}]}) +
        "\n</rca_result>\n还需要继续观察。")
    r, code = extract_rca_result(text)
    assert r is not None
    assert r.root_cause == "disk_full"

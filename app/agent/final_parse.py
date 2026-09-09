"""从 Agent final 文本提取 <rca_result> 区块并校验为 RCAResult（兜底通道）。

混合收尾机制（docs/design.md 第 41 章）：
  submit_rca_result（工具）是首选；若本轮未产生有效 Tool RCA，
  则从 final_answer 中提取 <rca_result>...</rca_result> 内的 JSON，
  经同一 RCAResult schema 校验作为兜底。不猜自然语言里的任意 JSON。
"""
import json

from pydantic import ValidationError

from app.incident.codes import MISSING_EVIDENCE
from app.incident.model import RCAResult, rca_validation_code

BLOCK_START = "<rca_result>"
BLOCK_END = "</rca_result>"


def extract_rca_result(text: str | None) -> tuple[RCAResult | None, str | None]:
    """返回 (RCAResult, None) 成功；无区块 → (None, None)；区块非法 → (None, code)。

    code 与 submit 工具同源（rca_validation_code，spec §6.2）：
    confidence 问题 → LOW_CONFIDENCE；verdict/root_cause 等结构违例 → MISSING_EVIDENCE。
    verdict 缺失 + root_cause 非空按 ROOT_CAUSE_FOUND 兼容（legacy）。
    """
    if not text:
        return None, None
    start = text.find(BLOCK_START)
    if start == -1:
        return None, None
    body_start = start + len(BLOCK_START)
    end = text.find(BLOCK_END, body_start)
    if end == -1:
        return None, MISSING_EVIDENCE
    raw = text[body_start:end].strip()
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None, MISSING_EVIDENCE
    if not isinstance(data, dict):
        return None, MISSING_EVIDENCE
    try:
        result = RCAResult(**data)
    except ValidationError as e:
        return None, rca_validation_code(e)
    return result, None

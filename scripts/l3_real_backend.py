"""L3 Real LLM + Real Backend 观测脚本（spec docs/design.md §46）。

用法（backend 生命周期手动，脚本不隐式管理）：
    PYTHONIOENCODING=utf-8 python tests/integration/backend.py up
    PYTHONIOENCODING=utf-8 python scripts/l3_real_backend.py [--expect ...] [scene...]
    python tests/integration/backend.py down

判定纯函数在本文件顶部（可被 tests/scripts/test_l3_gate.py 作 L0 单测）；
真实 LLM 的 run 层（Task 2）与报告/main（Task 3）在本函数后追加。
exit code：缺 .env LLM key=2；backend 不可达=3；默认只观测=0（除非未捕获异常/系统错误）；
--expect 显式不满足=1。
"""
import os
import sys
from pathlib import Path

# 本地后端直连：绕过 Windows 系统代理（Clash 注册表代理会劫持 127.0.0.1 → HTTP 502）。
# 必须在任何 httpx 请求发生前设置。
os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), "127.0.0.1", "localhost"]))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CPU_FALSE_POSITIVE_MARKERS = ("cpu usage above", "cpu saturation", "high cpu",
                              "cpu 使用率", "cpu 高", "cpu 异常", "cpu 持续高", "cpu 占用过高")


def budget_compliance(read_total: int, budget: int) -> bool:
    return read_total <= budget


def a_no_false_positive_cpu(rca) -> bool:
    """A 负向判据：提交的 RCA（若有）不得虚构 CPU 异常证据。无 RCA 视为无虚构。"""
    if rca is None:
        return True
    for e in getattr(rca, "evidence", []) or []:
        text = f"{getattr(e, 'fact', '')} {getattr(e, 'source', '')}".lower()
        if any(m in text for m in CPU_FALSE_POSITIVE_MARKERS):
            return False
    return True


def scene_success(name: str, obs: dict) -> tuple[bool, str]:
    """按 §46.5 场景语义判单场景成功。obs 需含：read_tool_calls/budget/rca_valid/
    evidence_sources/status/submit_attempted/rca_source/rca/system_error。

    A（负向控制）= 预算内 + 无虚构 CPU 异常 + 不因系统错误失败（不要求 ROOT_CAUSE_FOUND）；
    B（正向多源）= 预算内 + 合法 RCA + ROOT_CAUSE_FOUND + evidence_sources == {prometheus, loki}；
    C（Hybrid 兜底）= 预算内 + submit_attempted 为 False + 合法 RCA + final_answer + ROOT_CAUSE_FOUND。
    INSUFFICIENT_EVIDENCE 显式通过仅适用于 A。
    """
    if obs.get("system_error"):
        return False, "system_error"
    if not budget_compliance(obs.get("read_tool_calls", 0), obs.get("budget", 4)):
        return False, "budget exceeded"
    if name == "cpu_alert_negative_control":
        if not a_no_false_positive_cpu(obs.get("rca")):
            return False, "false positive cpu evidence"
        return True, "negative control ok (INSUFFICIENT or no fp)"
    if name == "error_spike_multisource":
        if not (obs.get("rca_valid") and obs.get("status") == "ROOT_CAUSE_FOUND"
                and obs.get("evidence_sources") == {"prometheus", "loki"}):
            return False, f"need valid rca + ROOT_CAUSE_FOUND + sources {{prom,loki}}; got {obs.get('evidence_sources')}"
        return True, "multisource rca ok"
    if name == "hybrid_fallback_observation":
        if not (obs.get("submit_attempted") is False and obs.get("rca_valid")
                and obs.get("rca_source") == "final_answer"
                and obs.get("status") == "ROOT_CAUSE_FOUND"):
            return False, "need no-submit + valid rca + final_answer + ROOT_CAUSE_FOUND"
        return True, "fallback rca ok"
    return False, f"unknown scene {name}"


def evaluate_expect(expects: set[str], results: list[dict]) -> bool:
    """--expect 语义（§46.6）。results 每项含 name/success/rca_source/submit_attempted/
    budget_compliance。

    convergence：所有场景 budget_compliance=True（独立于场景业务成功）；
    rca：所有场景 scene_success=True；
    tool：B/C 中至少一个 rca_source=='tool'（真实模型非确定，不要求全中）；
    fallback：C rca_source=='final_answer' 且 submit_attempted 为 False；
    all：以上全部叠加。
    """
    expects = set(expects)
    if not results or not expects:
        return False
    if "convergence" in expects or "all" in expects:
        if not all(r.get("budget_compliance") for r in results):
            return False
    if "rca" in expects or "all" in expects:
        if not all(r.get("success") for r in results):
            return False
    if "tool" in expects or "all" in expects:
        bc = [r for r in results if r["name"] in ("error_spike_multisource", "hybrid_fallback_observation")]
        if not any(r.get("rca_source") == "tool" for r in bc):
            return False
    if "fallback" in expects or "all" in expects:
        c = [r for r in results if r["name"] == "hybrid_fallback_observation"]
        if not (c and c[0].get("rca_source") == "final_answer" and c[0].get("submit_attempted") is False):
            return False
    return True

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

    A（负向控制）= 预算内 + 无虚构 CPU 异常 + 不因系统错误失败 + 最终 INSUFFICIENT_EVIDENCE
      （V1 状态机预期终态；负向控制不允许臆造任何根因，故 ROOT_CAUSE_FOUND 即使无 CPU 声称也不通过）；
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
        if obs.get("status") != "INSUFFICIENT_EVIDENCE":
            return False, f"expected INSUFFICIENT_EVIDENCE; got {obs.get('status')}"
        return True, "negative control ok"
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


import time  # noqa: E402

from app.agent import agent as _agent_mod  # noqa: E402
from app.agent.agent import investigate  # noqa: E402
from app.config import Settings  # noqa: E402
from app.incident.service import IncidentService  # noqa: E402
from app.llm.provider import LiteLLMProvider  # noqa: E402
from app.tools.knowledge import KnowledgeTool  # noqa: E402
from app.tools.logging import LoggingTool  # noqa: E402
from app.tools.monitoring import MonitoringTool  # noqa: E402

# 真实后端地址（backend.py up 后可用；scripts 不隐式管理生命周期）。
PROM_URL = "http://127.0.0.1:9090"
LOKI_URL = "http://127.0.0.1:3100"
CMDB_URL = "http://127.0.0.1:8081"

SCENARIOS = [
    dict(
        name="cpu_alert_negative_control", kind="A",
        title="order-service CPU 使用率高",
        service="order-service", severity="critical",
        observed_value=95.0, threshold=80.0, target="server-01",
        tools=("monitoring", "knowledge"),
    ),
    dict(
        name="error_spike_multisource", kind="B",
        title="order-service 错误率上升（HTTP 500）",
        service="order-service", severity="major",
        observed_value=None, threshold=None, target=None,
        tools=("monitoring", "logging", "knowledge"),
    ),
    dict(
        name="hybrid_fallback_observation", kind="C",
        title="order-service 服务异常",
        service="order-service", severity="critical",
        observed_value=None, threshold=None, target=None,
        tools=("monitoring", "logging"),
    ),
]

# 脚本层插桩（权威）：_READ_ORDER 只含只读工具调用（预算计数基础）；
# _FULL_ORDER 含只读 + submit（供 tool_order 展示整段轨迹）。
_READ_ORDER: list[str] = []
_FULL_ORDER: list[str] = []


def _bump_read(name: str) -> None:
    _READ_ORDER.append(name)
    _FULL_ORDER.append(name)


class _CountingMonitoring(MonitoringTool):
    """只读计数子类：调用真实 MonitoringTool 并记录到顺序表（不 mock、不改返回值）。"""

    def query_metric(self, metric: str, target: str = ""):
        _bump_read("query_metric")
        return super().query_metric(metric, target)

    def query_workload(self, service: str):
        _bump_read("query_workload")
        return super().query_workload(service)

    def query_metric_range(self, metric: str, target: str = "",
                           start=None, end=None, step: str = "60s"):
        _bump_read("query_metric_range")
        return super().query_metric_range(metric, target, start, end, step)


class _CountingLogging(LoggingTool):
    def search_logs(self, query: str, limit: int = 50, start=None, end=None):
        _bump_read("search_logs")
        return super().search_logs(query, limit, start, end)


class _CountingKnowledge(KnowledgeTool):
    def search_runbook(self, keyword: str):
        _bump_read("search_runbook")
        return super().search_runbook(keyword)


def make_tools(settings: Settings, scenario: dict) -> list:
    tools = []
    for name in scenario["tools"]:
        tools.append({
            "monitoring": _CountingMonitoring,
            "logging": _CountingLogging,
            "knowledge": _CountingKnowledge,
        }[name](settings))
    return tools


class _LoggingModel:
    """包真实模型做纯步数计数：generate 每次都转发给真实模型，不改行为。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self._inner.generate(messages, **kwargs)


def _run_scenario(scenario: dict) -> dict:
    _READ_ORDER.clear()
    _FULL_ORDER.clear()

    settings = Settings()  # 读 .env；仅 URL/rag 覆写，llm_* 与 agent_* 保持 .env/env 值
    settings.prometheus_url = PROM_URL
    settings.loki_url = LOKI_URL
    settings.cmdb_url = CMDB_URL
    settings.rag_enabled = False
    settings.agent_max_steps = int(os.environ.get("L3_MAX_STEPS", "10"))
    budget = settings.agent_max_read_tools

    holder: dict = {}
    _orig_make = LiteLLMProvider.make_agent_model

    def _wrap_model(self):
        holder["model"] = _LoggingModel(_orig_make(self))
        return holder["model"]

    _orig_submit = _agent_mod.SubmitRCATool

    class _RecordingSubmit(_orig_submit):
        """记录型 SubmitRCATool 子类：investigate 内部以本类实例化（agent.py 模块全局引用被
        临时替换），实例被捕获进 holder 供事后读 submit_attempted/校验码；不 mock、不改语义。"""

        def __init__(self, svc, incident_id):
            super().__init__(svc, incident_id)
            holder["submit_tool"] = self

        def submit_rca_result(self, *args, **kwargs):
            _FULL_ORDER.append("submit_rca_result")
            return super().submit_rca_result(*args, **kwargs)

    svc = IncidentService()
    inc = svc.create(
        scenario["title"], scenario["service"], scenario["severity"],
        source="prometheus", alert_id="alert-l3", target=scenario.get("target"),
        observed_value=scenario.get("observed_value"),
        threshold=scenario.get("threshold"),
    )

    t0 = time.time()
    system_error = None
    try:
        LiteLLMProvider.make_agent_model = _wrap_model
        _agent_mod.SubmitRCATool = _RecordingSubmit
        investigate(settings, svc, inc.incident_id, tools=make_tools(settings, scenario))
    except Exception as e:  # noqa: BLE001 - 真实 LLM/网络异常记为观测；investigate 已把最终状态落库
        system_error = f"{type(e).__name__}: {e}"
    finally:
        LiteLLMProvider.make_agent_model = _orig_make
        _agent_mod.SubmitRCATool = _orig_submit

    got = None
    try:
        got = svc.get(inc.incident_id)  # 无论 investigate 正常/异常，都读最终落库状态
    except Exception as e:  # noqa: BLE001
        system_error = system_error or f"{type(e).__name__}: {e}"

    read_total = len(_READ_ORDER)
    sub = holder.get("submit_tool")
    model = holder.get("model")
    obs = {
        "name": scenario["name"], "kind": scenario["kind"], "title": scenario["title"],
        "duration": round(time.time() - t0, 1),
        "read_tool_calls": read_total,
        "budget": budget,
        "budget_compliance": budget_compliance(read_total, budget),
        "tool_order": list(_FULL_ORDER),
        "system_error": system_error,
        # submit_attempted 走权威 holder（investigate 事务内同一 SubmitRCATool 实例），
        # 不做任何消息内容/字符串搜索。
        "submit_attempted": bool(sub and sub.submit_attempted),
        "submit_last_validation_code": sub.last_validation_code if sub else None,
        "total_steps": len(model.calls) if model else 0,
    }
    if got is not None:
        obs.update({
            "rca_valid": got.rca is not None,
            "rca_source": got.rca_source,
            "status": got.status.value if getattr(got.status, "value", None) else got.status,
            "failure_code": got.failure_code,
            "root_cause": got.rca.root_cause if got.rca else None,
            "evidence_count": len(got.rca.evidence) if got.rca else 0,
            "evidence_sources": {e.source for e in got.rca.evidence} if got.rca else set(),
            "rca": got.rca,
        })
    else:
        obs.update({"rca_valid": False, "rca_source": None, "status": None,
                    "failure_code": None, "root_cause": None,
                    "evidence_count": 0, "evidence_sources": set(), "rca": None})
    return obs


import argparse  # noqa: E402

import httpx  # noqa: E402


def _fmt(obs: dict, model_name: str) -> str:
    read = obs.get("read_tool_calls", 0)
    budget = obs.get("budget", 4)
    lines = [
        f"Scenario: {obs['name']}  [{obs['kind']}]",
        f"title: {obs.get('title', '')}",
        f"Model: {model_name} | duration: {obs['duration']}s",
        f"read_tool_calls: {read} | max_read_tools: {budget} | "
        f"budget_compliance: {'PASS' if budget_compliance(read, budget) else 'FAIL'} | "
        f"total_steps: {obs.get('total_steps', 0)}",
        "tool_order:",
    ]
    order = obs.get("tool_order") or []
    lines += [f"  {t}" for t in order] if order else ["  -"]
    if obs.get("system_error"):
        lines.append(f"system_error: {obs['system_error']}")
    ok, reason = scene_success(obs["name"], obs)
    lines.append(f"scene_success: {'PASS' if ok else 'FAIL'} ({reason})")
    lines.append(f"submit_attempted: {obs.get('submit_attempted')} | rca_source: {obs.get('rca_source')} | "
                 f"rca_valid: {obs.get('rca_valid')} | status: {obs.get('status')} | "
                 f"failure_code: {obs.get('failure_code')}")
    if obs.get("kind") == "A":
        fp = a_no_false_positive_cpu(obs.get("rca"))
        lines.append(f"false_positive_cpu_evidence: {'NOT_FOUND' if fp else 'FOUND'}")
    if obs.get("evidence_count"):
        lines.append(f"evidence: {obs['evidence_count']} -> {sorted(obs.get('evidence_sources') or [])}")
    if obs.get("root_cause"):
        lines.append(f"root_cause: {obs['root_cause'][:140]}")
    return "\n".join(lines)


def _summary(results: list[dict], model_name: str) -> str:
    n = max(len(results), 1)
    tool_hits = sum(1 for o in results if o.get("rca_source") == "tool")
    final_hits = sum(1 for o in results if o.get("rca_source") == "final_answer")
    all_reads = [o.get("read_tool_calls", 0) for o in results]
    valid = sum(1 for o in results if o.get("rca_valid"))
    bc_ok = sum(1 for o in results if o.get("budget_compliance"))
    return "\n".join([
        "==== 汇总 ====",
        f"model: {model_name}",
        f"tool_path_rate: {tool_hits}/{len(results)}  final_fallback_rate: {final_hits}/{len(results)}",
        f"avg_read_calls: {sum(all_reads) / n:.1f}  max_read_calls: {max(all_reads) if all_reads else 0}",
        f"rca_valid_rate: {valid}/{len(results)}  budget_compliance_rate: {bc_ok}/{len(results)}",
    ])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="l3_real_backend")
    parser.add_argument("--expect", action="append", default=[],
                        choices=["rca", "convergence", "tool", "fallback", "all"],
                        help="可选门禁（默认只观测不失败）")
    parser.add_argument("scene", nargs="*", help="场景名子串过滤（如 cpu / error / hybrid）")
    args = parser.parse_args(argv)

    settings = Settings()
    if not settings.llm_api_key:
        print("缺少 LLM API Key：请先配置 .env 的 llm_api_key / llm_base_url / llm_model")
        return 2

    # 不隐式管理 backend：探测真实后端可达性，给出友好提示。
    try:
        httpx.get(f"{PROM_URL}/-/ready", timeout=3).raise_for_status()
    except httpx.HTTPError:
        print(f"后端未就绪：请先运行 python tests/integration/backend.py up（需 {PROM_URL} 可达）")
        return 3

    selected = [s for s in SCENARIOS
                if not args.scene or any(f in s["name"] for f in args.scene)]
    print("\n==== L3 Real LLM + Real Backend 观测 ====")
    print(f"model={settings.llm_model}  预算(read)={settings.agent_max_read_tools}  "
          f"max_steps={settings.agent_max_steps}  场景数={len(selected)}\n")

    results = []
    for s in selected:
        print(f"--- [{s['kind']}] {s['name']} | {s['title']} | tools={s['tools']} ---")
        obs = _run_scenario(s)
        print(_fmt(obs, settings.llm_model))
        print()
        results.append(obs)

    print(_summary(results, settings.llm_model))
    for obs in results:
        ok, _reason = scene_success(obs["name"], obs)
        print(f"  {obs['name']:<32} scene_success={'PASS' if ok else 'FAIL'} "
              f"rca_source={obs.get('rca_source') or '-'} status={obs.get('status')}")

    expects = set(args.expect)
    if not expects:
        return 0  # 默认只观测，不因模型行为判失败。
    proj = [{
        "name": o["name"],
        "success": scene_success(o["name"], o)[0],
        "rca_source": o.get("rca_source"),
        "submit_attempted": o.get("submit_attempted"),
        "budget_compliance": o.get("budget_compliance"),
    } for o in results]
    passed = evaluate_expect(expects, proj)
    print(f"--expect {sorted(expects)} -> {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

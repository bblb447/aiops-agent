"""V1.6 收敛复验（真实 LLM，手工运行）：生产诊断 prompt（已固化预算+判据）在不同场景下是否收敛。

用法（仓库根目录）：
    python scripts/experiment_convergence.py             # 跑全部场景
    python scripts/experiment_convergence.py multi       # 按名字子串过滤（可多个）

场景（§42.9-3 扩场景复验）：
    cpu_single_source    一次查询即可判断的 CPU 场景（基线验证过，保留对照）
    multi_source_mem_gc   监控(CPU/内存) + 日志(Full GC/OOM) 多来源
    release_regression   监控(错误率) + 日志(部署 v2.3.1 后抛 NPE) 发布回归

只读调用计数在脚本层对工具实例插桩（权威），不解析模型消息。验收：预算(≤4)内收敛、RCA 合法。
"""
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.agent.agent import investigate  # noqa: E402
from app.config import Settings  # noqa: E402
from app.incident.service import IncidentService  # noqa: E402
from app.tools.knowledge import KnowledgeTool  # noqa: E402
from app.tools.logging import LoggingTool  # noqa: E402
from app.tools.monitoring import MonitoringTool  # noqa: E402

SCENARIOS = [
    dict(
        name="cpu_single_source",
        title="order-service CPU 持续高",
        service="order-service", severity="critical",
        hot=("cpu",),
        loki_text=None,
        runbook_name="cpu-high.md",
        runbook_text="# CPU 高排查\n\nCPU 持续高通常与内存泄漏或发布有关，先查 Full GC 再查最近部署。",
        tools=("monitoring", "knowledge"),
    ),
    dict(
        name="multi_source_mem_gc",
        title="order-service 内存持续上涨伴随 Full GC",
        service="order-service", severity="critical",
        hot=("cpu", "mem", "gc"),
        loki_text="Full GC 频繁触发，日志出现 OutOfMemoryError: Java heap space，疑似最近发布引入内存泄漏",
        runbook_name="memory-leak.md",
        runbook_text="# 内存泄漏排查\n\n服务内存持续上涨并伴随 Full GC 时，优先怀疑最近发布引入内存泄漏，建议回滚最近版本。",
        tools=("monitoring", "logging", "knowledge"),
    ),
    dict(
        name="release_regression",
        title="payment-service 错误率升高",
        service="payment-service", severity="major",
        hot=("error", "http_request"),
        loki_text="deploy started v2.3.1 ... payment-service 抛 NullPointerException，错误率上升，疑似发布回归",
        runbook_name="rollback-release.md",
        runbook_text="# 发布回滚\n\n错误率在发布后升高时，优先怀疑新版本回归，建议回滚到上一稳定版本并观察。",
        tools=("monitoring", "logging", "knowledge"),
    ),
]


class _CountingMonitoring(MonitoringTool):
    # 签名须与基类一致，否则 _ToolAdapter 的 input schema 丢失命名参数。
    def query_metric(self, metric: str, target: str = ""):
        COUNTS["query_metric"] = COUNTS.get("query_metric", 0) + 1
        return super().query_metric(metric, target)

    def query_workload(self, service: str):
        COUNTS["query_workload"] = COUNTS.get("query_workload", 0) + 1
        return super().query_workload(service)

    def query_metric_range(self, metric: str, target: str = "",
                           start: int | None = None, end: int | None = None,
                           step: str = "60s"):
        COUNTS["query_metric_range"] = COUNTS.get("query_metric_range", 0) + 1
        return super().query_metric_range(metric, target, start, end, step)


class _CountingLogging(LoggingTool):
    def search_logs(self, query: str, limit: int = 50,
                    start: int | None = None, end: int | None = None):
        COUNTS["search_logs"] = COUNTS.get("search_logs", 0) + 1
        return super().search_logs(query, limit, start, end)


class _CountingKnowledge(KnowledgeTool):
    def search_runbook(self, keyword: str):
        COUNTS["search_runbook"] = COUNTS.get("search_runbook", 0) + 1
        return super().search_runbook(keyword)


COUNTS: dict[str, int] = {}


def make_fixture(scenario):
    hot = tuple(h.lower() for h in scenario["hot"])
    loki_text = scenario.get("loki_text")

    def fx(url, params=None, timeout=None):
        u = str(url)
        params = params or {}
        q = str(params.get("query", "")).lower()
        value = "95.2" if any(k in q for k in hot) else "23.5"
        req = httpx.Request("GET", u)
        if "/loki/" in u:
            if loki_text is None:
                return httpx.Response(200, request=req, json={"status": "success", "data": {"result": []}})
            return httpx.Response(200, request=req, json={
                "status": "success",
                "data": {"result": [{"stream": {"job": "app"}, "values": [[str(1710000000000000000), loki_text]]}]},
            })
        if "/api/v1/query_range" in u:
            return httpx.Response(200, request=req, json={
                "status": "success",
                "data": {"result": [{"metric": {"instance": "server-01"},
                                     "values": [[1710000000, value], [1710000060, value]]}]},
            })
        if "/api/v1/query" in u:
            return httpx.Response(200, request=req, json={
                "status": "success",
                "data": {"result": [{"metric": {"instance": "server-01"}, "value": [1710000000, value]}]},
            })
        return httpx.Response(404, request=req, json={})

    return fx


def make_tools(settings, scenario):
    tools = []
    for name in scenario["tools"]:
        if name == "monitoring":
            tools.append(_CountingMonitoring(settings))
        elif name == "logging":
            tools.append(_CountingLogging(settings))
        elif name == "knowledge":
            tools.append(_CountingKnowledge(settings))
    return tools


class _LoggingModel:
    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self._inner.generate(messages, **kwargs)


def run_one(scenario: dict, prompt_text: str) -> dict:
    from app.agent.agent import PROMPT_FILE
    from app.llm.provider import LiteLLMProvider
    import app.tools.knowledge as knowledge_mod

    _orig_prompt = PROMPT_FILE
    _orig_get = httpx.get
    _orig_runbook_dir = knowledge_mod.RUNBOOK_DIR
    _orig_make = LiteLLMProvider.make_agent_model

    COUNTS.clear()
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        prompt_file = tmp / "prompt.txt"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        runbook_dir = tmp / "runbooks"
        runbook_dir.mkdir()
        (runbook_dir / scenario["runbook_name"]).write_text(scenario["runbook_text"], encoding="utf-8")

        holder = {}
        def _wrapped(self):
            holder["model"] = _LoggingModel(_orig_make(self))
            return holder["model"]

        try:
            import app.agent.agent as agent_mod
            agent_mod.PROMPT_FILE = prompt_file
            knowledge_mod.RUNBOOK_DIR = runbook_dir
            httpx.get = make_fixture(scenario)
            LiteLLMProvider.make_agent_model = _wrapped

            settings = Settings()
            settings.prometheus_url = "http://fixture-prom:9090"
            settings.loki_url = "http://fixture-loki:3100"
            settings.rag_enabled = False
            settings.agent_max_steps = 8

            svc = IncidentService()
            inc = svc.create(scenario["title"], scenario["service"], scenario["severity"],
                             source="prometheus", alert_id="alert-001", target="server-01",
                             observed_value=95.2, threshold=80)
            investigate(settings, svc, inc.incident_id, tools=make_tools(settings, scenario))
            got = svc.get(inc.incident_id)
            reads = {k: v for k, v in COUNTS.items() if v > 0}
            return {
                "tag": scenario["name"],
                "generate_calls": len(holder["model"].calls),
                "read_tool_calls": sum(reads.values()),
                "unique_tools": sorted(reads),
                "tool_counts": reads,
                "rca_valid": got.rca is not None,
                "rca_source": got.rca_source,
                "status": got.status.value,
                "failure_code": got.failure_code,
                "root_cause": got.rca.root_cause if got.rca else None,
            }
        finally:
            import app.agent.agent as agent_mod
            agent_mod.PROMPT_FILE = _orig_prompt
            knowledge_mod.RUNBOOK_DIR = _orig_runbook_dir
            httpx.get = _orig_get
            LiteLLMProvider.make_agent_model = _orig_make


def _fmt(m: dict) -> str:
    counts = m.get("tool_counts") or {}
    return ("  {tag:<24} generate={generate_calls:<2} read_calls={read_tool_calls:<2} "
            "reads={counts} rca_source={rca_source} rca={rca_valid} "
            "status={status} failure_code={failure_code}").format(
                tag=m["tag"], generate_calls=m["generate_calls"], read_tool_calls=m["read_tool_calls"],
                counts=counts, rca_source=m["rca_source"] or "-",
                rca_valid="Y" if m["rca_valid"] else "n",
                status=m["status"], failure_code=m["failure_code"])


def main() -> int:
    settings = Settings()
    if not settings.llm_api_key:
        print("缺少 LLM API Key：请先配置 .env")
        return 2

    prompt_text = (ROOT / "prompts" / "diagnose.txt").read_text(encoding="utf-8")
    filters = sys.argv[1:]
    selected = SCENARIOS
    if filters:
        selected = [s for s in SCENARIOS if any(f in s["name"] for f in filters)]

    print("\n==== V1.6 收敛复验（真实 LLM，生产 diagnose.txt prompt）====")
    print(f"model={settings.llm_model}  只读预算=4  max_steps=8  场景数={len(selected)}\n")
    for s in selected:
        print(f"--- {s['name']} | {s['title']} | tools={s['tools']} ---")
        try:
            m = run_one(s, prompt_text)
        except Exception as e:  # noqa: BLE001
            print(f"  {s['name']} 异常: {type(e).__name__}: {e}")
            continue
        print(_fmt(m))
        if m.get("root_cause"):
            print(f"    root_cause: {m['root_cause'][:140]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

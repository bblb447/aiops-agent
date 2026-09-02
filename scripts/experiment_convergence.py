"""V1.6 Investigation Convergence 收敛实验（A/B，真实 LLM，手工运行）。

用法（仓库根目录）：
    python scripts/experiment_convergence.py

只改 Prompt，不改状态机/不做强制注入/不改工具集。
固定场景：CPU 高（一次查询即可判断）——query_metric 返回明确异常 + runbook 有对应处置。
两个版本：
    Baseline        = 当前 prompts/diagnose.txt（V1.5）
    Convergence     = + 显式调查预算(≤4 次只读) + 收敛判据(≥2 条独立证据且 ≥2 来源即收尾)

验收优先级：预算内收敛 > RCA 合法 > tool/final 路径。
"""
import json
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
from app.tools.monitoring import MonitoringTool  # noqa: E402

from smolagents.models import MessageRole  # noqa: E402

CONVERGENCE_PROMPT = (
    "你是 AIOps 诊断 Agent。请调查以下故障并给出带证据的根因结论。\n"
    "故障: {title}，服务: {service}，级别: {severity}。\n"
    "告警上下文: {context}\n"
    "可用工具: {tool_names}\n"
    "调查预算: 你最多只能调用 4 次只读工具（query_metric/query_metric_range/search_runbook 等，"
    "不含 submit_rca_result 与 final_answer）。\n"
    "收敛判据: 一旦已有至少 2 条独立证据、且来自至少 2 个不同来源，就必须停止继续调查并立即收尾提交 RCA；"
    "不要为了找更多证据而查满预算。\n"
    "收尾二选一：① 调用 submit_rca_result 提交结构化 RCA；"
    "② 或调用 final_answer 时把严格 JSON 放进 <rca_result>...</rca_result> 标签。\n"
    "JSON 字段：root_cause 为字符串；confidence 为 0 到 1 之间的数字；evidence 为数组且至少 1 条，"
    "每条是含 source（字符串，数据源）与 fact（字符串，证据事实）的对象；"
    "hypotheses 与 recommendations 为字符串数组；summary 可选。"
)


def _prometheus_fixture(url, params=None, timeout=None):
    if "/api/v1/query" in str(url):
        query = (params or {}).get("query", "")
        value = "95.2" if "cpu" in str(query).lower() else "23.5"
        return httpx.Response(
            200, request=httpx.Request("GET", str(url)),
            json={"status": "success", "data": {"result": [
                {"metric": {"instance": "server-01"}, "value": [1710000000, value]}]}},
        )
    return httpx.Response(404, request=httpx.Request("GET", str(url)), json={})


class _LoggingModel:
    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self._inner.generate(messages, **kwargs)


def _content_str(content) -> str:
    if isinstance(content, str):
        return content
    try:
        return json.dumps(content, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        return str(content)


def _tool_executions(calls):
    """统计工具实际执行：最后一次 generate 的 messages 是累计历史，含每个工具响应一次。"""
    msgs = calls[-1] if calls else []
    responses = [m for m in msgs if getattr(m, "role", None) == MessageRole.TOOL_RESPONSE]
    reads = []
    submit_responses = 0
    for m in responses:
        txt = _content_str(getattr(m, "content", None))
        if "submit_rca_result" in txt:
            submit_responses += 1
        elif "search_runbook" in txt:
            reads.append("search_runbook")
        elif "query_metric_range" in txt:
            reads.append("query_metric_range")
        elif "query_metric" in txt:
            reads.append("query_metric")
    return submit_responses, reads


def run_one(tag: str, prompt_text: str) -> dict:
    from app.agent.agent import PROMPT_FILE
    from app.llm.provider import LiteLLMProvider
    import app.tools.knowledge as knowledge_mod

    _orig_prompt = PROMPT_FILE
    _orig_get = httpx.get
    _orig_runbook_dir = knowledge_mod.RUNBOOK_DIR
    _orig_make = LiteLLMProvider.make_agent_model

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        prompt_file = tmp / "prompt.txt"
        prompt_file.write_text(prompt_text, encoding="utf-8")
        runbook_dir = tmp / "runbooks"
        runbook_dir.mkdir()
        (runbook_dir / "cpu-high.md").write_text(
            "# CPU 高排查\n\nCPU 持续高通常与内存泄漏或发布有关，先查 Full GC 再查最近部署。",
            encoding="utf-8",
        )

        holder = {}
        def _wrapped(self):
            holder["model"] = _LoggingModel(_orig_make(self))
            return holder["model"]

        try:
            import app.agent.agent as agent_mod
            agent_mod.PROMPT_FILE = prompt_file
            knowledge_mod.RUNBOOK_DIR = runbook_dir
            httpx.get = _prometheus_fixture
            LiteLLMProvider.make_agent_model = _wrapped

            settings = Settings()
            settings.prometheus_url = "http://fixture-prom:9090"
            settings.rag_enabled = False
            settings.agent_max_steps = 8

            svc = IncidentService()
            inc = svc.create(
                "order-service CPU 持续高", "order-service", "critical",
                source="prometheus", alert_id="alert-001", target="server-01",
                observed_value=95.2, threshold=80,
            )
            investigate(settings, svc, inc.incident_id,
                        tools=[MonitoringTool(settings), KnowledgeTool(settings)])
            got = svc.get(inc.incident_id)
            submit_responses, reads = _tool_executions(holder["model"].calls)
            return {
                "tag": tag,
                "generate_calls": len(holder["model"].calls),
                "read_tool_calls": len(reads),
                "unique_tools": sorted(set(reads)),
                "submit_tool_called": submit_responses > 0,
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
    return ("  {tag:<16} generate={generate_calls:<2} read_calls={read_tool_calls:<2} "
            "tools={unique_tools} submit_called={submit_tool_called} rca_source={rca_source} "
            "rca={rca_valid} status={status} failure_code={failure_code}").format(**{
                **m,
                "submit_tool_called": "Y" if m["submit_tool_called"] else "n",
                "rca_valid": "Y" if m["rca_valid"] else "n",
                "rca_source": m["rca_source"] or "-",
            })


def main() -> int:
    settings = Settings()
    if not settings.llm_api_key:
        print("缺少 LLM API Key：请先配置 .env")
        return 2

    baseline_prompt = (ROOT / "prompts" / "diagnose.txt").read_text(encoding="utf-8")

    print("\n==== V1.6 Investigation Convergence 收敛实验（真实 LLM）====")
    print(f"model={settings.llm_model}  scenario=order-service CPU 高  budget=4  max_steps=8\n")
    results = []
    for tag, prompt in [("Baseline", baseline_prompt), ("Convergence", CONVERGENCE_PROMPT)]:
        print(f"--- 运行 {tag} ---")
        try:
            m = run_one(tag, prompt)
        except Exception as e:  # noqa: BLE001
            print(f"  {tag} 异常: {type(e).__name__}: {e}")
            results.append({"tag": tag, "error": str(e)})
            continue
        print(_fmt(m))
        if m.get("root_cause"):
            print(f"    root_cause: {m['root_cause'][:120]}")
        results.append(m)

    print("\n==== 汇总 ====")
    for r in results:
        print(_fmt(r) if "error" not in r else f"  {r['tag']}: ERROR {r['error'][:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

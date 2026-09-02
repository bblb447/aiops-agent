"""真实 LLM 冒烟测试：V1.5 结构化 RCA 验收（手工运行，不跑 CI、不提交密钥）。

用法（在仓库根目录）：
    python scripts/smoke_real_llm.py               # 打印验收报告（exit 0）
    python scripts/smoke_real_llm.py --expect      # 期望 ROOT_CAUSE_FOUND，否则 exit 1

验证 5 件事：
    1. Agent 是否选择只读工具（query_metric / search_runbook）
    2. 是否能读取 ToolResult（fixture 实测值 95.2 回到对话）
    3. 是否主动调用 submit_rca_result
    4. RCAResult 是否合法（root_cause / confidence / evidence / hypotheses）
    5. investigate 最终状态是否 ROOT_CAUSE_FOUND

数据源全部用 fixture，唯一真实外部依赖是 LLM（.env 的 llm_api_key / llm_base_url / llm_model）。
"""
import json
import os
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


def _prometheus_fixture(url, params=None, timeout=None):
    if "/api/v1/query" in str(url):
        query = (params or {}).get("query", "")
        # CPU 相关指标异常偏高，其余指标正常——给模型一个能收敛的清晰信号。
        value = "95.2" if "cpu" in str(query).lower() else "23.5"
        return httpx.Response(
            200,
            request=httpx.Request("GET", str(url)),
            json={
                "status": "success",
                "data": {"result": [
                    {"metric": {"instance": "server-01"}, "value": [1710000000, value]}
                ]},
            },
        )
    return httpx.Response(404, request=httpx.Request("GET", str(url)), json={})


class _LoggingModel:
    """包一层真实模型：记录每次 generate 的对话与输出，用于验收工具调用轨迹。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []
        self.outputs = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        out = self._inner.generate(messages, **kwargs)
        self.outputs.append(out)
        return out


def _dump(messages) -> str:
    parts = []
    for m in messages:
        c = getattr(m, "content", None)
        if isinstance(c, str):
            parts.append(c)
        else:
            try:
                parts.append(json.dumps(c, ensure_ascii=False, default=str))
            except Exception:  # noqa: BLE001 - 仅用于报告
                parts.append(str(c))
    return "\n".join(parts)


def main() -> int:
    expect_ok = "--expect" in sys.argv
    settings = Settings()  # 读仓库根目录 .env
    if not settings.llm_api_key:
        print("缺少 LLM API Key：请先配置 .env 的 llm_api_key / llm_base_url / llm_model")
        return 2

    settings.prometheus_url = "http://fixture-prom:9090"
    settings.rag_enabled = False
    settings.agent_max_steps = int(os.environ.get("SMOKE_MAX_STEPS", "12"))  # 限定步数，避免长时间挂起

    tmp = tempfile.TemporaryDirectory()
    rb_dir = Path(tmp.name)
    (rb_dir / "cpu-high.md").write_text(
        "# CPU 高排查\n\nCPU 持续走高通常与内存泄漏或流量突增有关，检查 Full GC 与最近发布。",
        encoding="utf-8",
    )

    import app.tools.knowledge as knowledge_mod
    _orig_runbook_dir = knowledge_mod.RUNBOOK_DIR
    knowledge_mod.RUNBOOK_DIR = rb_dir
    _orig_httpx_get = httpx.get
    httpx.get = _prometheus_fixture

    from app.llm.provider import LiteLLMProvider
    _orig_make_model = LiteLLMProvider.make_agent_model
    holder = {}
    def _wrapped_make_model(self):
        inner = _orig_make_model(self)
        log = _LoggingModel(inner)
        holder["model"] = log
        return log
    LiteLLMProvider.make_agent_model = _wrapped_make_model

    svc = IncidentService()
    inc = svc.create(
        "order-service CPU 持续高", "order-service", "critical",
        source="prometheus", alert_id="alert-001", target="server-01",
        observed_value=95.2, threshold=80,
    )
    tools = [MonitoringTool(settings), KnowledgeTool(settings)]

    status_code = 0
    try:
        investigate(settings, svc, inc.incident_id, tools=tools)
    except Exception as e:  # noqa: BLE001 - LLM/网络异常也要落进报告
        print(f"investigate 抛出异常: {type(e).__name__}: {e}")
        status_code = 1
    finally:
        LiteLLMProvider.make_agent_model = _orig_make_model
        httpx.get = _orig_httpx_get
        knowledge_mod.RUNBOOK_DIR = _orig_runbook_dir
        tmp.cleanup()

    got = svc.get(inc.incident_id)
    transcript = _dump(holder["model"].calls[-1]) if holder.get("model") and holder["model"].calls else ""
    submitted = got.rca is not None

    print("\n==== AIOps Agent V1.5 真实 LLM 冒烟验收 ====")
    print(f"model          : {settings.llm_model}")
    print(f"scenario       : order-service CPU 高 (observed={inc.observed_value} threshold={inc.threshold} target={inc.target})")
    print()
    print("[1] Agent 工具选择")
    print(f"    query_metric   调用: {'yes' if 'query_metric' in transcript else 'no'}")
    print(f"    search_runbook 调用: {'yes' if 'search_runbook' in transcript else 'no'}")
    print("[2] ToolResult 读取")
    print(f"    对话中出现实测值 95.2: {'yes' if '95.2' in transcript else 'no'}")
    print("[3] submit_rca_result")
    print(f"    submit_attempted   : {submitted}")
    print(f"    rca_result 存在     : {'yes' if submitted else 'no'}")
    print("[4] RCAResult 合法性")
    if submitted:
        r = got.rca
        print(f"    root_cause : {r.root_cause}")
        print(f"    confidence : {r.confidence}")
        print(f"    evidence   : {len(r.evidence)} 条 -> " +
              "; ".join(f"[{e.source}] {e.fact}" for e in r.evidence))
        print(f"    hypotheses : {r.hypotheses}")
    else:
        print("    （无有效 RCA 提交）")
    print("[5] 最终状态")
    print(f"    status      : {got.status.value}")
    print(f"    failure_code: {got.failure_code}")

    ok = submitted and got.status.value == "ROOT_CAUSE_FOUND"
    if not ok and holder.get("model") and holder["model"].outputs:
        last = holder["model"].outputs[-1]
        txt = last.content if isinstance(last.content, str) else json.dumps(last.content, ensure_ascii=False, default=str)
        print("\n[debug] 模型最后一次输出（截断）:")
        print("    " + txt[:800].replace("\n", "\n    "))
    print("\n==== 结论: " + ("PASS" if ok else "FAIL") + " (期望 ROOT_CAUSE_FOUND) ====")
    if expect_ok and not ok:
        status_code = status_code or 1
    return status_code


if __name__ == "__main__":
    raise SystemExit(main())

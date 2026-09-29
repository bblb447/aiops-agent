"""F4：预算接线与包装链结构不变式（spec §12.2）。

一次逻辑只读调用 → 恰好一次 consume()；所有只读适配器共享同一个 budget；
submit_rca_result 经 _ToolAdapter 暴露但不带预算 —— 不消耗预算，且预算耗尽后仍可提交。
直接断言计数与底层调用次数，不靠返回值间接推断。
"""
import json

from app.agent.agent import _compose_investigation_tools, adapt_tools
from app.agent.budget import ReadBudget
from app.agent.submit_tool import SubmitRCATool
from app.incident.service import IncidentService
from app.tools.base import ToolResult
from app.tools.monitoring import MonitoringTool


class _StubMonitoring(MonitoringTool):
    """不发网络请求的只读工具桩，只统计底层被调用的次数。"""

    def __init__(self):
        self.calls = 0

    def query_metric(self, metric: str, target: str = "") -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, tool="query_metric", data={"metric": metric})


class _StubLogging:
    """第二个只读工具桩，用于证明预算**跨工具**共享（方法名不冲突）。"""

    source_type = None
    exposed_methods = ["search_logs"]

    def __init__(self):
        self.calls = 0

    def search_logs(self, query: str, limit: int = 50,
                    start: int | None = None, end: int | None = None) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, tool="search_logs", data={})


def _submit_tool():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    return SubmitRCATool(svc, inc.incident_id)


def test_one_logical_read_call_consumes_exactly_once():
    budget = ReadBudget(4)
    monitoring = _StubMonitoring()
    by_name = {t.name: t for t in
               _compose_investigation_tools([monitoring], _submit_tool(), budget)}
    by_name["query_metric"].forward(metric="cpu")
    assert budget.executed == 1
    assert monitoring.calls == 1


def test_read_adapters_share_one_budget_across_tools():
    # 跨工具共享同一份预算：第 3 次调用（换回 monitoring）被拒，
    # 说明预算不是"每个工具一份"（spec §12.2 显式排除"预算被重复消耗"）。
    budget = ReadBudget(2)
    monitoring, logging = _StubMonitoring(), _StubLogging()
    by_name = {t.name: t for t in
               _compose_investigation_tools([monitoring, logging], _submit_tool(), budget)}
    assert json.loads(by_name["query_metric"].forward(metric="cpu"))["success"] is True
    assert json.loads(by_name["search_logs"].forward(query="error"))["success"] is True
    assert json.loads(by_name["query_metric"].forward(metric="cpu"))["success"] is False
    assert budget.executed == 2
    assert monitoring.calls == 1 and logging.calls == 1


def test_build_agent_inner_adapt_tools_is_identity_and_preserves_budget():
    # build_agent 内部对已适配对象会再调一次 adapt_tools；该次必须是恒等操作，
    # 否则会出现第二个不受预算约束的包装（spec §4.3 / §12.2）。
    budget = ReadBudget(1)
    composed = _compose_investigation_tools([_StubMonitoring()], _submit_tool(), budget)
    again = adapt_tools(composed)
    assert len(again) == len(composed)
    assert all(a is b for a, b in zip(again, composed))
    query_metric = next(a for a in again if a.name == "query_metric")
    assert json.loads(query_metric.forward(metric="cpu"))["success"] is True
    assert json.loads(query_metric.forward(metric="cpu"))["success"] is False
    assert budget.executed == 1


def test_submit_is_exposed_but_not_budgeted_and_survives_exhaustion():
    # spec §2.1/§2.2/§7.5：submit 必须被 _ToolAdapter 包装（否则 agent 调不到），
    # 但不带预算 —— 故不消耗预算，且预算耗尽后仍可成功提交。
    budget = ReadBudget(1)
    by_name = {t.name: t for t in
               _compose_investigation_tools([_StubMonitoring()], _submit_tool(), budget)}
    assert "submit_rca_result" in by_name

    # 先耗尽预算
    assert json.loads(by_name["query_metric"].forward(metric="cpu"))["success"] is True
    assert json.loads(by_name["query_metric"].forward(metric="cpu"))["success"] is False
    assert budget.executed == 1

    # 预算耗尽后，submit 仍能成功提交，且不消耗预算
    payload = json.loads(by_name["submit_rca_result"].forward(
        root_cause="deployment_regression", confidence=0.9,
        evidence=[{"source": "prometheus", "fact": "CPU 从 42% 涨到 95%"}],
    ))
    assert payload["success"] is True
    assert budget.executed == 1          # ← 经 adapter 调用，故这行有判别力

"""F4：_ToolAdapter 的预算拒绝（spec §4.2）。"""
import json

from app.agent.agent import _ToolAdapter
from app.agent.budget import ReadBudget
from app.tools.base import ToolResult


class _Stub:
    source_type = None

    def __init__(self):
        self.calls = 0

    def query(self) -> ToolResult:
        self.calls += 1
        return ToolResult(success=True, tool="query", data={"n": self.calls})


def _adapter(limit):
    stub = _Stub()
    return stub, _ToolAdapter(stub, stub.query, budget=ReadBudget(limit))


def test_over_budget_call_does_not_invoke_underlying_method():
    stub, adapter = _adapter(1)
    assert json.loads(adapter.forward())["success"] is True
    second = json.loads(adapter.forward())
    # 关键：底层方法只被执行过一次 —— 拒绝发生在调用底层之前（spec §4.2）。
    assert stub.calls == 1
    assert second["success"] is False
    assert second["tool"] == "query"
    assert "预算" in second["error"]


def test_rejection_envelope_has_same_keys_as_toolresult_failure():
    # spec §4.2：拒绝信封与既有 ToolResult(success=False) 同构，模型零学习成本。
    _, adapter = _adapter(0)
    payload = json.loads(adapter.forward())
    assert set(payload) == set(ToolResult(success=False, tool="x", error="e").to_dict())


def test_no_budget_means_no_enforcement():
    # spec §6：不传 budget 的调用点行为与 F4 之前完全一致。
    stub = _Stub()
    adapter = _ToolAdapter(stub, stub.query)
    for _ in range(5):
        assert json.loads(adapter.forward())["success"] is True
    assert stub.calls == 5

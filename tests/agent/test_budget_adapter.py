"""F4：_ToolAdapter 的预算拒绝（spec §4.2）。"""
import json

import pytest

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


class _FailingStub:
    """底层调用必然失败的只读工具桩。"""

    source_type = None

    def __init__(self):
        self.calls = 0

    def query(self) -> ToolResult:
        self.calls += 1
        return ToolResult(success=False, tool="query", error="底层失败")


def test_failed_underlying_call_still_consumes_budget():
    # spec §2.2 / design.md §48.4：放行即计数 —— 底层返回失败的 ToolResult 时，
    # 该次调用同样占掉一格预算（不因结果失败而回退）。
    # 注意：本用例只验证「失败仍计数」与「耗尽后底层不再被调用」，
    # 不覆盖「计数先于底层执行」的时序 —— 那由 test_counting_precedes_underlying_execution 负责。
    budget = ReadBudget(2)
    stub = _FailingStub()
    adapter = _ToolAdapter(stub, stub.query, budget=budget)

    for _ in range(2):
        payload = json.loads(adapter.forward())
        assert payload["success"] is False        # 底层确实失败了
    assert stub.calls == 2
    assert budget.executed == 2                   # 但两格预算都已被消耗

    # 预算耗尽后，底层连一次都不会再被调用（拒绝先于底层调用）。
    rejected = json.loads(adapter.forward())
    assert stub.calls == 2
    assert rejected["success"] is False
    assert "预算" in rejected["error"]


class _RaisingStub:
    """底层调用必然抛异常的只读工具桩。"""

    source_type = None

    def __init__(self):
        self.calls = 0

    def query(self):
        self.calls += 1
        raise RuntimeError("底层炸了")


def test_counting_precedes_underlying_execution():
    # design.md §48.4：计数发生在底层工具执行之前 —— 故底层即使**抛异常**
    # （而非返回失败 ToolResult），该次调用也已经占掉一格预算。
    # 区分力：若把 consume() 挪到底层调用之后，抛出的异常会先传出，
    # executed 将停在 0，本用例即转红。
    budget = ReadBudget(1)
    stub = _RaisingStub()
    adapter = _ToolAdapter(stub, stub.query, budget=budget)

    with pytest.raises(RuntimeError):
        adapter.forward()

    assert stub.calls == 1
    assert budget.executed == 1        # 已计一格，尽管底层抛了异常

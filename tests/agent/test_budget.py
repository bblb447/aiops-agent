"""F4：只读调用预算计数器（spec §4.1 / §12.1）。"""
import pytest

from app.agent.budget import ReadBudget


def test_consume_allows_exactly_limit_calls():
    b = ReadBudget(2)
    assert b.consume() is True
    assert b.consume() is True
    assert b.consume() is False
    assert b.executed == 2


def test_rejected_consume_leaves_executed_unchanged():
    # spec §2.2：被拒的调用不计数、不消耗预算。
    b = ReadBudget(1)
    assert b.consume() is True
    for _ in range(5):
        assert b.consume() is False
    assert b.executed == 1


def test_zero_limit_rejects_every_call():
    # spec §12.1：limit == 0 合法，表示一律拒绝。
    b = ReadBudget(0)
    assert b.consume() is False
    assert b.consume() is False
    assert b.executed == 0


def test_negative_limit_rejected_at_construction():
    # spec §12.1：负数在构造时拒绝，不得产生奇怪语义。
    with pytest.raises(ValueError):
        ReadBudget(-1)


def test_limit_is_readonly():
    b = ReadBudget(4)
    assert b.limit == 4
    with pytest.raises(AttributeError):
        b.limit = 5

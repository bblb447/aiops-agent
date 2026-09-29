"""F4 Hard Budget：单次 investigate 的只读调用预算（spec §4.1）。"""


class ReadBudget:
    """单次 investigate 的只读调用预算。

    - ``consume()`` 返回 True = 放行并计数；False = 拒绝且**不**计数。
    - 不变式：``0 <= executed <= limit``。
    - ``limit < 0`` 构造时拒绝；``limit == 0`` 合法，表示一律拒绝。
    """

    def __init__(self, limit: int) -> None:
        if limit < 0:
            raise ValueError(f"只读预算不得为负：{limit}")
        self._limit = limit
        self._executed = 0

    def consume(self) -> bool:
        if self._executed >= self._limit:
            return False
        self._executed += 1
        return True

    @property
    def executed(self) -> int:
        return self._executed

    @property
    def limit(self) -> int:
        return self._limit

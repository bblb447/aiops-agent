from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Workload(BaseModel):
    """服务负载汇总（1.3）。cpu/memory 语义以 Prometheus 返回为准，
    接真实数据源时按 limit/quota 归一为 0~1。"""
    service: str
    timestamp: str = Field(default_factory=_now)
    qps: float | None = None
    error_rate: float | None = None
    cpu: float | None = None
    memory: float | None = None

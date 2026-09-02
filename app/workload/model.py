from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Workload(BaseModel):
    """服务负载汇总（1.3）。字段语义（V1.3 锁 Prometheus 原始值）：
    qps=请求速率 req/s；error_rate=错误请求比例 0~1；cpu=CPU 使用核数；
    memory=内存使用量 bytes。某指标无匹配数据时该字段为 null（请求仍 200）。
    未来如需 0~1 利用率，另加 cpu_utilization/memory_utilization（usage/limit），不在本字段混用。
    """
    service: str
    timestamp: str = Field(default_factory=_now)
    qps: float | None = None
    error_rate: float | None = None
    cpu: float | None = None
    memory: float | None = None

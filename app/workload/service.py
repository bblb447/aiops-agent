"""WorkloadService：从 Prometheus 汇总服务负载（1.3，与 API/Agent 工具共用一条查询链）。"""
import httpx

from app.workload.model import Workload


class WorkloadUnavailable(Exception):
    """Prometheus 未配置。"""


class WorkloadQueryError(Exception):
    """Prometheus 查询失败。"""


def _qps_expr(service: str) -> str:
    return f'sum(rate(http_requests_total{{service="{service}"}}[5m]))'


def _error_rate_expr(service: str) -> str:
    return (
        f'sum(rate(http_requests_total{{service="{service}",status=~"5..|4.."}}[5m]))'
        f' / clamp_min(sum(rate(http_requests_total{{service="{service}"}}[5m])), 1)'
    )


def _cpu_expr(service: str) -> str:
    return f'sum(rate(container_cpu_usage_seconds_total{{service="{service}"}}[5m]))'


def _memory_expr(service: str) -> str:
    return f'avg(container_memory_usage_bytes{{service="{service}"}})'


class WorkloadService:
    def __init__(self, prometheus_url: str = "") -> None:
        self._url = prometheus_url

    def _fetch(self, expr: str) -> float | None:
        resp = httpx.get(f"{self._url}/api/v1/query", params={"query": expr}, timeout=10)
        resp.raise_for_status()
        result = resp.json().get("data", {}).get("result", [])
        if not result:
            return None
        try:
            return float(result[0]["value"][1])
        except (KeyError, TypeError, ValueError):
            return None

    def get_workload(self, service: str) -> Workload:
        if not self._url:
            raise WorkloadUnavailable("未配置 Prometheus 地址(prometheus_url)")
        try:
            return Workload(
                service=service,
                qps=self._fetch(_qps_expr(service)),
                error_rate=self._fetch(_error_rate_expr(service)),
                cpu=self._fetch(_cpu_expr(service)),
                memory=self._fetch(_memory_expr(service)),
            )
        except httpx.HTTPError as e:
            raise WorkloadQueryError(f"Prometheus 查询失败: {type(e).__name__}: {e}") from e

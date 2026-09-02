"""WorkloadService：从 Prometheus 汇总服务负载（1.3，与 API/Agent 工具共用一条查询链）。

语义（V1.3 锁定 Prometheus 原始值）：qps=req/s；error_rate=错误比例 0~1；
cpu=核数；memory=bytes。某指标无匹配数据 → 该字段 null（请求仍 200）；
HTTP/网络错误、响应非 JSON、Prometheus status=error → WorkloadQueryError。
"""
import httpx

from app.workload.model import Workload


class WorkloadUnavailable(Exception):
    """Prometheus 未配置。"""


class WorkloadQueryError(Exception):
    """Prometheus 查询失败（HTTP/JSON/Prometheus 业务错误）。"""


def _escape_service(service: str) -> str:
    """PromQL 字符串转义：\\ 与 " 需转义，防止 service 破坏查询表达式。"""
    return service.replace("\\", "\\\\").replace('"', '\\"')


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
        try:
            resp = httpx.get(f"{self._url}/api/v1/query", params={"query": expr}, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise WorkloadQueryError(f"Prometheus 请求失败: {type(e).__name__}: {e}") from e
        try:
            payload = resp.json()
        except ValueError as e:
            raise WorkloadQueryError(f"Prometheus 响应非 JSON: {e}") from e
        if payload.get("status") != "success":
            raise WorkloadQueryError(
                "Prometheus 查询返回错误: " + str(payload.get("error") or payload.get("errorType") or payload)
            )
        result = payload.get("data", {}).get("result") or []
        if not result:
            return None
        try:
            return float(result[0]["value"][1])
        except (KeyError, TypeError, ValueError):
            return None

    def get_workload(self, service: str) -> Workload:
        if not self._url:
            raise WorkloadUnavailable("未配置 Prometheus 地址(prometheus_url)")
        s = _escape_service(service)
        return Workload(
            service=service,
            qps=self._fetch(_qps_expr(s)),
            error_rate=self._fetch(_error_rate_expr(s)),
            cpu=self._fetch(_cpu_expr(s)),
            memory=self._fetch(_memory_expr(s)),
        )

import httpx
from app.config import Settings
from app.tools.base import ToolResult


class MonitoringTool:
    # 显式暴露白名单：只包装这些方法，避免 dir() 把 refresh_cache 等辅助方法暴露给 Agent。
    exposed_methods = ["query_metric", "query_metric_range"]

    def __init__(self, settings: Settings) -> None:
        self._url = settings.prometheus_url

    def _expr(self, metric: str, target: str) -> str:
        return f'{metric}{"{instance=~\"" + target + ".*\"}" if target else ""}'

    def query_metric(self, metric: str, target: str = "") -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="query_metric",
                              error="未配置 Prometheus 地址(prometheus_url)")
        expr = self._expr(metric, target)
        try:
            resp = httpx.get(f"{self._url}/api/v1/query", params={"query": expr}, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return ToolResult(success=False, tool="query_metric",
                              error=f"Prometheus 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="query_metric", data=resp.json())

    def query_metric_range(self, metric: str, target: str = "",
                           start: int | None = None, end: int | None = None,
                           step: str = "60s") -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="query_metric_range",
                              error="未配置 Prometheus 地址(prometheus_url)")
        params = {"query": self._expr(metric, target),
                  "start": start, "end": end, "step": step}
        try:
            resp = httpx.get(f"{self._url}/api/v1/query_range", params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return ToolResult(success=False, tool="query_metric_range",
                              error=f"Prometheus 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="query_metric_range", data=resp.json())

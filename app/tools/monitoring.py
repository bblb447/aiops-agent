import httpx
from app.config import Settings
from app.tools.base import ToolResult


class MonitoringTool:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.prometheus_url

    def query_metric(self, metric: str, target: str = "") -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="query_metric",
                              error="未配置 Prometheus 地址(prometheus_url)")
        expr = f'{metric}{"{instance=~\"" + target + ".*\"}" if target else ""}'
        try:
            resp = httpx.get(f"{self._url}/api/v1/query", params={"query": expr}, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return ToolResult(success=False, tool="query_metric",
                              error=f"Prometheus 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="query_metric", data=resp.json())

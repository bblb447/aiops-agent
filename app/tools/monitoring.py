import httpx
from app.config import Settings
from app.tools.base import ToolResult, ToolError

class MonitoringTool:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.prometheus_url

    def query_metric(self, metric: str, target: str = "", minutes: int = 30) -> ToolResult:
        if not self._url:
            raise ToolError("未配置 Prometheus 地址(prometheus_url)")
        expr = f'{metric}{"{instance=~\"" + target + ".*\"}" if target else ""}'
        resp = httpx.get(f"{self._url}/api/v1/query", params={"query": expr}, timeout=10)
        resp.raise_for_status()
        return ToolResult(success=True, tool="query_metric", data=resp.json())

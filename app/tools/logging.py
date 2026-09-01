import httpx
from app.config import Settings
from app.tools.base import ToolResult, ToolError

class LoggingTool:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.loki_url

    def search_logs(self, query: str, limit: int = 50) -> ToolResult:
        if not self._url:
            raise ToolError("未配置 Loki 地址(loki_url)")
        resp = httpx.get(f"{self._url}/loki/api/v1/query_range",
                         params={"query": query, "limit": limit}, timeout=10)
        resp.raise_for_status()
        return ToolResult(success=True, tool="search_logs", data=resp.json())

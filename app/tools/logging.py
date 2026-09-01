import time

import httpx
from app.config import Settings
from app.tools.base import ToolResult


class LoggingTool:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.loki_url

    def search_logs(self, query: str, limit: int = 50) -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="search_logs",
                              error="未配置 Loki 地址(loki_url)")
        # Loki query_range 必需 start/end（Unix 纳秒），默认查最近 30 分钟。
        now = time.time_ns()
        params = {
            "query": query,
            "limit": limit,
            "start": str(now - 30 * 60 * 10**9),
            "end": str(now),
        }
        try:
            resp = httpx.get(f"{self._url}/loki/api/v1/query_range", params=params, timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return ToolResult(success=False, tool="search_logs",
                              error=f"Loki 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="search_logs", data=resp.json())

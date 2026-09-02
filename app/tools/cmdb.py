from urllib.parse import quote

import httpx
from app.config import Settings
from app.tools.base import ToolResult


class CMDBTool:
    exposed_methods = ["get_service"]

    def __init__(self, settings: Settings) -> None:
        self._url = settings.cmdb_url

    def get_service(self, service: str) -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="get_service",
                              error="未配置 CMDB 地址(cmdb_url)")
        try:
            resp = httpx.get(f"{self._url}/services/{quote(service, safe='')}", timeout=10)
            resp.raise_for_status()
        except Exception as e:
            return ToolResult(success=False, tool="get_service",
                              error=f"CMDB 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="get_service", data=resp.json())

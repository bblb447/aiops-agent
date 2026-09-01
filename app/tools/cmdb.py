import httpx
from app.config import Settings
from app.tools.base import ToolResult, ToolError

class CMDBTool:
    def __init__(self, settings: Settings) -> None:
        self._url = settings.cmdb_url

    def get_service(self, service: str) -> ToolResult:
        if not self._url:
            raise ToolError("未配置 CMDB 地址(cmdb_url)")
        resp = httpx.get(f"{self._url}/services/{service}", timeout=10)
        resp.raise_for_status()
        return ToolResult(success=True, tool="get_service", data=resp.json())

from urllib.parse import quote

import httpx
from app.config import Settings
from app.incident.sources import EvidenceSource
from app.tools.base import ToolResult


class KubernetesTool:
    # F3：本工具的证据归属数据源（spec §2.6）。
    source_type = EvidenceSource.KUBERNETES
    exposed_methods = ["list_pods", "list_events"]

    def __init__(self, settings: Settings) -> None:
        self._api = settings.k8s_api_url
        self._token = settings.k8s_token
        self._ca = settings.k8s_ca_path

    def _get(self, path: str, params: dict, tool: str) -> ToolResult:
        if not self._api:
            return ToolResult(success=False, tool=tool,
                              error="未配置 Kubernetes 地址(k8s_api_url)")
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        try:
            resp = httpx.get(f"{self._api}{path}", params=params, headers=headers,
                             timeout=10, verify=(self._ca or True))
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            body = (e.response.text or "").strip()
            if len(body) > 500:
                body = body[:500] + "..."
            return ToolResult(success=False, tool=tool,
                              error=f"Kubernetes 返回错误（HTTP {e.response.status_code}）：{body}")
        except Exception as e:
            return ToolResult(success=False, tool=tool,
                              error=f"Kubernetes 查询失败: {type(e).__name__}: {e}")
        try:
            data = resp.json()
        except ValueError:
            # 200 + 非 JSON body：不把 JSONDecodeError 逸出 ToolResult boundary。
            body = (resp.text or "").strip()
            if len(body) > 500:
                body = body[:500] + "..."
            return ToolResult(success=False, tool=tool,
                              error=f"Kubernetes 返回了非 JSON 响应（HTTP {resp.status_code}）：{body}")
        return ToolResult(success=True, tool=tool, data=data)

    def list_pods(self, namespace: str, label_selector: str | None = None) -> ToolResult:
        params = {"labelSelector": label_selector} if label_selector else {}
        path = f"/api/v1/namespaces/{quote(namespace, safe='')}/pods"
        return self._get(path, params, "list_pods")

    def list_events(self, namespace: str, field_selector: str | None = None) -> ToolResult:
        params = {"fieldSelector": field_selector} if field_selector else {}
        path = f"/api/v1/namespaces/{quote(namespace, safe='')}/events"
        return self._get(path, params, "list_events")

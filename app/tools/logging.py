import time

import httpx
from app.config import Settings
from app.incident.sources import EvidenceSource
from app.tools.base import ToolResult

# spec §7 恒定段：与配置无关，恒呈现给模型；逐字采用，不得改写措辞。
_CONTRACT_BASE = (
    "查询 Loki 日志。query 必须是合法 LogQL：stream selector 必须用花括号包裹，"
    "形如 {<label-key>=\"<value>\"}；需要按内容过滤时可用 |= \"<text>\"。"
    "纯文本（如 error timeout）不是合法 LogQL。"
    "Loki 返回错误时会附带 HTTP 状态码与 Loki 的原始错误信息，据此修正 query 后可重试。"
)


def _build_extra_description(label_keys: list[str]) -> str:
    """把 LogQL / label 契约合成为工具自身的描述补充（spec §7）。

    恒定段恒呈现；配置段仅在部署声明了 label key 时附加。
    空配置时【不得】出现任何 deployment label 假设（尤其不得内置 app）。
    """
    if not label_keys:
        return _CONTRACT_BASE
    joined = " / ".join(label_keys)
    first = label_keys[0]
    return (
        f"{_CONTRACT_BASE}\n"
        f"本部署可用的 Loki stream label key：{joined}。"
        f"推荐 selector 形式：{{{first}=\"<value>\"}}。"
    )


class LoggingTool:
    # F3：本工具的证据归属数据源（spec §3.2）。
    source_type = EvidenceSource.LOKI
    exposed_methods = ["search_logs"]

    def __init__(self, settings: Settings) -> None:
        self._url = settings.loki_url
        self.extra_description = _build_extra_description(settings.loki_label_keys)

    def search_logs(self, query: str, limit: int = 50,
                    start: int | None = None, end: int | None = None) -> ToolResult:
        if not self._url:
            return ToolResult(success=False, tool="search_logs",
                              error="未配置 Loki 地址(loki_url)")
        # Loki query_range 必需 start/end（Unix 纳秒）；未显式指定时默认查最近 30 分钟。
        now = time.time_ns()
        if start is None:
            start = now - 30 * 60 * 10**9
        if end is None:
            end = now
        params = {
            "query": query,
            "limit": limit,
            "start": str(start),
            "end": str(end),
        }
        try:
            resp = httpx.get(f"{self._url}/loki/api/v1/query_range", params=params, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            # spec §8：透传 HTTP status + Loki 原始 body（只截断，不解析/不分类/不重试/不改写）
            body = (e.response.text or "").strip()
            if len(body) > 500:
                body = body[:500] + "..."
            return ToolResult(success=False, tool="search_logs",
                              error=f"Loki 返回错误（HTTP {e.response.status_code}）：{body}")
        except Exception as e:
            return ToolResult(success=False, tool="search_logs",
                              error=f"Loki 查询失败: {type(e).__name__}: {e}")
        return ToolResult(success=True, tool="search_logs", data=resp.json())

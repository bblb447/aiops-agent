from dataclasses import dataclass, field
from datetime import datetime, timezone

class ToolError(Exception):
    pass

@dataclass
class ToolResult:
    success: bool
    tool: str
    data: dict = field(default_factory=dict)
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {"success": self.success, "tool": self.tool,
                "timestamp": self.timestamp, "data": self.data, "error": self.error}

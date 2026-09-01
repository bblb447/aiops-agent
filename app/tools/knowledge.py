import os
from app.config import Settings
from app.tools.base import ToolResult, ToolError

RUNBOOK_DIR = "runbooks"

class KnowledgeTool:
    def __init__(self, settings: Settings) -> None:
        self._dir = RUNBOOK_DIR

    def search_runbook(self, keyword: str) -> ToolResult:
        if not os.path.isdir(self._dir):
            return ToolResult(success=True, tool="search_runbook",
                              data={"hits": [], "note": "runbooks 目录不存在"})
        hits = []
        for name in sorted(os.listdir(self._dir)):
            if not name.endswith(".md"):
                continue
            path = os.path.join(self._dir, name)
            with open(path, encoding="utf-8") as f:
                if keyword.lower() in f.read().lower():
                    hits.append(name)
        return ToolResult(success=True, tool="search_runbook", data={"hits": hits})

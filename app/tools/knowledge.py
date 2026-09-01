import os
from pathlib import Path

from app.config import Settings
from app.tools.base import ToolResult

# runbooks/ 位于项目根目录（本文件在 app/tools/ 下，向上三级）。
RUNBOOK_DIR = Path(__file__).resolve().parent.parent.parent / "runbooks"


class KnowledgeTool:
    def __init__(self, settings: Settings) -> None:
        # 兼容 str/Path（测试可能 monkeypatch 成 str）。
        self._dir = Path(RUNBOOK_DIR)

    def search_runbook(self, keyword: str) -> ToolResult:
        if not self._dir.is_dir():
            return ToolResult(success=True, tool="search_runbook",
                              data={"hits": [], "note": "runbooks 目录不存在"})
        hits = []
        for name in sorted(os.listdir(self._dir)):
            if not name.endswith(".md"):
                continue
            path = self._dir / name
            with open(path, encoding="utf-8") as f:
                if keyword.lower() in f.read().lower():
                    hits.append(name)
        return ToolResult(success=True, tool="search_runbook", data={"hits": hits})

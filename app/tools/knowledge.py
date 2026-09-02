import os
from pathlib import Path

from app.config import Settings
from app.knowledge.chunker import chunk_markdown
from app.knowledge.embeddings import FastEmbedTextEmbedding
from app.knowledge.retriever import RunbookRetriever
from app.tools.base import ToolResult

# runbooks/ 位于项目根目录（本文件在 app/tools/ 下，向上三级）。
RUNBOOK_DIR = Path(__file__).resolve().parent.parent.parent / "runbooks"
# chromadb 持久化目录（.data 已 gitignore）。
CHROMA_DIR = Path(__file__).resolve().parent.parent.parent / ".data" / "chroma"


class KnowledgeTool:
    exposed_methods = ["search_runbook"]

    def __init__(self, settings: Settings) -> None:
        # 兼容 str/Path（测试可能 monkeypatch 成 str）。
        self._dir = Path(RUNBOOK_DIR)
        self._rag_enabled = settings.rag_enabled
        self._top_k = settings.rag_top_k
        self._retriever = None  # 懒创建
        self._indexed = False

    def _get_retriever(self) -> RunbookRetriever:
        if self._retriever is None:
            self._retriever = RunbookRetriever(
                FastEmbedTextEmbedding(), persist_dir=str(CHROMA_DIR)
            )
        return self._retriever

    def search_runbook(self, keyword: str) -> ToolResult:
        if self._rag_enabled:
            try:
                return self._rag_search(keyword)
            except Exception:
                # RAG 依赖/模型/检索任一步失败，本次会话降级为关键词搜索，不重试。
                self._rag_enabled = False
        return self._keyword_search(keyword)

    def _all_chunks(self) -> list[dict]:
        chunks = []
        if not self._dir.is_dir():
            return chunks
        for name in sorted(os.listdir(self._dir)):
            if not name.endswith(".md"):
                continue
            path = self._dir / name
            with open(path, encoding="utf-8") as f:
                chunks.extend(chunk_markdown(f.read(), name))
        return chunks

    def _rag_search(self, keyword: str) -> ToolResult:
        retriever = self._get_retriever()
        if not self._indexed:
            retriever.index(self._all_chunks())
            self._indexed = True
        hits = retriever.search(keyword, k=self._top_k)
        return ToolResult(success=True, tool="search_runbook", data={"hits": hits})

    def _keyword_search(self, keyword: str) -> ToolResult:
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

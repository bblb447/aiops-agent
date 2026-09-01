from app.knowledge.embeddings import EmbeddingError


class RunbookRetriever:
    """chromadb 持久化向量检索：index(chunks) 入库，search(query, k) 返回 top-k。"""

    def __init__(self, embedder, persist_dir: str,
                 collection_name: str = "runbooks", client=None) -> None:
        self._embedder = embedder
        self._persist_dir = persist_dir
        self._collection_name = collection_name
        self._client = client  # 测试注入 EphemeralClient；生产为 None 走持久化
        self._collection = None

    def _ensure_collection(self):
        if self._collection is None:
            import chromadb
            client = self._client or chromadb.PersistentClient(path=str(self._persist_dir))
            self._collection = client.get_or_create_collection(
                self._collection_name, metadata={"hnsw:space": "cosine"}
            )
        return self._collection

    def index(self, chunks: list[dict]) -> None:
        if not chunks:
            return
        embeds = self._embedder.embed_texts([c["text"] for c in chunks])
        if embeds is None:
            raise EmbeddingError("文本嵌入失败")
        coll = self._ensure_collection()
        coll.upsert(
            ids=[c["id"] for c in chunks],
            embeddings=embeds,
            documents=[c["text"] for c in chunks],
            metadatas=[{"source": c["source"]} for c in chunks],
        )

    def search(self, query: str, k: int = 3) -> list[dict]:
        coll = self._ensure_collection()
        count = coll.count()
        if count == 0:
            return []
        embeds = self._embedder.embed_texts([query])
        if embeds is None:
            raise EmbeddingError("查询嵌入失败")
        res = coll.query(
            query_embeddings=embeds,
            n_results=min(k, count),
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
            hits.append({
                "source": meta.get("source", ""),
                "text": doc,
                "score": round(1 - dist, 4),
            })
        return hits

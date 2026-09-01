# fastembed 用 loguru 打日志，每次先试 HF 源（qdrant 仓库在 hf-mirror 不可达）
# 再回退 GCS 缓存，模型已本地缓存时那条 ERROR 属预期噪音，整体禁用 fastembed 日志。
try:
    from loguru import logger as _loguru
    _loguru.disable("fastembed")
except ImportError:
    pass


class EmbeddingError(Exception):
    pass


class FastEmbedTextEmbedding:
    """fastembed 封装：懒加载模型，embed_texts 失败返回 None 而非 raise。"""

    def __init__(self, model: str = "BAAI/bge-small-zh-v1.5") -> None:
        self._model = model
        self._embedder = None

    def _ensure(self):
        if self._embedder is None:
            from fastembed import TextEmbedding
            self._embedder = TextEmbedding(model_name=self._model)
        return self._embedder

    def embed_texts(self, texts: list[str]) -> list[list[float]] | None:
        try:
            # tolist() 把 numpy float32 转成 Python float，chromadb 不接受 numpy 类型。
            return [v.tolist() for v in self._ensure().embed(texts)]
        except Exception:
            return None

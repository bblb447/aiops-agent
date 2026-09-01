import numpy as np

from app.knowledge.embeddings import FastEmbedTextEmbedding


class FakeTextEmbedding:
    def embed(self, texts):
        # onnxruntime 输出 float32，np.float32 不是 Python float 子类。
        return [np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32) for _ in texts]


def test_embed_texts_returns_vectors(monkeypatch):
    emb = FastEmbedTextEmbedding()
    monkeypatch.setattr(emb, "_ensure", lambda: FakeTextEmbedding())
    out = emb.embed_texts(["你好"])
    assert out is not None
    assert isinstance(out[0], list)
    assert len(out[0]) == 4


def test_embed_texts_returns_python_floats(monkeypatch):
    # chromadb 拒绝 numpy float32，必须转成 Python 原生 float。
    emb = FastEmbedTextEmbedding()
    monkeypatch.setattr(emb, "_ensure", lambda: FakeTextEmbedding())
    out = emb.embed_texts(["你好"])
    assert out is not None
    assert all(isinstance(x, float) for x in out[0])


def test_embed_texts_failure_returns_none(monkeypatch):
    emb = FastEmbedTextEmbedding()

    def boom():
        raise RuntimeError("model download failed")

    monkeypatch.setattr(emb, "_ensure", boom)
    assert emb.embed_texts(["x"]) is None

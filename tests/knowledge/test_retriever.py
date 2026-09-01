import itertools

import chromadb
import pytest

from app.knowledge.embeddings import EmbeddingError
from app.knowledge.retriever import RunbookRetriever


class FakeEmbedder:
    def __init__(self, mapping, fail=False):
        self._mapping = mapping
        self.fail = fail

    def embed_texts(self, texts):
        if self.fail:
            return None
        return [self._mapping[t] for t in texts]


# EphemeralClient 在进程内共享底层存储，collection 名需唯一隔离测试。
_counter = itertools.count()


def _retriever(embedder):
    return RunbookRetriever(
        embedder, persist_dir=":memory:",
        collection_name=f"runbooks_{next(_counter)}",
        client=chromadb.EphemeralClient(),
    )


def test_search_returns_topk_ordered():
    emb = FakeEmbedder({"块A": [1.0, 0.0], "块B": [0.0, 1.0], "查询": [0.9, 0.1]})
    r = _retriever(emb)
    r.index([{"id": "a", "text": "块A", "source": "runbook.md"},
             {"id": "b", "text": "块B", "source": "runbook.md"}])
    hits = r.search("查询", k=2)
    assert [h["text"] for h in hits] == ["块A", "块B"]
    assert hits[0]["score"] > hits[1]["score"]
    assert hits[0]["source"] == "runbook.md"


def test_search_empty_collection_returns_empty():
    emb = FakeEmbedder({})
    r = _retriever(emb)
    assert r.search("查询") == []


def test_index_empty_chunks_noop():
    emb = FakeEmbedder({})
    r = _retriever(emb)
    r.index([])  # 不应抛错


def test_embed_failure_raises():
    emb = FakeEmbedder({"块A": [1.0, 0.0]})
    r = _retriever(emb)
    r.index([{"id": "a", "text": "块A", "source": "runbook.md"}])
    emb.fail = True
    with pytest.raises(EmbeddingError):
        r.search("查询")

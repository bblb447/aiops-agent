from app.knowledge.chunker import chunk_markdown


def test_empty_text_returns_empty():
    assert chunk_markdown("", "runbook.md") == []
    assert chunk_markdown("   \n\n", "runbook.md") == []


def test_splits_by_headings():
    md = "# 重启崩溃循环\n\n检查最近发布。\n\n# 内存泄漏\n\n分析 heap dump。"
    chunks = chunk_markdown(md, "runbook.md")
    assert len(chunks) == 2
    assert chunks[0]["text"].startswith("# 重启崩溃循环")
    assert chunks[1]["text"].startswith("# 内存泄漏")
    assert all(c["source"] == "runbook.md" for c in chunks)
    assert chunks[0]["id"] == "runbook.md::0"
    assert chunks[1]["id"] == "runbook.md::1"


def test_long_block_hard_cut():
    text = "x" * 1200
    chunks = chunk_markdown(text, "r.md", max_chars=500)
    assert len(chunks) == 3
    assert all(len(c["text"]) <= 500 for c in chunks)
    assert "".join(c["text"] for c in chunks) == text


def test_no_empty_chunks_from_blank_lines():
    md = "# 标题\n\n\n\n正文\n\n\n"
    chunks = chunk_markdown(md, "runbook.md")
    assert all(c["text"].strip() for c in chunks)

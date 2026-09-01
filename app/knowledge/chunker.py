def chunk_markdown(text: str, source: str, max_chars: int = 500) -> list[dict]:
    """把 markdown 按标题切块；超长块硬切到 max_chars。返回 [{"id","text","source"}]。"""
    if not text.strip():
        return []
    blocks = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("#") and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    chunks = []
    for block in blocks:
        if len(block) <= max_chars:
            chunks.append(block)
        else:
            for i in range(0, len(block), max_chars):
                chunks.append(block[i:i + max_chars])

    return [
        {"id": f"{source}::{i}", "text": c, "source": source}
        for i, c in enumerate(chunks)
        if c.strip()
    ]

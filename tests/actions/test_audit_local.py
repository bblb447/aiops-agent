import json

import pytest

from app.actions.audit import AuditEvent
from app.actions.audit_local import LocalAnchor, LocalFileAuditStore
from app.actions.audit_ports import AnchorHead


def _ev(seq, integ, prev="GENESIS", version=1):
    return AuditEvent(seq, "PROPOSED", None, None, None, {}, prev, version, None, None, integ)


def test_append_then_read_all(tmp_path):
    p = tmp_path / "records.jsonl"
    s = LocalFileAuditStore(str(p))
    s.append(_ev(0, "a"))
    s.append(_ev(1, "b", prev="a"))
    got = list(s.read_all())
    assert [e.seq for e in got] == [0, 1]
    assert s.last_seq() == 1


def test_malformed_line_fails_closed(tmp_path):
    p = tmp_path / "records.jsonl"
    p.write_text('{"seq": 0, "event_type": "PROPOSED"}\nnot json\n', encoding="utf-8")
    with pytest.raises(Exception):
        list(LocalFileAuditStore(str(p)).read_all())


def test_partial_final_line_fails_closed(tmp_path):
    s = LocalFileAuditStore(str(tmp_path / "records.jsonl"))
    s.append(_ev(0, "a"))
    with open(s._path, "a", encoding="utf-8") as f:
        f.write('{"seq": 1, "event_type": "PRO')      # 截断末行（无换行）
    with pytest.raises(Exception):
        list(LocalFileAuditStore(s._path).read_all())


def test_first_create_append_succeeds(tmp_path):
    LocalFileAuditStore(str(tmp_path / "r.jsonl")).append(_ev(0, "a"))   # 不抛


@pytest.mark.skipif(__import__("os").name == "nt", reason="Windows 不支持目录 fsync（POSIX-only）")
def test_first_create_fsyncs_parent_dir(tmp_path, monkeypatch):
    import os
    calls = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    LocalFileAuditStore(str(tmp_path / "r.jsonl")).append(_ev(0, "a"))
    assert len(calls) >= 2                            # 文件 fsync + 首建父目录 fsync


# ---------- Task 5：LocalAnchor（原子 + pending marker） ----------

def test_normal_commit_roundtrip(tmp_path):
    p = tmp_path / "head.json"
    a = LocalAnchor(str(p))
    assert a.read() is None
    a.commit(AnchorHead(0, "x", 1))
    a.commit(AnchorHead(1, "y", 2))
    assert LocalAnchor(str(p)).read() == AnchorHead(1, "y", 2)
    assert not (tmp_path / "head.json.pending").exists()        # pending 已撤


def test_commit_rejects_rollback(tmp_path):
    a = LocalAnchor(str(tmp_path / "head.json"))
    a.commit(AnchorHead(2, "z", 1))
    with pytest.raises(ValueError):
        a.commit(AnchorHead(1, "y", 1))


def test_commit_writes_exact_json(tmp_path):
    p = tmp_path / "head.json"
    LocalAnchor(str(p)).commit(AnchorHead(5, "abc", 3))
    assert json.loads(p.read_text(encoding="utf-8")) == {
        "seq": 5, "integrity": "abc", "key_version": 3}


def test_crash_before_replace_fails_closed(tmp_path):
    a = LocalAnchor(str(tmp_path / "head.json"))
    (tmp_path / "head.json.pending").write_text(
        json.dumps({"seq": 1, "integrity": "x", "key_version": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        a.read()


def test_crash_after_replace_before_finalize_fails_closed(tmp_path):
    a = LocalAnchor(str(tmp_path / "head.json"))
    a.commit(AnchorHead(1, "x", 1))
    (tmp_path / "head.json.pending").write_text(             # head 已新 + pending 残留
        json.dumps({"seq": 2, "integrity": "y", "key_version": 1}), encoding="utf-8")
    with pytest.raises(ValueError):
        a.read()

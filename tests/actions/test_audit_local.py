import json

import pytest

from app.actions.audit import AuditEvent
from app.actions.audit_local import LocalFileAuditStore


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

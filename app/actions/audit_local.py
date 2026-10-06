import json
import os
from dataclasses import asdict

from app.actions.audit import AuditEvent
from app.auth.model import AuthMethod


def _event_to_json(e: AuditEvent) -> str:
    d = asdict(e)
    d["auth_method"] = e.auth_method.value if e.auth_method is not None else None
    return json.dumps(d, sort_keys=True, ensure_ascii=False)


def _json_to_event(d: dict) -> AuditEvent:
    am = d.get("auth_method")
    return AuditEvent(d["seq"], d["event_type"], d["incident_id"], d["action_id"],
                      d["proposal_fingerprint"], d["detail"], d["prev_integrity"],
                      d["key_version"], d["principal_id"],
                      AuthMethod(am) if am is not None else None, d["integrity"])


def _fsync_dir(d: str) -> None:
    """POSIX 目录 fsync（令目录 entry durable）。Windows 不支持对目录 fsync → no-op。"""
    if os.name == "nt":
        return
    dfd = os.open(d, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


class LocalFileAuditStore:
    """append-only JSONL；append 后 fsync（首次创建另 fsync 父目录）。
    损坏 / 末行不完整 → read_all fail-closed。无 update/delete/truncate。"""
    def __init__(self, path: str) -> None:
        self._path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    def append(self, event: AuditEvent) -> None:
        existed = os.path.exists(self._path)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(_event_to_json(event) + "\n")
            f.flush()
            os.fsync(f.fileno())
        if not existed:                            # 首次创建文件 → 父目录 entry 也须 durable
            _fsync_dir(os.path.dirname(os.path.abspath(self._path)))

    def read_all(self):
        if not os.path.exists(self._path):
            return ()
        out = []
        with open(self._path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f):
                if not line.endswith("\n"):
                    raise ValueError(f"fail-closed：末行不完整（line {lineno}）")
                try:
                    out.append(_json_to_event(json.loads(line)))
                except Exception as e:             # noqa: BLE001 - 损坏即 fail-closed
                    raise ValueError(f"fail-closed：记录损坏（line {lineno}）: {e}")
        return tuple(out)

    def last_seq(self) -> int:
        ev = self.read_all()
        return ev[-1].seq if ev else -1

import base64
import json
import os
import tempfile
from dataclasses import asdict

from app.actions.audit import AuditEvent
from app.actions.audit_ports import AnchorHead
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


def validate_audit_paths(records: str, anchor: str, key: str) -> None:
    """启动隔离校验（fail-closed）：anchor/key 不得落在 records 目录内，且 anchor ≠ key。

    注意：路径分离 ≠ 完整 OS trust-domain separation（同机同 account 仍可能同时改三者）；
    真正强锚定（external WORM/KMS/HSM）留 additive。此校验只防「明显误配」。
    """
    rec_dir = os.path.dirname(os.path.abspath(records))
    anc = os.path.abspath(anchor)
    kp = os.path.abspath(key)
    if os.path.dirname(anc) == rec_dir:
        raise ValueError("audit anchor path 不得位于 records 目录内")
    if os.path.dirname(kp) == rec_dir:
        raise ValueError("audit key path 不得位于 records 目录内")
    if anc == kp:
        raise ValueError("audit anchor 与 key 不得使用同一路径")


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


class LocalAnchor:
    """head 提交：pending marker 保证「不确定提交 → 恢复 fail-closed」。

    顺序：写 pending（durable）→ replace head（durable）→ 删 pending（durable）→ success。
    `read()` 若见 pending → fail-closed（上一轮 commit 处于不确定态：可能 replace 前/后崩溃）。
    """
    def __init__(self, path: str) -> None:
        self._path = path
        self._pending = path + ".pending"
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    @staticmethod
    def _durable_write(path: str, obj: dict) -> None:
        d = os.path.dirname(os.path.abspath(path))
        fd, tmp = tempfile.mkstemp(dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(obj, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)                     # 原子
            _fsync_dir(d)
        finally:
            if os.path.exists(tmp):                   # 异常路径不留 *.tmp
                os.remove(tmp)

    def read(self) -> AnchorHead | None:
        if os.path.exists(self._pending):             # 不确定提交 → fail-closed
            raise ValueError("fail-closed：存在未完成的 anchor 提交（pending marker）")
        if not os.path.exists(self._path):
            return None
        with open(self._path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return AnchorHead(d["seq"], d["integrity"], d["key_version"])

    def commit(self, head: AnchorHead) -> None:
        cur = self.read()                             # pending 存在 → 抛（fail-closed）
        if cur is not None and head.seq < cur.seq:
            raise ValueError("anchor head 回退被拒")
        d = {"seq": head.seq, "integrity": head.integrity, "key_version": head.key_version}
        self._durable_write(self._pending, d)         # 1) pending 先 durable
        self._durable_write(self._path, d)            # 2) head replace durable
        os.remove(self._pending)                      # 3) 撤 pending
        _fsync_dir(os.path.dirname(os.path.abspath(self._path)))


class LocalKeyProvider:
    """version→key 映射落盘（落点须在 audit 数据目录之外，见路径校验）。
    构造不写盘；首次 `current()` 才 bootstrap 初始 key 并 durable；rotate durable-before-use。
    旧 key 不隐式退休 / 删除（DA6）。"""
    def __init__(self, path: str) -> None:
        self._path = path
        self._data = self._load()                     # 不 mkdir、不写盘

    def _load(self) -> dict:
        if not os.path.exists(self._path):
            return {"current": 0, "keys": {}}         # 尚未 bootstrap
        with open(self._path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _durable_write(self, d: dict) -> None:
        ddir = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(ddir, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=ddir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(d, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)               # 原子
            _fsync_dir(ddir)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def current(self) -> tuple[int, bytes]:
        if self._data["current"] == 0:                # 首次真正使用 → bootstrap
            self._data["keys"]["1"] = base64.b64encode(os.urandom(32)).decode()
            self._data["current"] = 1
            self._durable_write(self._data)           # durable 后才返回
        v = self._data["current"]
        return v, base64.b64decode(self._data["keys"][str(v)])

    def get(self, version: int) -> bytes | None:
        b = self._data["keys"].get(str(version))
        return base64.b64decode(b) if b is not None else None

    def rotate(self) -> int:
        new = self._data["current"] + 1
        self._data["keys"][str(new)] = base64.b64encode(os.urandom(32)).decode()
        self._data["current"] = new
        self._durable_write(self._data)               # 先 durable
        return new                                    # 返回后才允许 current() 取新 version

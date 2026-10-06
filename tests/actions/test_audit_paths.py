import pytest

from app.actions.audit_local import validate_audit_paths
from app.config import Settings


def test_defaults_are_separate_dirs():
    s = Settings(_env_file=None)
    validate_audit_paths(s.audit_records_path, s.audit_anchor_path, s.audit_key_path)  # 不抛


@pytest.mark.parametrize("rec,anc,key", [
    ("/d/audit/records.jsonl", "/d/audit/head.json", "/d/audit-key/keys.json"),      # anchor ∈ records 目录
    ("/d/audit/records.jsonl", "/d/audit-anchor/head.json", "/d/audit/keys.json"),   # key ∈ records 目录
    ("/d/audit/records.jsonl", "/d/x/head.json", "/d/x/head.json"),                  # anchor == key
])
def test_violations_rejected(rec, anc, key):
    with pytest.raises(ValueError):
        validate_audit_paths(rec, anc, key)


def test_anchor_in_records_subdir_is_rejected(tmp_path):
    rec = str(tmp_path / "audit" / "records.jsonl")
    anc = str(tmp_path / "audit" / "sub" / "head.json")           # records 目录的子目录内
    with pytest.raises(ValueError):
        validate_audit_paths(rec, anc, str(tmp_path / "k" / "keys.json"))

def test_default_flow_uses_durable_audit(tmp_path, monkeypatch):
    from app import main
    from app.actions.audit_local import LocalAnchor, LocalFileAuditStore, LocalKeyProvider

    monkeypatch.setattr(main, "_settings", main.Settings(
        _env_file=None,
        audit_records_path=str(tmp_path / "rec" / "r.jsonl"),
        audit_anchor_path=str(tmp_path / "anc" / "head.json"),
        audit_key_path=str(tmp_path / "key" / "keys.json")))
    monkeypatch.setattr(main, "_flow", None)

    audit = main.get_action_flow()._audit
    assert isinstance(audit._store, LocalFileAuditStore)
    assert isinstance(audit._anchor, LocalAnchor)
    assert isinstance(audit._kp, LocalKeyProvider)

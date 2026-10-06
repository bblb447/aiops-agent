def test_default_flow_uses_cmdb_inventory_resolver():
    from app import main
    from app.actions.inventory import CMDBInventoryResolver
    assert not hasattr(main, "_NullResolver")                       # 已被替换
    flow = main.get_action_flow()
    assert isinstance(flow._gateway._resolver, CMDBInventoryResolver)


def test_wired_resolver_fails_closed_without_cmdb_url(monkeypatch):
    # 行为级：默认无 cmdb_url 时，装配出的 resolver 对任何 target 返回 None（→ Gateway 必 REJECT）
    from app import main
    from app.actions.inventory import CMDBInventoryResolver
    monkeypatch.setattr(main, "_settings", main.Settings(cmdb_url="", _env_file=None))
    monkeypatch.setattr(main, "_flow", None)
    resolver = main.get_action_flow()._gateway._resolver
    assert isinstance(resolver, CMDBInventoryResolver)
    assert resolver.resolve("anything") is None

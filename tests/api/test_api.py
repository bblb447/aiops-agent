from fastapi.testclient import TestClient

from app.config import Settings
from app.incident.service import IncidentService
from app.main import create_app


def _fake_investigator(settings, svc, incident_id, tools):
    inc = svc.get(incident_id)
    svc.add_timeline(incident_id, {"event": "结论: 版本回归"})
    inc.root_cause = "版本回归"
    inc.status = "ROOT_CAUSE_FOUND"
    svc.update(inc)
    return "版本回归"


def test_create_and_investigate():
    svc = IncidentService()
    app = create_app(Settings(llm_api_key="sk-test"), svc, _fake_investigator)
    c = TestClient(app)
    r = c.post("/api/v1/incidents", json={"title": "CPU 高", "service": "order-service", "severity": "critical"})
    assert r.status_code == 200
    inc = r.json()
    iid = inc["incident_id"]

    r2 = c.post(f"/api/v1/incidents/{iid}/investigate")
    assert r2.status_code == 200
    body = r2.json()
    assert body["conclusion"] == "版本回归"
    assert body["incident"]["status"] == "ROOT_CAUSE_FOUND"

    r3 = c.get(f"/api/v1/incidents/{iid}")
    assert r3.status_code == 200 and r3.json()["title"] == "CPU 高"

    r4 = c.get(f"/api/v1/incidents/{iid}/timeline")
    assert r4.status_code == 200 and len(r4.json()["timeline"]) >= 1


def test_investigate_second_time_conflict():
    # 二次调查：状态已非 NEW，必须返回 409 而非裸 500。
    svc = IncidentService()
    app = create_app(Settings(llm_api_key="sk-test"), svc, _fake_investigator)
    c = TestClient(app)
    r = c.post("/api/v1/incidents", json={"title": "CPU 高", "service": "order-service"})
    iid = r.json()["incident_id"]
    assert c.post(f"/api/v1/incidents/{iid}/investigate").status_code == 200
    r2 = c.post(f"/api/v1/incidents/{iid}/investigate")
    assert r2.status_code == 409
    body = r2.json()["detail"]
    assert "NEW" in body and "ROOT_CAUSE_FOUND" in body


def test_investigate_returns_structured_error_on_failure():
    # investigator 抛异常（含 InvalidTransitionError / LLM 异常）时，
    # 返回 502 且响应体携带结构化 incident，而不是通用 500。
    def failing_investigator(settings, svc_, incident_id, tools):
        raise RuntimeError("LLM 网络超时")

    svc = IncidentService()
    app = create_app(Settings(llm_api_key="sk-test"), svc, failing_investigator)
    c = TestClient(app)
    r = c.post("/api/v1/incidents", json={"title": "CPU 高", "service": "order-service"})
    iid = r.json()["incident_id"]
    r2 = c.post(f"/api/v1/incidents/{iid}/investigate")
    assert r2.status_code == 502
    body = r2.json()["detail"]
    assert body["incident"]["incident_id"] == iid
    assert "RuntimeError" in body["error"]
    assert "LLM 网络超时" in body["error"]


def test_investigate_receives_real_settings():
    # Ruling #4: 端点必须把真实 Settings 传给 investigator（而不是 None），
    # 否则真实 investigate 路径（读 settings.agent_max_steps 等）会 AttributeError。
    svc = IncidentService()
    seen = {}

    def settings_reader(settings, svc_, incident_id, tools):
        seen["settings"] = settings
        seen["llm_model"] = settings.llm_model
        return settings.llm_model

    app = create_app(
        Settings(llm_api_key="sk-test", llm_model="test-model"),
        svc,
        settings_reader,
    )
    c = TestClient(app)
    r = c.post("/api/v1/incidents", json={"title": "内存高", "service": "pay-service"})
    assert r.status_code == 200
    iid = r.json()["incident_id"]

    r2 = c.post(f"/api/v1/incidents/{iid}/investigate")
    assert r2.status_code == 200
    body = r2.json()
    assert body["conclusion"] == "test-model"
    assert seen["settings"] is not None
    assert seen["llm_model"] == "test-model"

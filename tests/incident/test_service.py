from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S

def test_create_and_get():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    assert inc.incident_id.startswith("INC-")
    assert inc.status == S.NEW
    assert svc.get(inc.incident_id).title == "CPU 高"

def test_add_timeline():
    svc = IncidentService()
    inc = svc.create("内存高", "billing-service", "major")
    svc.add_timeline(inc.incident_id, {"ts": "2026-09-01T10:00:00Z", "event": "收到告警"})
    assert len(svc.get(inc.incident_id).timeline) == 1

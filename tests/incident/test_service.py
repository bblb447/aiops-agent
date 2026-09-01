from concurrent.futures import ThreadPoolExecutor

from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S, IncidentSeverity

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
    ev = svc.get(inc.incident_id).timeline[0]
    assert len(svc.get(inc.incident_id).timeline) == 1
    assert ev["ts"] == "2026-09-01T10:00:00Z"

def test_add_timeline_auto_ts():
    svc = IncidentService()
    inc = svc.create("内存高", "billing-service")
    svc.add_timeline(inc.incident_id, {"event": "收到告警"})
    ev = svc.get(inc.incident_id).timeline[0]
    assert ev["event"] == "收到告警"
    assert "ts" in ev

def test_concurrent_create_unique_ids():
    svc = IncidentService()
    with ThreadPoolExecutor(max_workers=16) as ex:
        ids = list(ex.map(lambda _: svc.create("t", "s").incident_id, range(200)))
    assert len(ids) == len(set(ids)) == 200

def test_create_with_enum_severity():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", IncidentSeverity.CRITICAL)
    assert inc.severity == IncidentSeverity.CRITICAL

def test_default_severity_is_major():
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    assert inc.severity == IncidentSeverity.MAJOR

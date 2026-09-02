import threading
from datetime import datetime, timezone

from app.incident.model import Incident, IncidentSeverity, IncidentStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentService:
    def __init__(self) -> None:
        self._store: dict[str, Incident] = {}
        self._seq = 0
        self._lock = threading.Lock()

    def create(self, title: str, service: str,
               severity: IncidentSeverity = IncidentSeverity.MAJOR,
               *,
               alert_id: str | None = None,
               source: str | None = None,
               target: str | None = None,
               labels: dict | None = None,
               annotations: dict | None = None,
               observed_value: float | None = None,
               threshold: float | None = None,
               affected_assets: list[str] | None = None) -> Incident:
        with self._lock:
            self._seq += 1
            inc = Incident(
                incident_id=f"INC-{self._seq:05d}",
                title=title, service=service, severity=severity,
                status=IncidentStatus.NEW,
                alert_id=alert_id, source=source, target=target,
                labels=labels or {}, annotations=annotations or {},
                observed_value=observed_value, threshold=threshold,
                affected_assets=affected_assets or [],
            )
            self._store[inc.incident_id] = inc
        return inc

    def get(self, incident_id: str) -> Incident:
        return self._store[incident_id]

    def update(self, incident: Incident) -> None:
        with self._lock:
            self._store[incident.incident_id] = incident

    def add_timeline(self, incident_id: str, event: dict) -> None:
        with self._lock:
            inc = self.get(incident_id)
            event.setdefault("ts", _now())
            inc.timeline.append(event)

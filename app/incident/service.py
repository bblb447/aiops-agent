from app.incident.model import Incident, IncidentStatus

class IncidentService:
    def __init__(self) -> None:
        self._store: dict[str, Incident] = {}
        self._seq = 0

    def create(self, title: str, service: str, severity: str = "major") -> Incident:
        self._seq += 1
        inc = Incident(
            incident_id=f"INC-{self._seq:05d}",
            title=title, service=service, severity=severity,
            status=IncidentStatus.NEW,
        )
        self._store[inc.incident_id] = inc
        return inc

    def get(self, incident_id: str) -> Incident:
        return self._store[incident_id]

    def update(self, incident: Incident) -> None:
        self._store[incident.incident_id] = incident

    def add_timeline(self, incident_id: str, event: dict) -> None:
        inc = self.get(incident_id)
        inc.timeline.append(event)

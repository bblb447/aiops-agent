from datetime import datetime, timezone
from enum import Enum
from pydantic import BaseModel, Field

class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IncidentStatus(str, Enum):
    NEW = "NEW"
    TRIAGING = "TRIAGING"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REMEDIATION = "REMEDIATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    REOPEN = "REOPEN"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class Incident(BaseModel):
    incident_id: str
    title: str
    service: str
    severity: IncidentSeverity = IncidentSeverity.MAJOR
    status: IncidentStatus = IncidentStatus.NEW
    start_time: str = Field(default_factory=_now)
    affected_assets: list[str] = Field(default_factory=list)
    symptoms: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    remediation: list[str] = Field(default_factory=list)
    verification: str | None = None
    timeline: list[dict] = Field(default_factory=list)

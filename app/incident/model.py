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

class EvidenceItem(BaseModel):
    source: str
    fact: str

class RCAResult(BaseModel):
    root_cause: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(min_length=1)
    hypotheses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    summary: str | None = None

class Incident(BaseModel):
    incident_id: str
    title: str
    service: str
    severity: IncidentSeverity = IncidentSeverity.MAJOR
    status: IncidentStatus = IncidentStatus.NEW
    start_time: str = Field(default_factory=_now)
    affected_assets: list[str] = Field(default_factory=list)
    alert_id: str | None = None
    source: str | None = None
    target: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    observed_value: float | None = None
    threshold: float | None = None
    symptoms: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    rca: RCAResult | None = None
    failure_code: str | None = None
    remediation: list[str] = Field(default_factory=list)
    verification: str | None = None
    timeline: list[dict] = Field(default_factory=list)

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.incident.model import Incident
from app.incident.service import IncidentService

router = APIRouter(prefix="/api/v1/incidents")


class CreateIncidentRequest(BaseModel):
    title: str
    service: str
    severity: str = "major"


def _svc() -> IncidentService:
    from app.main import get_svc
    return get_svc()


@router.post("", response_model=Incident)
def create_incident(req: CreateIncidentRequest, svc: IncidentService = Depends(_svc)):
    return svc.create(req.title, req.service, req.severity)


@router.post("/{incident_id}/investigate")
def investigate_incident(incident_id: str, svc: IncidentService = Depends(_svc)):
    try:
        svc.get(incident_id)
    except KeyError:
        raise HTTPException(404, "incident not found")
    # Ruling #4: 必须把真实 Settings 传给 investigator（不是 None），
    # 否则真实 investigate 路径（读 settings.agent_max_steps 等）会 AttributeError。
    from app.main import current_settings, get_investigator
    conclusion = get_investigator()(current_settings(), svc, incident_id, tools=[])
    return {"conclusion": conclusion, "incident": svc.get(incident_id)}


@router.get("/{incident_id}", response_model=Incident)
def get_incident(incident_id: str, svc: IncidentService = Depends(_svc)):
    try:
        return svc.get(incident_id)
    except KeyError:
        raise HTTPException(404, "incident not found")


@router.get("/{incident_id}/timeline")
def get_timeline(incident_id: str, svc: IncidentService = Depends(_svc)):
    try:
        return {"timeline": svc.get(incident_id).timeline}
    except KeyError:
        raise HTTPException(404, "incident not found")

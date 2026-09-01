from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.incident.model import Incident, IncidentStatus
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
        inc = svc.get(incident_id)
    except KeyError:
        raise HTTPException(404, "incident not found")
    # 状态守卫：investigate 只接受 NEW 状态的 incident。二次调查（已是
    # ROOT_CAUSE_FOUND/ESCALATED 等）会触发状态机 NEW->TRIAGING 校验失败，
    # 与其裸 500，不如明确返回 409 让调用方感知"工单已调查过"。
    if inc.status != IncidentStatus.NEW:
        # status 可能是枚举或字符串（测试 fake 直接赋字符串），统一取展示值。
        current = inc.status.value if isinstance(inc.status, IncidentStatus) else inc.status
        raise HTTPException(409, f"incident 不在 NEW 状态, 当前 {current}")
    # Ruling #4: 必须把真实 Settings 传给 investigator（不是 None），
    # 否则真实 investigate 路径（读 settings.agent_max_steps 等）会 AttributeError。
    from app.main import current_settings, get_investigator
    try:
        conclusion = get_investigator()(current_settings(), svc, incident_id, tools=[])
    except Exception as e:
        # 失败时 agent 已把 incident 转 ESCALATED（见 investigate 的 except 分支）；
        # 结构化返回 incident + 错误摘要，调用方无需再解析通用 500。
        error = f"{type(e).__name__}: {e}"
        # detail 里的 incident 需先转 dict：HTTPException 的 detail 走 json.dumps，
        # pydantic 对象直接放进去会抛 "Object of type Incident is not JSON serializable"。
        raise HTTPException(502, detail={"incident": svc.get(incident_id).model_dump(), "error": error})
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

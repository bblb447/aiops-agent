from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.actions.flow import ActionFlow


class ProposeRequest(BaseModel):
    incident_id: str
    action_id: str
    target: str
    parameters: dict = Field(default_factory=dict)
    reason: str = ""


class ApprovalDecisionRequest(BaseModel):
    approved: bool


def _result(r) -> dict:
    return {
        "status": r.status,
        "approval_id": r.approval_id,
        "outcome": (r.execution.outcome.value if r.execution and r.execution.outcome else None),
        "admission": (r.execution.admission.value if r.execution else None),
        "reason": (r.execution.reason if r.execution else None),
    }


def create_actions_router(flow: ActionFlow) -> APIRouter:
    router = APIRouter(prefix="/api/v1/actions")

    @router.post("/propose")
    def propose(req: ProposeRequest, x_actor: str | None = Header(default=None)):
        # 注：X-Actor 是【未认证 seam】，不构成安全身份断言（未来接 authenticated principal）。
        payload = {"action_id": req.action_id, "target": req.target,
                   "parameters": req.parameters, "reason": req.reason}
        return _result(flow.propose(req.incident_id, payload, {"actor": x_actor or "anonymous"}))

    @router.post("/approvals/{approval_id}")
    def decide(approval_id: str, req: ApprovalDecisionRequest,
               x_actor: str | None = Header(default=None)):
        try:
            return _result(flow.decide_approval(approval_id, req.approved,
                                                {"actor": x_actor or "anonymous"}))
        except KeyError:
            raise HTTPException(404, "approval not found")

    @router.get("/approvals/{approval_id}")
    def status(approval_id: str):
        ap = flow.approval_status(approval_id)          # 只读，经 Flow，不直取内部 store
        if ap is None:
            raise HTTPException(404, "approval not found")
        return {"approval_id": ap.approval_id, "status": ap.status.value}

    return router

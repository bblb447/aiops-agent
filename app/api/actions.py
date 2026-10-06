from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.actions.flow import ActionFlow
from app.auth.authenticator import Authenticator
from app.auth.model import ActorContext, AuthenticatedPrincipal, RequestContext


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


def create_actions_router(flow: ActionFlow, authenticator: Authenticator) -> APIRouter:
    router = APIRouter(prefix="/api/v1/actions")

    def require_principal(request: Request) -> AuthenticatedPrincipal:
        try:
            principal = authenticator.authenticate(RequestContext(headers=dict(request.headers)))
        except Exception:                  # 认证器异常 / IdP 不可用 → fail-closed（非 500）
            raise HTTPException(status_code=401, detail="unauthenticated")
        if principal is None:
            raise HTTPException(status_code=401, detail="unauthenticated")
        return principal

    @router.post("/propose")
    def propose(req: ProposeRequest,
                principal: AuthenticatedPrincipal = Depends(require_principal)):
        actor = ActorContext.from_principal(principal)        # 唯一 request actor 构造点
        payload = {"action_id": req.action_id, "target": req.target,
                   "parameters": req.parameters, "reason": req.reason}
        return _result(flow.propose(req.incident_id, payload, actor))

    @router.post("/approvals/{approval_id}")
    def decide(approval_id: str, req: ApprovalDecisionRequest,
               principal: AuthenticatedPrincipal = Depends(require_principal)):
        actor = ActorContext.from_principal(principal)
        try:
            return _result(flow.decide_approval(approval_id, req.approved, actor))
        except KeyError:
            raise HTTPException(404, "approval not found")

    @router.get("/approvals/{approval_id}")
    def status(approval_id: str,
               principal: AuthenticatedPrincipal = Depends(require_principal)):
        # 认证必需；GET 状态语义不产生 actor（不写入 provenance）。
        ap = flow.approval_status(approval_id)
        if ap is None:
            raise HTTPException(404, "approval not found")
        return {"approval_id": ap.approval_id, "status": ap.status.value}

    return router

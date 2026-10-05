from fastapi import FastAPI

from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.model import ExecutionOutcome
from app.actions.registry import default_registry
from app.agent.agent import investigate
from app.api import actions as actions_api
from app.api import incidents, workload
from app.config import Settings, get_settings
from app.incident.service import IncidentService

# 惰性初始化：不在 import 时调用 get_settings()，避免预热其 lru_cache。
# 否则同一进程内 tests/test_config.py 的 monkeypatch 用例会读到缓存值而失败。
_settings: Settings | None = None
_svc: IncidentService | None = None
_investigator = investigate


def create_app(settings: Settings | None = None,
               svc: IncidentService | None = None,
               investigator=investigate) -> FastAPI:
    global _settings, _svc, _investigator
    if settings is not None:
        _settings = settings
    if svc is not None:
        _svc = svc
    _investigator = investigator
    app = FastAPI(title="AIOps Agent")
    app.include_router(incidents.router)
    app.include_router(workload.router)
    app.include_router(actions_api.create_actions_router(get_action_flow()))
    return app


class _NullResolver:
    """P3 未接 inventory：真实 target 一律解析失败（proposal REJECT）。真实解析留后续。"""
    def resolve(self, target):
        return None


class _UnwiredBackend:
    """P3 占位：不接真实 K8s 写（真实 backend 与 write credential 留后续）。

    默认运行时**不形成真实 mutation capability**；完整闭环由注入的测试 backend 覆盖。
    """
    def execute(self, action_id, target_descriptor, parameters):
        return ExecutionOutcome.NOOP


_flow = None


def get_action_flow():
    global _flow
    if _flow is None:
        store = ApprovalStore()
        _flow = ActionFlow(
            ActionGateway(default_registry(), _NullResolver(), get_svc().get),
            store, ActionExecutor(_UnwiredBackend(), default_registry(), store), AuditLog())
    return _flow


def current_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = get_settings()
    return _settings


def get_svc() -> IncidentService:
    global _svc
    if _svc is None:
        _svc = IncidentService()
    return _svc


def get_investigator():
    return _investigator


app = create_app()

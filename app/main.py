from fastapi import FastAPI

from app.actions.approval import ApprovalStore
from app.actions.audit import AuditLog
from app.actions.executor import ActionExecutor
from app.actions.flow import ActionFlow
from app.actions.gateway import ActionGateway
from app.actions.inventory import CMDBInventoryResolver
from app.actions.model import ExecutionOutcome
from app.actions.registry import default_registry
from app.auth.factory import build_authenticator, resolve_executor_principal_id
from app.auth.model import ActorContext, AuthMethod
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
    resolved = _settings if _settings is not None else Settings()
    app.include_router(actions_api.create_actions_router(
        get_action_flow(), build_authenticator(resolved)))
    return app


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
        # 不用 current_settings()/get_settings()：模块级 create_app() 在 import 时即调用本函数，
        # 会预热 get_settings 的 lru_cache，破坏 tests/test_config.py 的 monkeypatch 用例。
        settings = _settings if _settings is not None else Settings()
        store = ApprovalStore()
        service_principal = ActorContext(
            resolve_executor_principal_id(settings), AuthMethod.SERVICE)
        _flow = ActionFlow(
            ActionGateway(default_registry(), CMDBInventoryResolver(settings.cmdb_url), get_svc().get),
            store,
            ActionExecutor(_UnwiredBackend(), default_registry(), store,
                           service_principal=service_principal),
            AuditLog())
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

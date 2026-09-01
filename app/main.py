from fastapi import FastAPI

from app.agent.agent import investigate
from app.api import incidents
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
    return app


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

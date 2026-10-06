from app.auth.authenticator import (
    Authenticator, DenyAllAuthenticator, DevAuthenticator,
)
from app.config import Settings


def build_authenticator(settings: Settings) -> Authenticator:
    env = settings.app_env.strip().lower()
    mode = settings.authenticator.strip().lower()
    if env == "production":
        if mode == "dev":
            raise ValueError("production 禁止 dev authenticator（configuration error）")
        if mode == "oidc_jwt":
            raise NotImplementedError("oidc_jwt authenticator 未实现（deferred）")
        if mode in ("", "none"):
            return DenyAllAuthenticator()          # fail-closed
        raise ValueError(f"未知 authenticator: {mode!r}")
    if env == "development":                        # 显式开发环境才允许宽松
        if mode in ("", "dev"):
            return DevAuthenticator()
        if mode == "none":
            return DenyAllAuthenticator()
        raise ValueError(f"未知 authenticator: {mode!r}")
    # 未设 / 未知 / 拼错 → fail-closed（不得退化到 dev；2026-10-06 安全增强）
    return DenyAllAuthenticator()


_DEV_EXECUTOR_PRINCIPAL = "executor-service"   # 仅非 production 的 provenance 标签（非凭据）


def resolve_executor_principal_id(settings: Settings) -> str:
    """production 必须显式配置（无隐式身份）；dev/test 允许缺省 provenance 标签。"""
    pid = settings.executor_principal_id.strip()
    if pid:
        return pid
    if settings.app_env.strip().lower() == "production":
        raise ValueError("production 必须显式配置 executor_principal_id（configuration error）")
    return _DEV_EXECUTOR_PRINCIPAL

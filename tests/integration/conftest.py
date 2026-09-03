import os
import sys
from pathlib import Path

import pytest

# 本地后端直连：绕过系统代理（Windows 注册表代理会劫持 127.0.0.1 请求 → HTTP 502）。
os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), "127.0.0.1", "localhost"]))

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend  # noqa: E402

from app.config import Settings  # noqa: E402


@pytest.fixture(scope="session")
def l1_env():
    if not backend.PROM_EXE.exists() or not backend.LOKI_EXE.exists():
        pytest.skip("L1 需要二进制：先运行 tests/integration/scripts/setup_integration.ps1")
    try:
        backend.up_all()
    except BaseException:  # noqa: BLE001 - 起服务中途失败(SystemExit/异常)也须清理，防进程残留污染后续 session
        backend.down_all()
        raise
    try:
        yield {
            "prometheus": backend.PROM_URL,
            "loki": backend.LOKI_URL,
            "cmdb": backend.CMDB_URL,
            "exporter": backend.EXP_URL,
        }
    finally:
        backend.down_all()


@pytest.fixture(scope="session")
def settings_l1(l1_env):
    return Settings(prometheus_url=l1_env["prometheus"],
                    loki_url=l1_env["loki"],
                    cmdb_url=l1_env["cmdb"])

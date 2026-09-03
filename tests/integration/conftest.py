import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import backend  # noqa: E402

from app.config import Settings  # noqa: E402


@pytest.fixture(scope="session")
def l1_env():
    if not backend.PROM_EXE.exists() or not backend.LOKI_EXE.exists():
        pytest.skip("L1 需要二进制：先运行 tests/integration/scripts/setup_integration.ps1")
    backend.up_all()
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

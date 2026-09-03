"""L1 后端进程控制器。

CLI: python backend.py {up|down|status}
单宿主启动四进程：Prometheus/Loki（bin/ 原生 exe）+ metrics exporter + Mock CMDB（python）。
生命周期独立于 pytest；conftest.py 以 session fixture 包装 up_all()/down_all()。
"""
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
BIN_DIR = ROOT / "bin"
RUNTIME_DIR = ROOT / ".runtime"
PROM_EXE = BIN_DIR / "prometheus" / "prometheus.exe"
LOKI_EXE = BIN_DIR / "loki" / "loki-windows-amd64.exe"
PROM_YML = ROOT / "config" / "prometheus.yml"
LOKI_YML = ROOT / "config" / "loki-local-config.yaml"
EXPORTER_PY = ROOT / "fixtures" / "metrics_exporter.py"
MOCK_CMDB_PY = ROOT / "servers" / "mock_cmdb.py"

PROM_URL = "http://127.0.0.1:9090"
LOKI_URL = "http://127.0.0.1:3100"
EXP_URL = "http://127.0.0.1:8000"
CMDB_URL = "http://127.0.0.1:8081"

WARMUP_TIMEOUT = float(os.environ.get("AIOPS_INTEGRATION_WARMUP_SECONDS", "10"))

# 与 app/workload/service.py 契约同名：error_rate 命中 status=~"5..|4.."，分母 clamp_min
_QPS_EXPR = 'sum(rate(http_requests_total{service="order-service"}[5m]))'
_ERR_EXPR = ('sum(rate(http_requests_total{service="order-service",status=~"5..|4.."}[5m]))'
             ' / clamp_min(sum(rate(http_requests_total{service="order-service"}[5m])), 1)')
_CPU_EXPR = 'sum(rate(container_cpu_usage_seconds_total{service="order-service"}[5m]))'
_MEM_EXPR = 'avg(container_memory_usage_bytes{service="order-service"})'


def _run(cmd: list[str], name: str, cwd: Path) -> None:
    RUNTIME_DIR.mkdir(exist_ok=True)
    log = (RUNTIME_DIR / f"{name}.log").open("ab")
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (RUNTIME_DIR / f"{name}.pid").write_text(str(proc.pid))
    print(f"started {name} pid={proc.pid}")


def up() -> None:
    if not PROM_EXE.exists() or not LOKI_EXE.exists():
        sys.exit("二进制缺失：先运行 scripts/setup_integration.ps1 下载到 bin/")
    RUNTIME_DIR.mkdir(exist_ok=True)
    _run([str(PROM_EXE), f"--config.file={PROM_YML}",
          "--web.listen-address=127.0.0.1:9090",
          f"--storage.tsdb.path={RUNTIME_DIR / 'prom-data'}"],
         "prometheus", cwd=BIN_DIR / "prometheus")
    _run([str(LOKI_EXE), f"--config.file={LOKI_YML}"], "loki", cwd=RUNTIME_DIR)
    _run([sys.executable, str(EXPORTER_PY)], "exporter", cwd=ROOT)
    _run([sys.executable, str(MOCK_CMDB_PY)], "cmdb", cwd=ROOT)


def _poll(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    sys.exit(f"服务未就绪: {url}")


def _prom_value(expr: str) -> float | None:
    r = httpx.get(f"{PROM_URL}/api/v1/query", params={"query": expr}, timeout=5)
    r.raise_for_status()
    body = r.json()
    if body.get("status") != "success":
        return None
    res = body.get("data", {}).get("result") or []
    if not res:
        return None
    try:
        return float(res[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _ready() -> None:
    _poll(f"{PROM_URL}/-/ready")
    _poll(f"{LOKI_URL}/ready")
    _poll(f"{EXP_URL}/metrics")
    _poll(f"{CMDB_URL}/health")


def warmup_workload() -> None:
    deadline = time.time() + WARMUP_TIMEOUT
    while time.time() < deadline:
        vals = [_prom_value(e) for e in (_QPS_EXPR, _ERR_EXPR, _CPU_EXPR, _MEM_EXPR)]
        if all(v is not None and v > 0 for v in vals):
            return
        time.sleep(0.5)
    sys.exit(f"Workload warmup 超时({WARMUP_TIMEOUT}s): "
             f"qps={_prom_value(_QPS_EXPR)} 见 .runtime/prometheus.log")


def seed_loki() -> None:
    ns = str(time.time_ns())
    payload = {"streams": [{"stream": {"app": "order-service"}, "values": [
        [ns, 'level=error msg="order-service 500: upstream timeout" trace=abc123']]}]}
    r = httpx.post(f"{LOKI_URL}/loki/api/v1/push", json=payload, timeout=10)
    r.raise_for_status()


def wait_loki_seed() -> None:
    deadline = time.time() + WARMUP_TIMEOUT
    query = '{app="order-service"}'
    while time.time() < deadline:
        now = time.time_ns()
        params = {"query": query, "limit": 10,
                  "start": str(now - 60 * 10**9), "end": str(now)}
        try:
            r = httpx.get(f"{LOKI_URL}/loki/api/v1/query_range", params=params, timeout=5)
            if r.json().get("data", {}).get("result"):
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(0.5)
    sys.exit(f"Loki seed readiness 超时({WARMUP_TIMEOUT}s)")


def _kill(name: str) -> None:
    pidfile = RUNTIME_DIR / f"{name}.pid"
    if pidfile.exists():
        pid = pidfile.read_text().strip()
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"], capture_output=True)
        pidfile.unlink(missing_ok=True)


def up_all() -> None:
    up()
    _ready()
    warmup_workload()
    seed_loki()
    wait_loki_seed()
    print(f"L1 后端就绪: prom={PROM_URL} loki={LOKI_URL} exporter={EXP_URL} cmdb={CMDB_URL}")


def down_all() -> None:
    for name in ("prometheus", "loki", "exporter", "cmdb"):
        _kill(name)
    print("L1 后端已停止")


def status() -> None:
    for name in ("prometheus", "loki", "exporter", "cmdb"):
        pidfile = RUNTIME_DIR / f"{name}.pid"
        print(f"{name}: {pidfile.read_text().strip() if pidfile.exists() else 'stopped'}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "up":
        up_all()
    elif cmd == "down":
        down_all()
    elif cmd == "status":
        status()

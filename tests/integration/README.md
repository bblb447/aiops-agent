# L1 Real Backend Integration Test

验证 Tool/Service 层对真实 Prometheus/Loki/Mock CMDB 的数据契约。设计见 docs/design.md §44。
Windows 宿主原生二进制运行，无 Docker/WSL。

## 一次性准备（下载二进制，版本以官方 release 为准）

```powershell
# 境内环境如需代理，先设系统代理变量（脚本自动复用，不写死个人地址）
$env:HTTPS_PROXY = "http://127.0.0.1:7897"
# 版本号先经 `gh api repos/prometheus/prometheus/releases/latest` 与 grafana/loki 核实
powershell -ExecutionPolicy Bypass -File tests/integration/scripts/setup_integration.ps1 -PromVersion 3.14.0 -LokiVersion 3.7.7
```

SHA256 校验通过后 exe 落在 `bin/`（git 忽略，不提交）。

## 跑 L1

```powershell
# 方式 A：pytest session 自动起停（推荐；同一进程内 4 文件共享一次 up/down）
"D:\开发\smolagents\.venv\Scripts\python.exe" -m pytest -m integration tests/integration/ -q
# 方式 B：手动管理后端（调试时）
powershell -ExecutionPolicy Bypass -File tests/integration/scripts/integration_up.ps1
powershell -ExecutionPolicy Bypass -File tests/integration/scripts/integration_down.ps1
```

## 跑 L0（默认，不收集 integration）

```powershell
"D:\开发\smolagents\.venv\Scripts\python.exe" -m pytest -q
```

## 说明

- Warmup/Seed 默认等待上限 10s；设 `AIOPS_INTEGRATION_WARMUP_SECONDS` 调整。
- 错误语义测试用隔离端口 127.0.0.1:31999（connection refused），不停共享后端。
- L1 只到 Tools/Service；L2 Scripted Agent、L3 Real LLM 沿 docs/design.md §44.2 分层扩展。

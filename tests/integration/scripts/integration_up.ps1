# Start L1 backends (Prometheus/Loki/exporter/Mock CMDB) and wait until ready.
# Usage: powershell -ExecutionPolicy Bypass -File integration_up.ps1
$Py = "D:\开发\smolagents\.venv\Scripts\python.exe"
& $Py (Join-Path $PSScriptRoot "..\backend.py") up
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

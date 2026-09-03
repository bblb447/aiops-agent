# Stop L1 backends started by integration_up.ps1.
# Usage: powershell -ExecutionPolicy Bypass -File integration_down.ps1
$Py = "D:\开发\smolagents\.venv\Scripts\python.exe"
& $Py (Join-Path $PSScriptRoot "..\backend.py") down

# Download + SHA256-verify Prometheus/Loki Windows binaries into tests/integration/bin/ (git-ignored).
# Idempotent: skips a component whose target exe already exists.
# Usage: powershell -ExecutionPolicy Bypass -File setup_integration.ps1 -PromVersion 3.14.0 -LokiVersion 3.7.7
# Proxy: reuses system HTTPS_PROXY/HTTP_PROXY if set (no hardcoded personal proxy).
param(
    [Parameter(Mandatory = $true)][string]$PromVersion,
    [Parameter(Mandatory = $true)][string]$LokiVersion
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Bin = Join-Path $Root "bin"
New-Item -ItemType Directory -Force -Path $Bin | Out-Null

$Proxy = if ($env:HTTPS_PROXY) { $env:HTTPS_PROXY } elseif ($env:HTTP_PROXY) { $env:HTTP_PROXY } else { $null }

function CurlGet([string]$Url) {
    if ($Proxy) { return curl.exe -sL -x $Proxy $Url } else { return curl.exe -sL $Url }
}

function Download([string]$Url, [string]$Dest) {
    Write-Host "Downloading $Url"
    if ($Proxy) { curl.exe -sL -x $Proxy -o $Dest $Url } else { curl.exe -sL -o $Dest $Url }
    if ($LASTEXITCODE -ne 0) { throw "download failed: $Url" }
}

function GrabHash([string]$ChecksumUrl, [string]$ZipName) {
    $row = (CurlGet $ChecksumUrl) | Where-Object { $_ -like "*$ZipName*" } | Select-Object -First 1
    if (-not $row) { throw "checksum row not found for $ZipName in $ChecksumUrl" }
    return $row.Trim().Split(" ")[0]
}

# ---- Prometheus (asset has a version prefix: prometheus-<v>.windows-amd64.zip) ----
$PromDest = Join-Path $Bin "prometheus"
$PromExe = Join-Path $PromDest "prometheus.exe"
if (Test-Path $PromExe) {
    Write-Host "skip prometheus (exists: $PromExe)"
} else {
    $PromZip = "prometheus-$PromVersion.windows-amd64.zip"
    $PromUrl = "https://github.com/prometheus/prometheus/releases/download/v$PromVersion/$PromZip"
    $PromChecksumUrl = "https://github.com/prometheus/prometheus/releases/download/v$PromVersion/sha256sums.txt"
    $zip = Join-Path $Bin $PromZip
    Download $PromUrl $zip
    $expect = (GrabHash $PromChecksumUrl $PromZip).ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($expect -ne $actual) { throw "SHA256 mismatch: $PromZip" }
    $stage = Join-Path $Bin "prom-stage"
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    Expand-Archive -Path $zip -DestinationPath $stage -Force
    $exe = Get-ChildItem $stage -Recurse -Filter "prometheus.exe" | Select-Object -First 1
    if (-not $exe) { throw "prometheus.exe not found in $PromZip" }
    New-Item -ItemType Directory -Force -Path $PromDest | Out-Null
    Copy-Item -Force $exe.FullName $PromExe
    Remove-Item $stage -Recurse -Force
    Remove-Item $zip -Force
    Write-Host "OK prometheus $PromVersion verified -> $PromExe"
}

# ---- Loki (asset has NO version prefix: loki-windows-amd64.exe.zip) ----
$LokiDest = Join-Path $Bin "loki"
$LokiExe = Join-Path $LokiDest "loki-windows-amd64.exe"
if (Test-Path $LokiExe) {
    Write-Host "skip loki (exists: $LokiExe)"
} else {
    $LokiZip = "loki-windows-amd64.exe.zip"
    $LokiUrl = "https://github.com/grafana/loki/releases/download/v$LokiVersion/$LokiZip"
    $LokiChecksumUrl = "https://github.com/grafana/loki/releases/download/v$LokiVersion/SHA256SUMS"
    $zip = Join-Path $Bin $LokiZip
    Download $LokiUrl $zip
    $expect = (GrabHash $LokiChecksumUrl $LokiZip).ToLower()
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($expect -ne $actual) { throw "SHA256 mismatch: $LokiZip" }
    New-Item -ItemType Directory -Force -Path $LokiDest | Out-Null
    Expand-Archive -Path $zip -DestinationPath $LokiDest -Force
    $exe = Get-ChildItem $LokiDest -Recurse -Filter "loki-windows-amd64.exe" | Select-Object -First 1
    if (-not $exe) { throw "loki-windows-amd64.exe not found in $LokiZip" }
    if ($exe.FullName -ne $LokiExe) { Copy-Item -Force $exe.FullName $LokiExe }
    Remove-Item $zip -Force
    Write-Host "OK loki $LokiVersion verified -> $LokiExe"
}
Write-Host "bin ready: $Bin"

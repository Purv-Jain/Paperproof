# run.ps1 — start the Paperproof dev server.
#
# Uses the project-local toolchain so nothing needs to be installed on the
# machine itself:
#   * the Python venv at .venv (Python 3.13, created with uv)
#   * a portable Node.js >= 22.22 under .node/ (auto-downloaded on first run)
#
# Usage (from the repository root):
#   .\run.ps1            # dev mode  -> http://localhost:3000
#   .\run.ps1 -Mode prod # prod mode (must build first via reflex export)
param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

# 1) Python venv
$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "No virtual environment found. Create it first:`n  uv venv --python 3.13 .venv`n  uv pip install -r requirements.txt"
    exit 1
}

# 2) Project-local Node.js (>= 22.22, required by React Router 8.4)
$nodeDir = @(Get-ChildItem (Join-Path $root ".node") -Directory -ErrorAction SilentlyContinue |
    Where-Object { Test-Path (Join-Path $_.FullName "node.exe") } |
    Sort-Object Name -Descending) | Select-Object -First 1

if (-not $nodeDir) {
    Write-Host "Downloading a portable Node.js (latest v22 LTS) into .node/ ..."
    $shas = Invoke-WebRequest "https://nodejs.org/dist/latest-v22.x/SHASUMS256.txt" -UseBasicParsing
    $file = ($shas.Content -split "`n") |
        Where-Object { $_ -match "win-x64\.zip$" } |
        Select-Object -First 1 |
        ForEach-Object { ($_ -split "\s+")[1].Trim() }
    if (-not $file) { Write-Error "Could not determine the latest Node 22 download."; exit 1 }

    New-Item -ItemType Directory -Force ".node" | Out-Null
    Invoke-WebRequest "https://nodejs.org/dist/latest-v22.x/$file" -OutFile ".node\$file" -UseBasicParsing
    Expand-Archive -Path ".node\$file" -DestinationPath ".node" -Force
    Remove-Item ".node\$file"
    $nodeDir = Get-ChildItem ".node" -Directory |
        Where-Object { Test-Path (Join-Path $_.FullName "node.exe") } |
        Select-Object -First 1
}

$env:PATH = "$($nodeDir.FullName);$env:PATH"
Write-Host "Using Node $((& (Join-Path $nodeDir.FullName "node.exe") --version)) from $($nodeDir.FullName)"
Write-Host "Starting Paperproof in $Mode mode -> http://localhost:3000"

# 3) Run reflex
& $python -m reflex run --env $Mode
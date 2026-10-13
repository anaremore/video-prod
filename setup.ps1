<#
.SYNOPSIS
  One-time setup for video-prod: a Python venv (PyTorch + NeMo), HyperFrames (npm), then `vp doctor`.

.DESCRIPTION
  Run from the repo folder:   powershell -ExecutionPolicy Bypass -File .\setup.ps1
  Safe to re-run. Needs FFmpeg (full build), Node.js 22+ and Python 3.12 on PATH.

.PARAMETER Cpu
  Install CPU-only PyTorch (no NVIDIA GPU). Everything works; transcription is much slower.

.PARAMETER Cuda
  PyTorch CUDA wheel tag, e.g. cu130 or cu128. Default: chosen from your NVIDIA driver.

.PARAMETER Python
  Path to the Python 3.12 used to create .venv. Default: `py -3.12`, else `python`.
#>
param([switch]$Cpu, [string]$Cuda = "", [string]$Python = "")
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

function Step($msg) { Write-Host "`n== $msg" -ForegroundColor Cyan }
function Check($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit $LASTEXITCODE)" } }
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

Step "Checking tools"
$missing = @()
if (-not (Have "ffmpeg")) { $missing += "FFmpeg (full build):  winget install Gyan.FFmpeg" }
if (-not (Have "node"))   { $missing += "Node.js 22+:          winget install OpenJS.NodeJS.LTS" }
elseif ([int]((node --version).TrimStart("v").Split(".")[0]) -lt 22) { $missing += "Node.js 22+ (yours is $(node --version)):  winget upgrade OpenJS.NodeJS.LTS" }
if (-not $Python -and -not (Have "py") -and -not (Have "python")) { $missing += "Python 3.12:          winget install Python.Python.3.12" }
if ($missing) {
  Write-Host "Install these, open a new terminal, and run setup again:" -ForegroundColor Yellow
  $missing | ForEach-Object { Write-Host "  $_" }
  exit 1
}
Write-Host "ffmpeg, node $(node --version) found"

Step "Python environment (.venv)"
$venvPy = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
  if ($Python) { & $Python -m venv .venv }
  elseif (Have "py") { & py -3.12 -m venv .venv }
  else { & python -m venv .venv }
  if (-not (Test-Path $venvPy)) { throw "Couldn't create .venv. Install Python 3.12 (winget install Python.Python.3.12) or pass -Python <path>." }
}
$ver = & $venvPy -c "import sys; print('%d.%d' % sys.version_info[:2])"
if ($ver -ne "3.12") { Write-Host "Note: .venv is Python $ver; it's tested on 3.12." -ForegroundColor Yellow }
& $venvPy -m pip install --upgrade pip --quiet; Check "pip upgrade"

Step "PyTorch"
if (-not $Cpu -and -not $Cuda) {
  if (Have "nvidia-smi") {
    $smi = (& nvidia-smi) -join "`n"
    if ($smi -match "CUDA Version:\s*(\d+)\.(\d+)") {
      $driverCuda = [int]$Matches[1] * 10 + [int]$Matches[2]
      $Cuda = if ($driverCuda -ge 130) { "cu130" } else { "cu128" }
    }
  }
  if (-not $Cuda) { $Cpu = $true; Write-Host "No NVIDIA GPU found: installing CPU PyTorch (transcription will be slow)." -ForegroundColor Yellow }
}
$index = if ($Cpu) { "https://download.pytorch.org/whl/cpu" } else { "https://download.pytorch.org/whl/$Cuda" }
Write-Host "torch from $index"
& $venvPy -m pip install torch --index-url $index; Check "PyTorch install"

Step "Python packages (NeMo etc.)"
& $venvPy -m pip install -r requirements.txt; Check "pip install -r requirements.txt"

Step "HyperFrames + fonts (npm)"
Push-Location motion
try { npm ci --no-fund --no-audit; Check "npm ci" } finally { Pop-Location }

Step "Doctor (copies GSAP and fonts, converts caption fonts, makes sound effects)"
& "$root\vp.cmd" doctor

Write-Host "`nNext:" -ForegroundColor Green
Write-Host "  1. Copy brand\brand.example.json to brand\brand.json and set your name, colors and devices."
Write-Host "  2. Open this folder in Claude Code and ask it to edit a recording (the youtube-edit skill)."
Write-Host "  3. To record with OBS: enable its WebSocket server, then .\vp setup_obs --dry-run"

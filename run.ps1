# Canli Toplanti Cevirmeni - baslatici
# Kullanim:  .\run.ps1          (overlay)
#            .\run.ps1 -Console (konsol modu)
param(
    [switch]$Console,
    [string]$Model,
    [ValidateSet("local", "deepl", "none")][string]$Engine
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Sanal ortam yok. Once kurulum:" -ForegroundColor Yellow
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .venv\Scripts\python -m pip install -r requirements.txt"
    Write-Host "  .venv\Scripts\python tools\convert_mt_model.py"
    exit 1
}

$argsList = @("-m", "src.main")
if ($Console) { $argsList += "--console" }
if ($Model)   { $argsList += @("--model", $Model) }
if ($Engine)  { $argsList += @("--engine", $Engine) }

Push-Location $root
try { & $python @argsList } finally { Pop-Location }

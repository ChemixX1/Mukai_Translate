[CmdletBinding()]
param(
    [string]$PythonVersion = "3.12",
    [switch]$PrepareAllModels
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    throw "Instala uv desde https://docs.astral.sh/uv/getting-started/installation/ y vuelve a ejecutar este script."
}

if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $uv.Source venv --python $PythonVersion .venv
    if ($LASTEXITCODE -ne 0) { throw "No se pudo crear .venv." }
}

& $uv.Source pip sync --python ".venv\Scripts\python.exe" requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "No se pudieron sincronizar las dependencias." }

$env:MUKAI_BOOTSTRAP_MODE = if ($PrepareAllModels) { "all" } else { "essential" }
$env:MUKAI_PRELOAD_WATERMARK_REMOVER = "1"
$env:HF_HUB_DISABLE_XET = "1"
& ".venv\Scripts\python.exe" -m app.bootstrap_runtime
if ($LASTEXITCODE -ne 0) { throw "No se pudieron preparar los motores." }

& (Join-Path $PSScriptRoot "build_developer_launcher.ps1")
Write-Host "Entorno listo. En adelante abre MukaiTranslator-Developer.exe; los cambios de código no requieren reinstalación."

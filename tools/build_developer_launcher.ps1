[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$source = Join-Path $PSScriptRoot "developer_launcher\MukaiTranslatorDeveloperLauncher.cs"
$output = Join-Path $projectRoot "MukaiTranslator-Developer.exe"
$icon = Join-Path $projectRoot "resources\icons\icon.ico"
$compiler = Join-Path $env:WINDIR "Microsoft.NET\Framework64\v4.0.30319\csc.exe"

if (-not (Test-Path -LiteralPath $compiler)) {
    throw "No se encontró el compilador C# de Windows: $compiler"
}
if (-not (Test-Path -LiteralPath $source)) {
    throw "No se encontró el código del lanzador: $source"
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "No se encontró el icono de Mukai Translator: $icon"
}

& $compiler /nologo /target:winexe /optimize+ "/win32icon:$icon" "/out:$output" /reference:System.dll /reference:System.Windows.Forms.dll $source
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo compilar el lanzador de desarrollo (código $LASTEXITCODE)."
}

Write-Host "Lanzador de desarrollo listo: $output"

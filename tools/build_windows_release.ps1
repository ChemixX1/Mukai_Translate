[CmdletBinding()]
param(
    [switch]$Installer,
    [switch]$SkipApplicationBuild,
    [switch]$SkipPortablePackage,
    [string]$PythonPath = ".venv\Scripts\python.exe"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$versionSource = Get-Content -LiteralPath "app\version.py" -Raw
if ($versionSource -notmatch '__version__\s*=\s*["'']([^"'']+)["'']') {
    throw "Could not read the application version from app\version.py."
}
$appVersion = $Matches[1]

if (-not (Test-Path -LiteralPath $PythonPath)) {
    throw "Python environment not found: $PythonPath"
}

$appExe = Join-Path $projectRoot "dist\MukaiTranslate\MukaiTranslate.exe"
if (-not $SkipApplicationBuild) {
    $sourceSelfTestLog = Join-Path $projectRoot "build\production-self-test-source.log"
    $previousSelfTestLog = $env:MUKAI_SELF_TEST_LOG
    $env:MUKAI_SELF_TEST_LOG = $sourceSelfTestLog
    try {
        & $PythonPath "mukai.py" "--production-self-test"
        if ($LASTEXITCODE -ne 0) {
            throw "Source production self-test failed. Review $sourceSelfTestLog"
        }
    }
    finally {
        $env:MUKAI_SELF_TEST_LOG = $previousSelfTestLog
    }

    $versionInfoPath = Join-Path $projectRoot "build\windows-version-info.txt"
    & $PythonPath "tools\generate_windows_version_info.py" --version $appVersion --output $versionInfoPath
    if ($LASTEXITCODE -ne 0) {
        throw "Could not generate the Windows version resource."
    }

    & $PythonPath -m PyInstaller --noconfirm --clean ct-windows.spec
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed with exit code $LASTEXITCODE."
    }
}

if (-not (Test-Path -LiteralPath $appExe)) {
    throw "Expected executable was not generated: $appExe"
}

$frozenSelfTestLog = Join-Path $projectRoot "build\production-self-test-frozen.log"
$previousSelfTestLog = $env:MUKAI_SELF_TEST_LOG
$env:MUKAI_SELF_TEST_LOG = $frozenSelfTestLog
try {
    $selfTest = Start-Process -FilePath $appExe -ArgumentList "--production-self-test" -WorkingDirectory (Split-Path -Parent $appExe) -Wait -PassThru
    if ($selfTest.ExitCode -ne 0) {
        throw "Frozen production self-test failed. Review $frozenSelfTestLog"
    }
}
finally {
    $env:MUKAI_SELF_TEST_LOG = $previousSelfTestLog
}

Write-Host "Release executable ready: $appExe"
Write-Host "Mukai version: $appVersion"

$releaseDir = Join-Path $projectRoot "releases\$appVersion"
New-Item -ItemType Directory -Path $releaseDir -Force | Out-Null
$portableZip = Join-Path $releaseDir "MukaiTranslator-Portable-$appVersion.zip"
if (-not $SkipPortablePackage) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    if (Test-Path -LiteralPath $portableZip) {
        Remove-Item -LiteralPath $portableZip -Force
    }
    [System.IO.Compression.ZipFile]::CreateFromDirectory(
        (Split-Path -Parent $appExe),
        $portableZip,
        [System.IO.Compression.CompressionLevel]::Optimal,
        $true
    )
    Write-Host "Portable package ready: $portableZip"
}

if (-not $Installer) {
    Write-Host "Run again with -Installer to create the Windows setup package."
    exit 0
}

$isccCandidates = @(@(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) })

if (-not $isccCandidates) {
    throw "Inno Setup 6 was not found. Install it, then run this script again with -Installer."
}

& ($isccCandidates[0]) "/DMyAppVersion=$appVersion" "tools\MukaiTranslator.iss"
if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

$installerPath = Join-Path $projectRoot "installer\MukaiTranslator-Setup-$appVersion.exe"
if (-not (Test-Path -LiteralPath $installerPath)) {
    throw "Expected installer was not generated: $installerPath"
}

$sha256 = (Get-FileHash -LiteralPath $installerPath -Algorithm SHA256).Hash.ToLowerInvariant()
$releaseInstaller = Join-Path $releaseDir (Split-Path -Leaf $installerPath)
Copy-Item -LiteralPath $installerPath -Destination $releaseInstaller -Force

$releaseManifest = [ordered]@{
    version = $appVersion
    built_at = [DateTime]::UtcNow.ToString("o")
    installer = [ordered]@{
        file = Split-Path -Leaf $releaseInstaller
        sha256 = $sha256
        bytes = (Get-Item -LiteralPath $releaseInstaller).Length
    }
}
if (Test-Path -LiteralPath $portableZip) {
    $releaseManifest['portable'] = [ordered]@{
        file = Split-Path -Leaf $portableZip
        sha256 = (Get-FileHash -LiteralPath $portableZip -Algorithm SHA256).Hash.ToLowerInvariant()
        bytes = (Get-Item -LiteralPath $portableZip).Length
    }
}
$manifestPath = Join-Path $releaseDir "release-manifest.json"
$releaseManifest | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

Write-Host "Installer ready: $installerPath"
Write-Host "SHA-256: $sha256"
Write-Host "Share-ready release folder: $releaseDir"

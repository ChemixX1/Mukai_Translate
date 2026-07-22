[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ReleaseNotes,
    [switch]$SkipBuild,
    [string]$SshHost = "156.67.71.240",
    [int]$SshPort = 65002,
    [string]$SshUser = "u889203727",
    [string]$WordPressPath = "/home/u889203727/domains/mangamukai.com/public_html",
    [string]$RemoteDownloadDir = "/home/u889203727/domains/mangamukai.com/public_html/mukai-updates",
    [string]$PublicDownloadBase = "https://mangamukai.com/mukai-updates"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_windows_release.ps1") -Installer
    if ($LASTEXITCODE -ne 0) {
        throw "The Windows release build failed with exit code $LASTEXITCODE."
    }
}

$versionSource = Get-Content -LiteralPath "app\version.py" -Raw
if ($versionSource -notmatch '__version__\s*=\s*["'']([^"'']+)["'']') {
    throw "Could not read app/version.py."
}
$version = $Matches[1]
$installer = Join-Path $projectRoot "installer\MukaiTranslator-Setup-$version.exe"
if (-not (Test-Path -LiteralPath $installer)) {
    throw "Installer not found: $installer"
}
if (-not $PublicDownloadBase.StartsWith("https://")) {
    throw "PublicDownloadBase must use HTTPS."
}

$sha256 = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
$filename = Split-Path -Leaf $installer
$installerUrl = "$($PublicDownloadBase.TrimEnd('/'))/$filename"
$release = [ordered]@{
    installer_url = $installerUrl
    notes = $ReleaseNotes.Trim()
    published_at = [DateTime]::UtcNow.ToString("o")
    sha256 = $sha256
    version = $version
}
if (-not $release.notes) {
    throw "ReleaseNotes cannot be empty."
}

$json = $release | ConvertTo-Json -Compress
$encodedJson = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($json))
$tempName = "mukai-publish-$([Guid]::NewGuid().ToString('N')).php"
$localPublisher = Join-Path $env:TEMP $tempName
$remotePublisher = "/home/$SshUser/$tempName"
$php = @"
<?php
`$release = json_decode(base64_decode('$encodedJson'), true);
if (!is_array(`$release) || empty(`$release['version']) || empty(`$release['installer_url']) || empty(`$release['sha256']) || empty(`$release['notes'])) {
    throw new RuntimeException('Invalid Mukai release payload.');
}
update_option('mukai_license_latest_update', `$release, false);
echo 'Published Mukai ', `$release['version'], PHP_EOL;
"@

try {
    Set-Content -LiteralPath $localPublisher -Value $php -Encoding UTF8
    $destination = "$SshUser@$SshHost"

    & ssh -o StrictHostKeyChecking=accept-new -p $SshPort $destination "mkdir -p '$RemoteDownloadDir'"
    if ($LASTEXITCODE -ne 0) { throw "Could not prepare the isolated update directory." }

    & scp -o StrictHostKeyChecking=accept-new -P $SshPort $installer "${destination}:$RemoteDownloadDir/$filename"
    if ($LASTEXITCODE -ne 0) { throw "Could not upload the installer." }

    & scp -o StrictHostKeyChecking=accept-new -P $SshPort $localPublisher "${destination}:$remotePublisher"
    if ($LASTEXITCODE -ne 0) { throw "Could not upload the temporary publisher." }

    & ssh -o StrictHostKeyChecking=accept-new -p $SshPort $destination "/opt/alt/php82/usr/bin/php /usr/local/bin/wp eval-file '$remotePublisher' --path='$WordPressPath' --skip-themes"
    if ($LASTEXITCODE -ne 0) { throw "WordPress did not publish the release manifest." }

    & ssh -o StrictHostKeyChecking=accept-new -p $SshPort $destination "rm -f '$remotePublisher'"

    Write-Host "Update published: $version"
    Write-Host "Installer: $installerUrl"
    Write-Host "SHA-256: $sha256"
}
finally {
    Remove-Item -LiteralPath $localPublisher -Force -ErrorAction SilentlyContinue
}

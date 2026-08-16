$ErrorActionPreference = 'Stop'

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$ToolsRoot = Join-Path $RepositoryRoot '.tools'
$Version = '5.3.0'
$ArchiveName = "epubcheck-$Version.zip"
$ArchivePath = Join-Path $ToolsRoot $ArchiveName
$InstallRoot = Join-Path $ToolsRoot "epubcheck-$Version"
$JarPath = Join-Path $InstallRoot 'epubcheck.jar'
$ExpectedSha256 = '6c07e68584b2e2ce2f89fe06e1246dfead3eb36b46b340e7d93524f29dcff6c5'
$DownloadUrl = "https://github.com/w3c/epubcheck/releases/download/v$Version/$ArchiveName"

if (Test-Path -LiteralPath $JarPath) {
    Write-Output $JarPath
    exit 0
}

New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
Invoke-WebRequest -Uri $DownloadUrl -OutFile $ArchivePath
$ActualSha256 = (Get-FileHash -LiteralPath $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualSha256 -ne $ExpectedSha256) {
    Remove-Item -LiteralPath $ArchivePath -Force
    throw "EPUBCheck archive hash mismatch: $ActualSha256"
}

Expand-Archive -LiteralPath $ArchivePath -DestinationPath $ToolsRoot -Force
Remove-Item -LiteralPath $ArchivePath -Force
if (-not (Test-Path -LiteralPath $JarPath)) {
    throw "EPUBCheck archive did not contain $JarPath"
}
Write-Output $JarPath

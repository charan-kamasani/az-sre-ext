# Install the `az sre` extension from a GitHub release, verifying its checksum.
#
# Usage:
#   irm https://raw.githubusercontent.com/charan-kamasani/az-sre-ext/master/scripts/install.ps1 | iex
#
# Environment:
#   SRE_INSTALL_VERSION   Release tag to install, for example v1.0.0b1. Default: newest release.
#   SRE_INSTALL_REPO      GitHub repository. Default: charan-kamasani/az-sre-ext.
#   SRE_INSTALL_BASE_URL  Override the download location (testing).

$ErrorActionPreference = 'Stop'

$repo = if ($env:SRE_INSTALL_REPO) { $env:SRE_INSTALL_REPO } else { 'charan-kamasani/az-sre-ext' }
$version = $env:SRE_INSTALL_VERSION

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI not found. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli'
}

if (-not $version) {
    $releases = Invoke-RestMethod "https://api.github.com/repos/$repo/releases?per_page=1"
    $version = @($releases)[0].tag_name
    if (-not $version) { throw "Could not find a release in $repo" }
}

$baseUrl = if ($env:SRE_INSTALL_BASE_URL) { $env:SRE_INSTALL_BASE_URL } else { "https://github.com/$repo/releases/download/$version" }
$wheel = "sre-$($version.TrimStart('v'))-py3-none-any.whl"

$work = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $work | Out-Null

try {
    Write-Host "Downloading $wheel ($version)"
    Invoke-WebRequest "$baseUrl/$wheel" -OutFile (Join-Path $work $wheel)
    Invoke-WebRequest "$baseUrl/SHA256SUMS" -OutFile (Join-Path $work 'SHA256SUMS')

    $line = Get-Content (Join-Path $work 'SHA256SUMS') | Where-Object { $_ -match "\s$([regex]::Escape($wheel))$" } | Select-Object -First 1
    if (-not $line) { throw "$wheel is not listed in SHA256SUMS" }
    $expected = ($line -split '\s+')[0]
    $actual = (Get-FileHash (Join-Path $work $wheel) -Algorithm SHA256).Hash
    if ($actual -ne $expected.ToUpperInvariant()) { throw "Checksum mismatch for $wheel" }

    az extension add --source (Join-Path $work $wheel) --upgrade --yes
    if ($LASTEXITCODE -ne 0) { throw 'az extension add failed' }
    az sre --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "The extension installed but 'az sre' did not load" }

    Write-Host "Installed az sre $version. Run: az sre --help"
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

# Install the `az sre` extension from a GitHub release.
#
# Verifies the wheel against the release SHA256SUMS and, when an authenticated
# GitHub CLI is available, against its GitHub build-provenance attestation.
#
# Usage:
#   irm https://raw.githubusercontent.com/charan-kamasani/az-sre-ext/master/scripts/install.ps1 | iex
#   .\install.ps1 -ReleaseTag v1.0.0b1
#
# Parameters (each has a matching SRE_INSTALL_* environment variable):
#   -Repo OWNER/NAME        GitHub repository. Default: charan-kamasani/az-sre-ext.
#   -ReleaseTag TAG         Release to install, for example v1.0.0b1.
#   -LatestRelease          Install the newest release. This is the default.
#   -RequireAttestation     Fail unless the attestation was verified.
#   -BaseUrl URL            Download location override (testing only).

[CmdletBinding()]
param(
    [string]$Repo = $(if ($env:SRE_INSTALL_REPO) { $env:SRE_INSTALL_REPO } else { 'charan-kamasani/az-sre-ext' }),
    [string]$ReleaseTag = $(if ($env:SRE_INSTALL_RELEASE_TAG) { $env:SRE_INSTALL_RELEASE_TAG } else { $env:SRE_INSTALL_VERSION }),
    [switch]$LatestRelease,
    [switch]$RequireAttestation = ($env:SRE_INSTALL_REQUIRE_ATTESTATION -eq '1'),
    [string]$BaseUrl = $env:SRE_INSTALL_BASE_URL
)

$ErrorActionPreference = 'Stop'

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw 'Azure CLI not found. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli'
}

if ($LatestRelease) { $ReleaseTag = '' }
if (-not $ReleaseTag) {
    $releases = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases?per_page=1"
    $ReleaseTag = @($releases)[0].tag_name
    if (-not $ReleaseTag) { throw "No release found in $Repo" }
}
if ($ReleaseTag -notmatch '^v\d+\.\d+\.\d+b\d+$') {
    throw "Release tag '$ReleaseTag' must look like v1.0.0b1"
}

$downloadUrl = if ($BaseUrl) { $BaseUrl } else { "https://github.com/$Repo/releases/download/$ReleaseTag" }
$wheel = "sre-$($ReleaseTag.TrimStart('v'))-py3-none-any.whl"

$work = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $work | Out-Null

try {
    Write-Host "Downloading $wheel ($ReleaseTag)"
    $wheelPath = Join-Path $work $wheel
    Invoke-WebRequest "$downloadUrl/$wheel" -OutFile $wheelPath
    Invoke-WebRequest "$downloadUrl/SHA256SUMS" -OutFile (Join-Path $work 'SHA256SUMS')

    $lines = @(Get-Content (Join-Path $work 'SHA256SUMS') | Where-Object { $_ -match "\s$([regex]::Escape($wheel))$" })
    if ($lines.Count -ne 1) { throw "SHA256SUMS must list $wheel exactly once (found $($lines.Count))" }
    $expected = ($lines[0] -split '\s+')[0]
    $actual = (Get-FileHash $wheelPath -Algorithm SHA256).Hash
    if ($actual -ne $expected.ToUpperInvariant()) { throw "Checksum mismatch for $wheel" }
    Write-Host 'Checksum verified.'

    $attested = $false
    $ghReady = $false
    if (-not $BaseUrl -and (Get-Command gh -ErrorAction SilentlyContinue)) {
        gh auth status 2>$null | Out-Null
        $ghReady = ($LASTEXITCODE -eq 0)
    }
    if ($BaseUrl) {
        Write-Host 'Skipping attestation: custom -BaseUrl.'
    }
    elseif ($ghReady) {
        gh attestation verify $wheelPath --repo $Repo `
            --signer-workflow "$Repo/.github/workflows/release.yml" `
            --source-ref "refs/tags/$ReleaseTag" `
            --deny-self-hosted-runners | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Attestation verification failed for $wheel" }
        $attested = $true
        Write-Host 'Attestation verified.'
    }
    else {
        Write-Host 'Attestation not checked: sign in to the GitHub CLI (gh auth login) to enable it.'
    }
    if ($RequireAttestation -and -not $attested) {
        throw 'Attestation verification was required but did not run'
    }

    az extension add --source $wheelPath --upgrade --yes
    if ($LASTEXITCODE -ne 0) { throw 'az extension add failed' }
    az sre --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "The extension installed but 'az sre' did not load" }

    Write-Host "Installed az sre $ReleaseTag. Run: az sre --help"
}
finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

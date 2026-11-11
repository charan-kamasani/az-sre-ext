# Install the `az sre` extension from a GitHub release.
#
# The repository is private, so downloads go through the signed-in GitHub CLI
# (gh auth login). Verifies the wheel against the release SHA256SUMS and its
# GitHub build-provenance attestation.
#
# Usage:
#   gh api -H 'Accept: application/vnd.github.raw+json' repos/charan-kamasani/az-sre-ext/contents/scripts/install.ps1 | Out-String | iex
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

if (-not $BaseUrl) {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw 'GitHub CLI not found. Install it from https://cli.github.com and run: gh auth login'
    }
    gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'GitHub CLI is not signed in. Run: gh auth login' }
}

if ($LatestRelease) { $ReleaseTag = '' }
if (-not $ReleaseTag) {
    if ($BaseUrl) { throw '-BaseUrl needs -ReleaseTag' }
    $ReleaseTag = gh api "repos/$Repo/releases?per_page=20" --jq '[.[] | select(.draft | not)][0].tag_name // empty'
    if ($LASTEXITCODE -ne 0) { throw "Release lookup failed for $Repo. Check that your GitHub account can see the repository." }
    if (-not $ReleaseTag) { throw "No release found in $Repo" }
}
if ($ReleaseTag -notmatch '^v\d+\.\d+\.\d+b\d+$') {
    throw "Release tag '$ReleaseTag' must look like v1.0.0b1"
}

$wheel = "sre-$($ReleaseTag.TrimStart('v'))-py3-none-any.whl"

$work = Join-Path ([IO.Path]::GetTempPath()) ([IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $work | Out-Null

try {
    Write-Host "Downloading $wheel ($ReleaseTag)"
    $wheelPath = Join-Path $work $wheel
    if ($BaseUrl) {
        Invoke-WebRequest "$BaseUrl/$wheel" -OutFile $wheelPath
        Invoke-WebRequest "$BaseUrl/SHA256SUMS" -OutFile (Join-Path $work 'SHA256SUMS')
    }
    else {
        gh release download $ReleaseTag --repo $Repo --dir $work --pattern $wheel --pattern SHA256SUMS
        if ($LASTEXITCODE -ne 0) { throw "Could not download $wheel and SHA256SUMS from release $ReleaseTag" }
    }

    $lines = @(Get-Content (Join-Path $work 'SHA256SUMS') | Where-Object { $_ -match "\s$([regex]::Escape($wheel))$" })
    if ($lines.Count -ne 1) { throw "SHA256SUMS must list $wheel exactly once (found $($lines.Count))" }
    $expected = ($lines[0] -split '\s+')[0]
    $actual = (Get-FileHash $wheelPath -Algorithm SHA256).Hash
    if ($actual -ne $expected.ToUpperInvariant()) { throw "Checksum mismatch for $wheel" }
    Write-Host 'Checksum verified.'

    $attested = $false
    if ($BaseUrl) {
        Write-Host 'Skipping attestation: custom -BaseUrl.'
    }
    else {
        gh attestation verify $wheelPath --repo $Repo `
            --signer-workflow "$Repo/.github/workflows/release.yml" `
            --source-ref "refs/tags/$ReleaseTag" `
            --deny-self-hosted-runners | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Attestation verification failed for $wheel" }
        $attested = $true
        Write-Host 'Attestation verified.'
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

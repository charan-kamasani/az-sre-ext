#!/usr/bin/env sh
# Install the `az sre` extension from a GitHub release.
#
# Verifies the wheel against the release SHA256SUMS and, when an authenticated
# GitHub CLI is available, against its GitHub build-provenance attestation.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/charan-kamasani/az-sre-ext/master/scripts/install.sh | sh
#   sh install.sh --release-tag v1.0.0b1
#
# Options (each has a matching SRE_INSTALL_* environment variable):
#   --repo OWNER/NAME        GitHub repository. Default: charan-kamasani/az-sre-ext.
#   --release-tag TAG        Release to install, for example v1.0.0b1.
#   --latest-release         Install the newest release. This is the default.
#   --require-attestation    Fail unless the attestation was verified.
#   --base-url URL           Download location override (testing only).
#   -h, --help               Show this help.

set -eu

REPO="${SRE_INSTALL_REPO:-charan-kamasani/az-sre-ext}"
RELEASE_TAG="${SRE_INSTALL_RELEASE_TAG:-${SRE_INSTALL_VERSION:-}}"
REQUIRE_ATTESTATION="${SRE_INSTALL_REQUIRE_ATTESTATION:-0}"
BASE_URL="${SRE_INSTALL_BASE_URL:-}"

fail() {
  printf 'ERROR: %s\n' "$1" >&2
  exit 1
}

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --repo) [ "$#" -ge 2 ] || fail "--repo needs a value"; REPO="$2"; shift 2 ;;
    --release-tag) [ "$#" -ge 2 ] || fail "--release-tag needs a value"; RELEASE_TAG="$2"; shift 2 ;;
    --latest-release) RELEASE_TAG=""; shift ;;
    --require-attestation) REQUIRE_ATTESTATION=1; shift ;;
    --base-url) [ "$#" -ge 2 ] || fail "--base-url needs a value"; BASE_URL="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; fail "unknown option: $1" ;;
  esac
done

command -v az >/dev/null 2>&1 || fail "Azure CLI not found. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if [ -z "$RELEASE_TAG" ]; then
  RELEASE_TAG="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=1" |
    sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)" ||
    fail "release lookup failed for ${REPO}"
  [ -n "$RELEASE_TAG" ] || fail "no release found in ${REPO}"
fi

case "$RELEASE_TAG" in
  v[0-9]*.[0-9]*.[0-9]*b[0-9]*) ;;
  *) fail "release tag '$RELEASE_TAG' must look like v1.0.0b1" ;;
esac

DOWNLOAD_URL="${BASE_URL:-https://github.com/${REPO}/releases/download/${RELEASE_TAG}}"
WHEEL="sre-${RELEASE_TAG#v}-py3-none-any.whl"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

printf 'Downloading %s (%s)\n' "$WHEEL" "$RELEASE_TAG"
curl -fsSL -o "$WORK/$WHEEL" "$DOWNLOAD_URL/$WHEEL" || fail "could not download $DOWNLOAD_URL/$WHEEL"
curl -fsSL -o "$WORK/SHA256SUMS" "$DOWNLOAD_URL/SHA256SUMS" || fail "could not download SHA256SUMS"

MATCHES="$(grep -c " $WHEEL\$" "$WORK/SHA256SUMS" || true)"
[ "$MATCHES" = "1" ] || fail "SHA256SUMS must list $WHEEL exactly once (found $MATCHES)"
EXPECTED="$(grep " $WHEEL\$" "$WORK/SHA256SUMS" | awk '{print $1}')"

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$WORK/$WHEEL" | awk '{print $1}')"
elif command -v shasum >/dev/null 2>&1; then
  ACTUAL="$(shasum -a 256 "$WORK/$WHEEL" | awk '{print $1}')"
else
  fail "sha256sum or shasum is required"
fi
[ "$ACTUAL" = "$EXPECTED" ] || fail "checksum mismatch for $WHEEL"
echo "Checksum verified."

ATTESTED=0
if [ -n "$BASE_URL" ]; then
  echo "Skipping attestation: custom --base-url."
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  gh attestation verify "$WORK/$WHEEL" \
    --repo "$REPO" \
    --signer-workflow "$REPO/.github/workflows/release.yml" \
    --source-ref "refs/tags/$RELEASE_TAG" \
    --deny-self-hosted-runners >/dev/null ||
    fail "attestation verification failed for $WHEEL"
  ATTESTED=1
  echo "Attestation verified."
else
  echo "Attestation not checked: sign in to the GitHub CLI (gh auth login) to enable it."
fi
if [ "$REQUIRE_ATTESTATION" = "1" ] && [ "$ATTESTED" != "1" ]; then
  fail "attestation verification was required but did not run"
fi

az extension add --source "$WORK/$WHEEL" --upgrade --yes
az sre --help >/dev/null || fail "the extension installed but 'az sre' did not load"

printf 'Installed az sre %s. Run: az sre --help\n' "$RELEASE_TAG"

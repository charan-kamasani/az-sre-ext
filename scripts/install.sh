#!/usr/bin/env sh
# Install the `az sre` extension from a GitHub release, verifying its checksum.
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/charan-kamasani/az-sre-ext/master/scripts/install.sh | sh
#
# Environment:
#   SRE_INSTALL_VERSION   Release tag to install, for example v1.0.0b1. Default: newest release.
#   SRE_INSTALL_REPO      GitHub repository. Default: charan-kamasani/az-sre-ext.
#   SRE_INSTALL_BASE_URL  Override the download location (testing).

set -eu

REPO="${SRE_INSTALL_REPO:-charan-kamasani/az-sre-ext}"
VERSION="${SRE_INSTALL_VERSION:-}"

fail() {
  printf 'error: %s\n' "$1" >&2
  exit 1
}

command -v az >/dev/null 2>&1 || fail "Azure CLI not found. Install it from https://learn.microsoft.com/cli/azure/install-azure-cli"
command -v curl >/dev/null 2>&1 || fail "curl is required"

if [ -z "$VERSION" ]; then
  VERSION="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases?per_page=1" |
    sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n 1)"
  [ -n "$VERSION" ] || fail "could not find a release in ${REPO}"
fi

BASE_URL="${SRE_INSTALL_BASE_URL:-https://github.com/${REPO}/releases/download/${VERSION}}"
WHEEL="sre-${VERSION#v}-py3-none-any.whl"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

printf 'Downloading %s (%s)\n' "$WHEEL" "$VERSION"
curl -fsSL -o "$WORK/$WHEEL" "$BASE_URL/$WHEEL" || fail "could not download $BASE_URL/$WHEEL"
curl -fsSL -o "$WORK/SHA256SUMS" "$BASE_URL/SHA256SUMS" || fail "could not download SHA256SUMS"

EXPECTED="$(grep " $WHEEL\$" "$WORK/SHA256SUMS" | awk '{print $1}')"
[ -n "$EXPECTED" ] || fail "$WHEEL is not listed in SHA256SUMS"

if command -v sha256sum >/dev/null 2>&1; then
  ACTUAL="$(sha256sum "$WORK/$WHEEL" | awk '{print $1}')"
else
  ACTUAL="$(shasum -a 256 "$WORK/$WHEEL" | awk '{print $1}')"
fi
[ "$ACTUAL" = "$EXPECTED" ] || fail "checksum mismatch for $WHEEL"

az extension add --source "$WORK/$WHEEL" --upgrade --yes
az sre --help >/dev/null || fail "the extension installed but 'az sre' did not load"

printf 'Installed az sre %s. Run: az sre --help\n' "$VERSION"

#!/usr/bin/env bash
# Install a built wheel into a clean, isolated Azure CLI and check that every
# documented command loads.
set -euo pipefail

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
  echo "Usage: $0 <sre-wheel> [expected-version]" >&2
  exit 2
fi

wheel="$1"
required_version="${2:-}"
if [ ! -f "$wheel" ]; then
  echo "Wheel not found: $wheel" >&2
  exit 2
fi
wheel_name="${wheel##*/}"
case "$wheel_name" in
  sre-*-py3-none-any.whl) ;;
  *)
    echo "Unexpected wheel filename: $wheel_name" >&2
    exit 2
    ;;
esac
wheel_version="${wheel_name#sre-}"
wheel_version="${wheel_version%-py3-none-any.whl}"
if [ -n "$required_version" ] && [ "$wheel_version" != "$required_version" ]; then
  echo "Wheel version '$wheel_version' does not match '$required_version'." >&2
  exit 1
fi
if ! command -v az >/dev/null 2>&1; then
  echo "az is required on PATH." >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
reference="$root/docs/cli-reference.md"
if [ ! -f "$reference" ]; then
  echo "Missing $reference" >&2
  exit 2
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT
export AZURE_CONFIG_DIR="${work_dir}/azure"
export AZURE_EXTENSION_DIR="${work_dir}/extensions"
mkdir -p "$AZURE_CONFIG_DIR" "$AZURE_EXTENSION_DIR"

az extension add --source "$wheel" --yes >/dev/null

installed_version="$(az extension show --name sre --query version -o tsv)"
if [ "$installed_version" != "$wheel_version" ]; then
  echo "Installed version '$installed_version' does not match wheel '$wheel_version'." >&2
  exit 1
fi

commands=()
while IFS= read -r line; do
  commands+=("$line")
done < <(sed -n 's/^#\{2,3\} `\(az sre[^`]*\)`$/\1/p' "$reference")

if [ "${#commands[@]}" -lt 50 ]; then
  echo "Expected at least 50 commands in $reference, found ${#commands[@]}." >&2
  exit 1
fi

echo "Verifying ${#commands[@]} az sre command and group help surfaces..."
for command in "${commands[@]}"; do
  read -r -a command_args <<<"$command"
  if ! "${command_args[@]}" --help >/dev/null 2>"$work_dir/stderr"; then
    echo "Help failed for: $command" >&2
    cat "$work_dir/stderr" >&2
    exit 1
  fi
done

if az sre not-a-real-command --help >/dev/null 2>&1; then
  echo "An unknown command unexpectedly resolved." >&2
  exit 1
fi

echo "Credential-free az sre wheel verification passed."

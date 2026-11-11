#!/usr/bin/env python3
"""Credential-free verification of a built sre wheel in a clean Azure CLI.

Installs the exact wheel with ``az extension add --source`` into throwaway
config/extension directories (so nothing from the developer machine leaks in),
then checks that:

* the wheel filename, ``az extension show``, ``az version`` and ``az sre version`` agree on
  the version (and match ``--expected-version`` when given);
* every command and group documented in ``docs/cli-reference.md`` answers
  ``--help`` without error;
* the installed command inventory (as listed by group help) matches the
  documented inventory exactly -- nothing missing, nothing undocumented;
* the CLI rejects an unknown argument before making any request.

Runs on Windows, macOS and Linux. Needs only ``az`` on PATH.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "docs" / "cli-reference.md"
WHEEL_RE = re.compile(r"^sre-(?P<version>[^-]+)-py3-none-any\.whl$")
HEADING_RE = re.compile(r"^(#{2,4}) `az (sre(?: [^`]*)?)`\s*$")
# Group help lists children as "    name [Preview] : summary" under Subgroups:/Commands:.
HELP_SECTION_RE = re.compile(r"^(Subgroups|Commands):\s*$")
HELP_ENTRY_RE = re.compile(r"^\s{4}(\S+)(?:\s+\[[^\]]+\])*\s*:")


def documented_surfaces() -> dict[str, bool]:
    """Return {"sre ...": is_group} for every heading in the CLI reference."""
    surfaces: dict[str, bool] = {}
    for line in REFERENCE.read_text(encoding="utf-8").splitlines():
        match = HEADING_RE.match(line)
        if match:
            surfaces[match.group(2)] = len(match.group(1)) == 2
    if not surfaces:
        raise SystemExit(f"No `az sre ...` headings found in {REFERENCE}")
    return surfaces


def run_az(az: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run([az, *args], env=env, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=False)


def help_children(help_text: str) -> set[str]:
    children: set[str] = set()
    in_section = False
    for line in help_text.splitlines():
        if HELP_SECTION_RE.match(line):
            in_section = True
            continue
        if in_section:
            entry = HELP_ENTRY_RE.match(line)
            if entry:
                children.add(entry.group(1))
            elif line.strip() and not line.startswith(" "):
                in_section = False
    return children


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--expected-version", help="Fail unless the wheel has exactly this version.")
    parser.add_argument("--jobs", type=int, default=4, help="Parallel --help invocations.")
    opts = parser.parse_args()

    wheel = opts.wheel.resolve()
    if not wheel.is_file():
        fail(f"Wheel not found: {wheel}")
    name_match = WHEEL_RE.match(wheel.name)
    if not name_match:
        fail(f"Unexpected wheel filename: {wheel.name}")
    wheel_version = name_match.group("version")
    if opts.expected_version and wheel_version != opts.expected_version:
        fail(f"Wheel version {wheel_version!r} does not match expected {opts.expected_version!r}")

    az = shutil.which("az")
    if not az:
        fail("az is required on PATH")

    with tempfile.TemporaryDirectory(prefix="sre-wheel-verify-") as work:
        env = dict(os.environ)
        env.update({
            "AZURE_CONFIG_DIR": str(Path(work, "config")),
            "AZURE_EXTENSION_DIR": str(Path(work, "extensions")),
            "AZURE_EXTENSION_SYS_DIR": str(Path(work, "sys-extensions")),
            "AZURE_EXTENSION_DEV_SOURCES": "",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_NO_COLOR": "true",
        })

        cli_version = run_az(az, ["version", "-o", "json"], env)
        if cli_version.returncode == 0:
            print(f"azure-cli-core {json.loads(cli_version.stdout).get('azure-cli-core')}")

        print(f"Installing {wheel.name} into a clean extension directory...")
        added = run_az(az, ["extension", "add", "--source", str(wheel), "--yes"], env)
        if added.returncode != 0:
            fail(f"az extension add failed:\n{added.stdout}{added.stderr}")

        shown = run_az(az, ["extension", "show", "--name", "sre", "-o", "json"], env)
        if shown.returncode != 0:
            fail(f"az extension show failed:\n{shown.stderr}")
        ext_version = json.loads(shown.stdout).get("version")
        if ext_version != wheel_version:
            fail(f"az extension show reports {ext_version!r}, wheel is {wheel_version!r}")

        # Azure CLI reads extension versions through pkginfo; wheel metadata it
        # cannot parse makes `az version` report the extension as "Unknown".
        listed = run_az(az, ["version", "-o", "json"], env)
        listed_version = json.loads(listed.stdout).get("extensions", {}).get("sre") if listed.returncode == 0 else None
        if listed_version != wheel_version:
            fail(f"az version reports sre {listed_version!r}, wheel is {wheel_version!r}")

        reported = run_az(az, ["sre", "version", "-o", "json"], env)
        if reported.returncode != 0:
            fail(f"az sre version failed:\n{reported.stderr}")
        sre_version = json.loads(reported.stdout).get("extensionVersion")
        if sre_version != wheel_version:
            fail(f"az sre version reports {sre_version!r}, wheel is {wheel_version!r}")
        print(f"Version {wheel_version} confirmed by filename, extension show, az version and az sre version")

        surfaces = documented_surfaces()
        command_count = sum(1 for is_group in surfaces.values() if not is_group)
        print(f"Checking --help for {len(surfaces)} surfaces ({command_count} commands)...")

        def check(surface: str):
            return surface, run_az(az, [*surface.split(), "--help"], env)

        failures: list[str] = []
        installed: dict[str, set[str]] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, opts.jobs)) as pool:
            for surface, result in pool.map(check, surfaces):
                noisy = re.search(r"Unable to load extension|Traceback|ModuleNotFoundError|ImportError",
                                  result.stdout + result.stderr)
                if result.returncode != 0 or noisy:
                    failures.append(f"az {surface} --help (exit {result.returncode}):\n{result.stderr.strip()}")
                elif surfaces[surface]:
                    installed[surface] = help_children(result.stdout)
        if failures:
            fail(f"{len(failures)} help surface(s) failed:\n" + "\n".join(failures))

        documented_children = {group: set() for group, is_group in surfaces.items() if is_group}
        for surface in surfaces:
            parent, _, leaf = surface.rpartition(" ")
            if parent in documented_children:
                documented_children[parent].add(leaf)
        drift = []
        for group, expected in sorted(documented_children.items()):
            actual = installed.get(group, set())
            if actual - expected:
                drift.append(f"az {group}: undocumented {sorted(actual - expected)}")
            if expected - actual:
                drift.append(f"az {group}: documented but not installed {sorted(expected - actual)}")
        if drift:
            fail("Installed command inventory differs from docs/cli-reference.md:\n" + "\n".join(drift))
        print(f"{command_count}/{command_count} commands load; inventory matches docs/cli-reference.md")

        bogus = run_az(az, ["sre", "agent", "show", "--resource-group", "rg", "--name", "n",
                            "--subscription", "00000000-0000-0000-0000-000000000000",
                            "--definitely-not-an-argument"], env)
        if bogus.returncode == 0 or "unrecognized arguments" not in bogus.stderr:
            fail(f"Unknown argument was not rejected:\n{bogus.stdout}{bogus.stderr}")

    print("Credential-free sre wheel verification passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

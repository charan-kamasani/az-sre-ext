#!/usr/bin/env python3
"""Live end-to-end canary for the installed ``az sre`` extension.

Drives the core customer journey against real Azure and fails on any
mismatch between CLI output and the actual resource state:

1. agent lifecycle: create, show, list, update, stop, start
2. content round trip: instructions and a text knowledge source (create, show,
   list, duplicate-create rejected, delete, verify gone)
3. RBAC: grant the caller ``reader`` on the agent with ``--assignee-me`` (no
   Microsoft Graph), verify it independently with ``az role assignment list``,
   revoke it, verify only that assignment went away
4. negative cases: a missing agent fails, an unknown argument fails
5. secret safety: the caller's access token never appears in any captured
   output, including ``--debug`` logs
6. delete the agent, verify it is gone, then delete the resource group

The resource group must not exist beforehand (the canary exits with code 2
if it does). The group is tagged with a per-run nonce, and only a group this
run created and tagged is deleted at the end, also on failure (unless
``--keep``). Every ``az`` call has a timeout. Evidence is written to
``<results-dir>/live-canary.json``; it holds command lines, exit codes and
pass/fail, never raw output or tokens.

Creates billable resources. The signed-in identity needs Contributor on the
subscription, plus Role Based Access Control Administrator limited to the SRE
Agent roles for the RBAC scenario (or pass ``--skip-rbac``).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

AZ = shutil.which("az")

TIMEOUT_LONG = 15 * 60  # long-running operations (agent create/stop/start/delete, group delete)
TIMEOUT_SHORT = 3 * 60
PURPOSE_TAG = "purpose=sre-live-canary"
RUN_TAG = "sre-canary-run"
CREATED_TAG = "sre-canary-created"


class CanaryFailure(Exception):
    pass


class Canary:
    def __init__(self, opts: argparse.Namespace):
        self.opts = opts
        self.steps: list[dict] = []
        self.outputs: list[str] = []
        self.common = ["--subscription", opts.subscription]
        self.run_id = uuid.uuid4().hex
        self.created_rg = False

    def az(self, *args: str, expect_ok: bool = True, capture: bool = True,
           long_running: bool = False) -> subprocess.CompletedProcess:
        cmd = [AZ, *args, "--only-show-errors"] if "--debug" not in args else [AZ, *args]
        shown = " ".join(["az", *args])
        timeout = TIMEOUT_LONG if long_running else TIMEOUT_SHORT
        started = time.monotonic()
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                    errors="replace", check=False, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            if capture:
                self.outputs.append(_text(exc.stdout) + _text(exc.stderr))
            print(f"$ {shown}  -> timed out after {timeout}s", flush=True)
            raise CanaryFailure(f"`{shown}` timed out after {timeout}s") from exc
        if capture:
            self.outputs.append(result.stdout + result.stderr)
        print(f"$ {shown}  -> exit {result.returncode} ({time.monotonic() - started:.0f}s)", flush=True)
        if expect_ok and result.returncode != 0:
            raise CanaryFailure(f"`{shown}` failed:\n{result.stderr.strip()[-2000:]}")
        return result

    def json(self, *args: str, long_running: bool = False):
        out = self.az(*args, "-o", "json", long_running=long_running).stdout.strip()
        return json.loads(out) if out else None

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        self.steps.append({"step": name, "passed": bool(condition), "detail": detail})
        print(f"  [{'PASS' if condition else 'FAIL'}] {name}{': ' + detail if detail and not condition else ''}")
        if not condition:
            raise CanaryFailure(f"{name}: {detail}")

    def agent_args(self) -> list[str]:
        return ["-g", self.opts.resource_group, "--name", self.opts.agent_name, *self.common]

    def child_args(self) -> list[str]:
        return ["-g", self.opts.resource_group, "--agent-name", self.opts.agent_name, *self.common]

    # --- scenarios ---------------------------------------------------------

    def resource_group_exists(self) -> bool:
        out = self.az("group", "exists", "--name", self.opts.resource_group, *self.common, capture=False)
        return out.stdout.strip().lower() == "true"

    def create_resource_group(self) -> None:
        o = self.opts
        created_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.az("group", "create", "--name", o.resource_group, "--location", o.location,
                "--tags", PURPOSE_TAG, f"{RUN_TAG}={self.run_id}", f"{CREATED_TAG}={created_at}",
                *self.common, "-o", "none")
        self.created_rg = True

    def agent_lifecycle(self) -> str:
        o = self.opts
        self.create_resource_group()
        created = self.json("sre", "agent", "create", *self.agent_args(), "--location", o.location,
                            long_running=True)
        agent_id = created.get("id", "")
        expected_suffix = f"/resourceGroups/{o.resource_group}/providers/Microsoft.App/agents/{o.agent_name}".lower()
        self.check("agent create returns the expected resource id",
                   agent_id.lower().endswith(expected_suffix), agent_id)

        shown = self.json("sre", "agent", "show", *self.agent_args())
        self.check("agent show reports provisioningState Succeeded",
                   shown["properties"].get("provisioningState") == "Succeeded",
                   str(shown["properties"].get("provisioningState")))

        listed = self.json("sre", "agent", "list", "-g", o.resource_group, *self.common)
        self.check("agent list contains the new agent",
                   any(a.get("id", "").lower() == agent_id.lower() for a in listed))

        self.az("sre", "agent", "update", *self.agent_args(), "--tags", "canary=updated", "-o", "none")
        shown = self.json("sre", "agent", "show", *self.agent_args())
        self.check("agent update persists (fresh show)", (shown.get("tags") or {}).get("canary") == "updated",
                   json.dumps(shown.get("tags")))

        self.az("sre", "agent", "stop", *self.agent_args(), "-o", "none", long_running=True)
        state = self.json("sre", "agent", "show", *self.agent_args())["properties"]
        self.check("agent stop is reflected in show",
                   "stop" in f"{state.get('runningState')} {state.get('powerState')}".lower(),
                   f"runningState={state.get('runningState')} powerState={state.get('powerState')}")
        self.az("sre", "agent", "start", *self.agent_args(), "-o", "none", long_running=True)
        state = self.json("sre", "agent", "show", *self.agent_args())["properties"]
        self.check("agent start is reflected in show",
                   "stop" not in f"{state.get('runningState')} {state.get('powerState')}".lower(),
                   f"runningState={state.get('runningState')} powerState={state.get('powerState')}")
        return agent_id

    def content_round_trip(self) -> None:
        written = {"prompt": "Live canary instruction. Safe to delete."}
        self.az("sre", "instructions", "create", *self.child_args(), "--name", "canary",
                "--value", json.dumps(written), "-o", "none")
        shown = _extension_value(self.json("sre", "instructions", "show", *self.child_args(), "--name", "canary"))
        self.check("instructions show returns the written prompt", shown == written, json.dumps(shown))
        names = [i.get("name") for i in self.json("sre", "instructions", "list", *self.child_args())]
        self.check("instructions list contains the new snippet", "canary" in names, str(names))
        dup = self.az("sre", "instructions", "create", *self.child_args(), "--name", "canary",
                      "--value", json.dumps({"prompt": "Duplicate canary instruction."}), expect_ok=False)
        self.check("duplicate instructions create is rejected without --overwrite",
                   dup.returncode != 0 and re.search(r"already exists|--overwrite", dup.stderr) is not None,
                   f"exit {dup.returncode}: {dup.stderr.strip()[-300:]}")
        shown = _extension_value(self.json("sre", "instructions", "show", *self.child_args(), "--name", "canary"))
        self.check("rejected duplicate leaves the original prompt unchanged", shown == written, json.dumps(shown))
        self.az("sre", "instructions", "delete", *self.child_args(), "--name", "canary", "--yes", "-o", "none")
        names = [i.get("name") for i in self.json("sre", "instructions", "list", *self.child_args())]
        self.check("instructions delete removes the snippet", "canary" not in names, str(names))

        with tempfile.TemporaryDirectory() as work:
            note = Path(work, "canary.md")
            note.write_text("# Live canary\nSafe to delete.\n", encoding="utf-8")
            self.az("sre", "knowledge", "create", *self.child_args(), "--name", "canary-text", "--type", "text",
                    "--file-path", str(note), "-o", "none")
        source = self.json("sre", "knowledge", "show", *self.child_args(), "--name", "canary-text")
        kind = (source.get("properties") or {}).get("dataConnectorType")
        self.check("knowledge show returns the new text source",
                   source.get("name") == "canary-text" and kind == "KnowledgeText",
                   f"name={source.get('name')} dataConnectorType={kind}")
        names = [k.get("name") for k in self.json("sre", "knowledge", "list", *self.child_args())]
        self.check("knowledge list contains the new source", "canary-text" in names, str(names))
        self.az("sre", "knowledge", "delete", *self.child_args(), "--name", "canary-text", "--yes", "-o", "none")
        names = [k.get("name") for k in self.json("sre", "knowledge", "list", *self.child_args())]
        self.check("knowledge delete removes the source", "canary-text" not in names, str(names))

    def rbac(self, agent_id: str) -> None:
        def assignments(principal: str) -> list[dict]:
            listed = self.json("role", "assignment", "list", "--scope", agent_id,
                               "--fill-principal-name", "false", *self.common) or []
            return [a for a in listed if str(a.get("principalId", "")).lower() == principal.lower()]

        granted = self.json("sre", "access", "grant", *self.agent_args(), "--role", "reader", "--assignee-me")
        principal = (granted or {}).get("principalId") or ""
        self.check("access grant --assignee-me returns a principalId", bool(principal), json.dumps(granted))
        after_grant = assignments(principal)
        readers = [a for a in after_grant if a.get("roleDefinitionName") == "SRE Agent Reader"
                   and a.get("scope", "").lower() == agent_id.lower()]
        self.check("access grant adds exactly one SRE Agent Reader assignment at the agent scope",
                   len(readers) == 1 and readers[0].get("id", "").lower() == str(granted.get("id", "")).lower(),
                   json.dumps([{k: a.get(k) for k in ("roleDefinitionName", "scope")} for a in after_grant]))

        self.az("sre", "access", "revoke", *self.agent_args(), "--role", "reader", "--assignee-me", "-o", "none")
        remaining = {a["id"] for a in assignments(principal)}
        self.check("access revoke removes only the granted assignment",
                   remaining == {a["id"] for a in after_grant} - {readers[0]["id"]},
                   f"before={len(after_grant)} after={len(remaining)}")

    def negatives(self) -> None:
        missing = self.az("sre", "agent", "show", "-g", self.opts.resource_group, "--name",
                          f"{self.opts.agent_name}-missing", *self.common, expect_ok=False)
        self.check("show of a missing agent fails with not-found",
                   missing.returncode != 0 and re.search(r"not ?found", missing.stderr, re.I) is not None,
                   missing.stderr.strip()[-300:])
        bogus = self.az("sre", "agent", "show", *self.agent_args(), "--definitely-not-an-argument",
                        expect_ok=False)
        self.check("unknown argument is rejected", bogus.returncode != 0
                   and "unrecognized arguments" in bogus.stderr)

    def secret_safety(self) -> None:
        self.az("sre", "agent", "show", *self.agent_args(), "--debug")
        token = self.az("account", "get-access-token", *self.common, "--query", "accessToken", "-o", "tsv",
                        capture=False).stdout.strip()
        leaked = [i for i, text in enumerate(self.outputs)
                  if (token and token in text) or re.search(r"Bearer\s+eyJ", text)]
        self.check("no access token in any captured output (normal, error or --debug)", not leaked,
                   f"{len(leaked)} output(s) contained a token")

    def delete(self) -> None:
        self.az("sre", "agent", "delete", *self.agent_args(), "--yes", long_running=True)
        gone = self.az("sre", "agent", "show", *self.agent_args(), expect_ok=False)
        self.check("agent delete leaves no agent behind", gone.returncode != 0
                   and re.search(r"not ?found", gone.stderr, re.I) is not None, gone.stderr.strip()[-300:])

    def cleanup(self) -> None:
        rg = self.opts.resource_group
        if not self.created_rg:
            print(f"Resource group {rg} was not created by this run; not deleting it.")
            return
        if self.opts.keep:
            print(f"--keep given: leaving resource group {rg}")
            return
        try:
            tags = self.json("group", "show", "--name", rg, "--query", "tags", *self.common) or {}
            if tags.get(RUN_TAG) != self.run_id:
                print(f"Resource group {rg} does not carry this run's {RUN_TAG} tag; not deleting it.")
                self.steps.append({"step": "resource group deleted", "passed": False,
                                   "detail": f"{RUN_TAG} tag mismatch"})
                return
            result = self.az("group", "delete", "--name", rg, "--yes", *self.common,
                             expect_ok=False, capture=False, long_running=True)
            self.steps.append({"step": "resource group deleted", "passed": result.returncode == 0})
        except (CanaryFailure, ValueError, AttributeError) as exc:
            print(f"Cleanup of {rg} failed: {exc}", file=sys.stderr)
            self.steps.append({"step": "resource group deleted", "passed": False, "detail": str(exc)[:300]})


def _text(value) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else value


def _extension_value(shown):
    """The decoded ``properties.value`` of an extension show result."""
    value = ((shown or {}).get("properties") or {}).get("value")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--location", default=os.environ.get("AZURE_LOCATION", "eastus2"))
    parser.add_argument("--resource-group", default=f"rg-sre-canary-{suffix}")
    parser.add_argument("--agent-name", default=f"sre-canary-{suffix}")
    parser.add_argument("--results-dir", type=Path, default=Path("live-canary-results"))
    parser.add_argument("--skip-rbac", action="store_true",
                        help="Skip the grant/revoke scenario (identity can't assign the SRE Agent roles).")
    parser.add_argument("--keep", action="store_true",
                        help="Do not delete the resource group this run created.")
    opts = parser.parse_args()
    if not AZ:
        print("ERROR: az is required on PATH", file=sys.stderr)
        return 2
    if not opts.subscription:
        print("ERROR: --subscription or AZURE_SUBSCRIPTION_ID is required", file=sys.stderr)
        return 2

    canary = Canary(opts)
    try:
        if canary.resource_group_exists():
            print(f"ERROR: resource group {opts.resource_group} already exists. The canary only uses a "
                  "group it creates; pass a new --resource-group name.", file=sys.stderr)
            return 2
    except CanaryFailure as exc:
        print(f"ERROR: could not check resource group {opts.resource_group}: {exc}", file=sys.stderr)
        return 2

    error = None
    completed = False
    try:
        agent_id = canary.agent_lifecycle()
        canary.content_round_trip()
        if not opts.skip_rbac:
            canary.rbac(agent_id)
        canary.negatives()
        canary.secret_safety()
        canary.delete()
        completed = True
    except CanaryFailure as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"\nCANARY FAILED: {error}", file=sys.stderr)
    except Exception as exc:  # pylint: disable=broad-except
        error = f"{type(exc).__name__}: {exc}"
        traceback.print_exc()
        print(f"\nCANARY CRASHED: {error}", file=sys.stderr)
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        canary.cleanup()
        opts.results_dir.mkdir(parents=True, exist_ok=True)
        evidence = {
            "resourceGroup": opts.resource_group,
            "agentName": opts.agent_name,
            "location": opts.location,
            "passed": completed and error is None and all(s["passed"] for s in canary.steps),
            "error": error,
            "steps": canary.steps,
        }
        (opts.results_dir / "live-canary.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    passed = sum(s["passed"] for s in canary.steps)
    print(f"\n{passed}/{len(canary.steps)} checks passed. Evidence: {opts.results_dir / 'live-canary.json'}")
    return 0 if completed and error is None and passed == len(canary.steps) else 1


if __name__ == "__main__":
    sys.exit(main())

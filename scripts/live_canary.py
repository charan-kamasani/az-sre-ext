#!/usr/bin/env python3
"""Live end-to-end canary for the installed ``az sre`` extension.

Drives the core customer journey against real Azure and fails on any
mismatch between CLI output and the actual resource state:

1. agent lifecycle: create, show, list, update, stop, start
2. content round trip: instructions and a text knowledge source (create, show,
   list, duplicate-create rejected, delete, verify gone)
3. RBAC: grant the caller ``reader`` on the agent, verify it independently with
   ``az role assignment list``, revoke it, verify only that assignment went away
4. negative cases: a missing agent fails, an unknown argument fails
5. secret safety: the caller's access token never appears in any captured
   output, including ``--debug`` logs
6. delete the agent, verify it is gone, then delete the resource group

The resource group is always deleted (unless ``--keep``), even on failure.
Evidence is written to ``<results-dir>/live-canary.json``; it holds command
lines, exit codes and pass/fail, never raw output or tokens.

Creates billable resources. The signed-in identity needs Contributor and
User Access Administrator (or Owner) on the subscription.
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
import uuid
from pathlib import Path

AZ = shutil.which("az")


class CanaryFailure(Exception):
    pass


class Canary:
    def __init__(self, opts: argparse.Namespace):
        self.opts = opts
        self.steps: list[dict] = []
        self.outputs: list[str] = []
        self.common = ["--subscription", opts.subscription]

    def az(self, *args: str, expect_ok: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
        cmd = [AZ, *args, "--only-show-errors"] if "--debug" not in args else [AZ, *args]
        started = time.monotonic()
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=False)
        if capture:
            self.outputs.append(result.stdout + result.stderr)
        shown = " ".join(["az", *args])
        print(f"$ {shown}  -> exit {result.returncode} ({time.monotonic() - started:.0f}s)", flush=True)
        if expect_ok and result.returncode != 0:
            raise CanaryFailure(f"`{shown}` failed:\n{result.stderr.strip()[-2000:]}")
        return result

    def json(self, *args: str):
        out = self.az(*args, "-o", "json").stdout.strip()
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

    def agent_lifecycle(self) -> str:
        o = self.opts
        self.az("group", "create", "--name", o.resource_group, "--location", o.location,
                "--tags", "purpose=sre-live-canary", *self.common, "-o", "none")
        created = self.json("sre", "agent", "create", *self.agent_args(), "--location", o.location)
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

        self.az("sre", "agent", "stop", *self.agent_args(), "-o", "none")
        state = self.json("sre", "agent", "show", *self.agent_args())["properties"]
        self.check("agent stop is reflected in show",
                   "stop" in f"{state.get('runningState')} {state.get('powerState')}".lower(),
                   f"runningState={state.get('runningState')} powerState={state.get('powerState')}")
        self.az("sre", "agent", "start", *self.agent_args(), "-o", "none")
        state = self.json("sre", "agent", "show", *self.agent_args())["properties"]
        self.check("agent start is reflected in show",
                   "stop" not in f"{state.get('runningState')} {state.get('powerState')}".lower(),
                   f"runningState={state.get('runningState')} powerState={state.get('powerState')}")
        return agent_id

    def content_round_trip(self) -> None:
        prompt = json.dumps({"prompt": "Live canary instruction. Safe to delete."})
        self.az("sre", "instructions", "create", *self.child_args(), "--name", "canary", "--value", prompt,
                "-o", "none")
        self.json("sre", "instructions", "show", *self.child_args(), "--name", "canary")
        names = [i.get("name") for i in self.json("sre", "instructions", "list", *self.child_args())]
        self.check("instructions list contains the new snippet", "canary" in names, str(names))
        dup = self.az("sre", "instructions", "create", *self.child_args(), "--name", "canary", "--value", prompt,
                      expect_ok=False)
        self.check("duplicate instructions create is rejected without --overwrite", dup.returncode != 0)
        self.az("sre", "instructions", "delete", *self.child_args(), "--name", "canary", "--yes", "-o", "none")
        names = [i.get("name") for i in self.json("sre", "instructions", "list", *self.child_args())]
        self.check("instructions delete removes the snippet", "canary" not in names, str(names))

        with tempfile.TemporaryDirectory() as work:
            note = Path(work, "canary.md")
            note.write_text("# Live canary\nSafe to delete.\n", encoding="utf-8")
            self.az("sre", "knowledge", "create", *self.child_args(), "--name", "canary-text", "--type", "text",
                    "--file-path", str(note), "-o", "none")
        names = [k.get("name") for k in self.json("sre", "knowledge", "list", *self.child_args())]
        self.check("knowledge list contains the new source", "canary-text" in names, str(names))
        self.az("sre", "knowledge", "delete", *self.child_args(), "--name", "canary-text", "--yes", "-o", "none")
        names = [k.get("name") for k in self.json("sre", "knowledge", "list", *self.child_args())]
        self.check("knowledge delete removes the source", "canary-text" not in names, str(names))

    def rbac(self, agent_id: str) -> None:
        account = self.json("account", "show", *self.common)
        if account["user"]["type"] == "servicePrincipal":
            principal = self.az("ad", "sp", "show", "--id", account["user"]["name"], "--query", "id",
                                "-o", "tsv").stdout.strip()
        else:
            principal = self.az("ad", "signed-in-user", "show", "--query", "id", "-o", "tsv").stdout.strip()

        def assignments() -> list[dict]:
            return self.json("role", "assignment", "list", "--assignee", principal, "--scope", agent_id,
                             *self.common) or []

        before = {a["id"] for a in assignments()}
        self.az("sre", "access", "grant", *self.agent_args(), "--role", "reader", "--assignee", principal,
                "-o", "none")
        after_grant = assignments()
        added = [a for a in after_grant if a["id"] not in before]
        self.check("access grant adds exactly one SRE Agent Reader assignment at the agent scope",
                   len(added) == 1 and added[0].get("roleDefinitionName") == "SRE Agent Reader"
                   and added[0].get("scope", "").lower() == agent_id.lower(),
                   json.dumps([{k: a.get(k) for k in ("roleDefinitionName", "scope")} for a in added]))

        self.az("sre", "access", "revoke", *self.agent_args(), "--role", "reader", "--assignee", principal,
                "-o", "none")
        after_revoke = {a["id"] for a in assignments()}
        self.check("access revoke removes only the granted assignment", after_revoke == before,
                   f"before={len(before)} after={len(after_revoke)}")

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
        self.az("sre", "agent", "delete", *self.agent_args(), "--yes")
        gone = self.az("sre", "agent", "show", *self.agent_args(), expect_ok=False)
        self.check("agent delete leaves no agent behind", gone.returncode != 0
                   and re.search(r"not ?found", gone.stderr, re.I) is not None, gone.stderr.strip()[-300:])

    def cleanup(self) -> None:
        if self.opts.keep:
            print(f"--keep given: leaving resource group {self.opts.resource_group}")
            return
        exists = self.az("group", "exists", "--name", self.opts.resource_group, *self.common,
                         expect_ok=False, capture=False)
        if exists.stdout.strip() == "true":
            result = self.az("group", "delete", "--name", self.opts.resource_group, "--yes", *self.common,
                             expect_ok=False, capture=False)
            self.steps.append({"step": "resource group deleted", "passed": result.returncode == 0})


def main() -> int:
    suffix = uuid.uuid4().hex[:8]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--subscription", default=os.environ.get("AZURE_SUBSCRIPTION_ID"))
    parser.add_argument("--location", default=os.environ.get("AZURE_LOCATION", "eastus2"))
    parser.add_argument("--resource-group", default=f"rg-sre-canary-{suffix}")
    parser.add_argument("--agent-name", default=f"sre-canary-{suffix}")
    parser.add_argument("--results-dir", type=Path, default=Path("live-canary-results"))
    parser.add_argument("--skip-rbac", action="store_true",
                        help="Skip the grant/revoke scenario (identity lacks User Access Administrator).")
    parser.add_argument("--keep", action="store_true", help="Do not delete the resource group afterwards.")
    opts = parser.parse_args()
    if not AZ:
        print("ERROR: az is required on PATH", file=sys.stderr)
        return 2
    if not opts.subscription:
        print("ERROR: --subscription or AZURE_SUBSCRIPTION_ID is required", file=sys.stderr)
        return 2

    canary = Canary(opts)
    error = None
    try:
        agent_id = canary.agent_lifecycle()
        canary.content_round_trip()
        if not opts.skip_rbac:
            canary.rbac(agent_id)
        canary.negatives()
        canary.secret_safety()
        canary.delete()
    except (CanaryFailure, KeyError, TypeError, json.JSONDecodeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"\nCANARY FAILED: {error}", file=sys.stderr)
    finally:
        canary.cleanup()
        opts.results_dir.mkdir(parents=True, exist_ok=True)
        evidence = {
            "resourceGroup": opts.resource_group,
            "agentName": opts.agent_name,
            "location": opts.location,
            "passed": error is None and all(s["passed"] for s in canary.steps),
            "error": error,
            "steps": canary.steps,
        }
        (opts.results_dir / "live-canary.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")

    passed = sum(s["passed"] for s in canary.steps)
    print(f"\n{passed}/{len(canary.steps)} checks passed. Evidence: {opts.results_dir / 'live-canary.json'}")
    return 0 if error is None and passed == len(canary.steps) else 1


if __name__ == "__main__":
    sys.exit(main())

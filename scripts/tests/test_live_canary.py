import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import live_canary

RG = "rg-test"
AGENT_ID = f"/subscriptions/s/resourceGroups/{RG}/providers/Microsoft.App/agents/a"


class FakeAz:
    """Minimal stand-in for `az`. Handlers map a command prefix to a result."""

    def __init__(self, overrides=None):
        self.calls = []
        self.run_tag = None
        self.overrides = overrides or {}

    def __call__(self, cmd, **kwargs):
        args = [a for a in cmd[1:] if a != "--only-show-errors"]
        self.calls.append(args)
        for prefix, handler in self.overrides.items():
            if " ".join(args).startswith(prefix):
                return handler(args, kwargs)
        return self.default(args)

    def default(self, args):
        joined = " ".join(args)
        if joined.startswith("group exists"):
            return _ok("false")
        if joined.startswith("group create"):
            self.run_tag = next(a.split("=", 1)[1] for a in args if a.startswith("sre-canary-run="))
            return _ok("")
        if joined.startswith("group show"):
            return _ok(json.dumps({"sre-canary-run": self.run_tag}))
        return _ok("")


def _ok(stdout):
    return subprocess.CompletedProcess([], 0, stdout, "")


def _fail(stderr):
    return subprocess.CompletedProcess([], 1, "", stderr)


def _run_main(fake, seen=None):
    with tempfile.TemporaryDirectory() as results, \
            mock.patch.object(live_canary, "AZ", "az"), \
            mock.patch.object(live_canary.subprocess, "run", side_effect=fake), \
            mock.patch.object(sys, "argv", ["live_canary.py", "--subscription", "s", "--resource-group", RG,
                                            "--results-dir", results]), \
            mock.patch("sys.stdout"), mock.patch("sys.stderr"):
        try:
            code = live_canary.main()
        finally:
            evidence_path = Path(results, "live-canary.json")
            evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else None
    return code, evidence


def _group_deletes(fake):
    return [c for c in fake.calls if c[:2] == ["group", "delete"]]


class LiveCanaryTests(unittest.TestCase):
    def test_existing_resource_group_is_refused(self):
        fake = FakeAz({"group exists": lambda a, k: _ok("true")})
        code, evidence = _run_main(fake)
        self.assertEqual(code, 2)
        self.assertIsNone(evidence)
        self.assertEqual([c[:2] for c in fake.calls], [["group", "exists"]])

    def test_group_not_created_by_run_is_not_deleted(self):
        fake = FakeAz({"group create": lambda a, k: _fail("InvalidResourceGroupLocation")})
        code, evidence = _run_main(fake)
        self.assertEqual(code, 1)
        self.assertFalse(evidence["passed"])
        self.assertEqual(_group_deletes(fake), [])

    def test_group_with_other_run_tag_is_not_deleted(self):
        fake = FakeAz({"sre agent create": lambda a, k: _fail("boom"),
                       "group show": lambda a, k: _ok(json.dumps({"sre-canary-run": "someone-else"}))})
        code, _ = _run_main(fake)
        self.assertEqual(code, 1)
        self.assertEqual(_group_deletes(fake), [])

    def test_created_group_is_deleted_after_failure(self):
        fake = FakeAz({"sre agent create": lambda a, k: _fail("boom")})
        code, evidence = _run_main(fake)
        self.assertEqual(code, 1)
        self.assertEqual(len(_group_deletes(fake)), 1)
        self.assertIn("boom", evidence["error"])

    def test_timeout_becomes_failure(self):
        def hang(args, kwargs):
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])

        fake = FakeAz({"sre agent create": hang})
        code, evidence = _run_main(fake)
        self.assertEqual(code, 1)
        self.assertIn(f"timed out after {live_canary.TIMEOUT_LONG}s", evidence["error"])
        self.assertEqual(len(_group_deletes(fake)), 1)

    def test_unexpected_exception_reports_not_passed(self):
        # agent create returns an unexpected shape -> AttributeError on .get
        fake = FakeAz({"sre agent create": lambda a, k: _ok('["not-a-dict"]')})
        code, evidence = _run_main(fake)
        self.assertEqual(code, 1)
        self.assertFalse(evidence["passed"])
        self.assertIn("AttributeError", evidence["error"])

    def test_interrupt_reports_not_passed(self):
        def interrupt(args, kwargs):
            raise KeyboardInterrupt

        fake = FakeAz({"sre agent create": interrupt})
        with self.assertRaises(KeyboardInterrupt):
            _run_main(fake)


class DuplicateCheckTests(unittest.TestCase):
    def _canary(self, fake):
        opts = mock.Mock(subscription="s", resource_group=RG, agent_name="a")
        canary = live_canary.Canary(opts)
        patches = [mock.patch.object(live_canary, "AZ", "az"),
                   mock.patch.object(live_canary.subprocess, "run", side_effect=fake),
                   mock.patch("sys.stdout")]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return canary

    def _instructions(self, duplicate_result):
        written = json.dumps({"properties": {"value": {"prompt": "Live canary instruction. Safe to delete."}}})
        state = {"created": False}

        def create(args, kwargs):
            if state["created"]:
                return duplicate_result
            state["created"] = True
            return _ok("")

        return FakeAz({"sre instructions create": create,
                       "sre instructions show": lambda a, k: _ok(written),
                       "sre instructions list": lambda a, k: _ok(json.dumps([{"name": "canary"}]))})

    def test_unrelated_error_does_not_pass_duplicate_check(self):
        canary = self._canary(self._instructions(_fail("AADSTS700024: client assertion expired")))
        with self.assertRaisesRegex(live_canary.CanaryFailure, "duplicate instructions create"):
            canary.content_round_trip()

    def test_already_exists_error_passes_duplicate_check(self):
        canary = self._canary(self._instructions(
            _fail("An extension named 'canary' of type 'commonPrompts' already exists on agent 'a'. "
                  "Pass --overwrite to replace it intentionally, or choose another name.")))
        with self.assertRaisesRegex(live_canary.CanaryFailure, "instructions delete removes"):
            canary.content_round_trip()
        names = [s["step"] for s in canary.steps if s["passed"]]
        self.assertIn("duplicate instructions create is rejected without --overwrite", names)
        self.assertIn("rejected duplicate leaves the original prompt unchanged", names)


if __name__ == "__main__":
    unittest.main()

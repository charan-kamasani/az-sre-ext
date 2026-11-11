"""Response-plan commands through the real Azure CLI, with Azure faked at the HTTP layer.

The fake keeps the agent's incident filters (behind ARM, and behind the agent's own API on
the direct route) and its incident handlers (the plan's instructions) in memory, so a test
can check what a command wrote or deleted, and in which order. Requests are faked at
requests.adapters.HTTPAdapter.send, which both send_raw_request and the AAZ pipeline reach.
"""

import base64
import copy
import io
import json
import logging
import os
import re
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

from requests import Response

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
AGENT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
ENDPOINT_HOST = "myagent--1a2b.cafe.swedencentral.azuresre.ai"
# Unset filter fields that ARM echoes as null.
ARM_NULL_ECHO = ("titleContains", "titleNotContains", "incidentTypes", "owningTeamIds", "handlingAgents",
                 "impactedService", "alertId", "priorities")
REASONS = {200: "OK", 204: "No Content", 400: "Bad Request", 403: "Forbidden", 404: "Not Found",
           500: "Internal Server Error"}


def _arm_error(code, message):
    return {"error": {"code": code, "message": message}}


def _has_null(value):
    if isinstance(value, dict):
        return any(v is None or _has_null(v) for v in value.values())
    return isinstance(value, list) and any(v is None or _has_null(v) for v in value)


AUTHORIZATION_FAILED = _arm_error(
    "AuthorizationFailed",
    "The client 'someone@contoso.com' does not have authorization to perform action "
    "'Microsoft.App/agents/incidentFilters/delete' over scope 'myagent/incidentFilters/p'.")


class _FakeAzure:
    """ARM's view of the agent and the agent's own API, with injectable failures."""

    def __init__(self):
        self.filters = {}
        self.handlers = {}
        self.subagents = {"responder"}
        self.incident_platform = "AzMonitor"
        self.requests = []
        self.failures = []
        self.unexpected = []

    def fail(self, method, api, kind, status, body=None, name=None, content_type="application/json"):
        """Answer matching requests (name None matches any) with this response from now on."""
        self.failures.append((method, api, kind, name, status, body, content_type))

    def writes(self):
        return [entry[:4] for entry in self.requests if entry[0] in ("PUT", "DELETE")]

    def send(self, request):
        url = urlsplit(request.url)
        body = json.loads(request.body) if request.body else None
        if url.netloc == "management.azure.com":
            api = "arm"
            if url.path == AGENT_ID:
                return self._reply(request, 200, {"id": AGENT_ID, "name": "myagent", "properties": {
                    "agentEndpoint": f"https://{ENDPOINT_HOST}"}})
            match = re.fullmatch(
                re.escape(AGENT_ID) + r"/(?P<kind>incidentFilters|subagents)(?:/(?P<name>[^/]+))?", url.path)
        elif url.netloc == ENDPOINT_HOST:
            api = "agent"
            match = re.fullmatch(
                r"/api/v2/(?:incidentManagement|extendedAgent)/(?P<kind>incidentFilters|incidentHandlers)"
                r"(?:/(?P<name>[^/]+))?", url.path)
            if match and (match["kind"] == "incidentFilters") != ("/incidentManagement/" in url.path):
                match = None
        else:
            match = None
        if match is None:
            self.unexpected.append(f"{request.method} {request.url}")
            raise AssertionError(f"Unexpected request: {request.method} {request.url}")
        kind, name = match["kind"], unquote(match["name"]) if match["name"] else None
        failure = next((f for f in self.failures if f[:3] == (request.method, api, kind)
                        and f[3] in (None, name)), None)
        status, payload, content_type = (failure[4], failure[5], failure[6]) if failure else \
            self._handle(request.method, api, kind, name, body)
        self.requests.append((request.method, api, kind, name, status))
        return self._reply(request, status, payload, content_type)

    def _handle(self, method, api, kind, name, body):
        if kind == "subagents":
            return (200, {"name": name}, None) if method == "GET" and name in self.subagents else \
                (404, _arm_error("NotFound", "Not found"), None)
        store = self.filters if kind == "incidentFilters" else self.handlers
        if name is None:
            if kind == "incidentHandlers":
                return 200, copy.deepcopy(list(self.handlers.values())), None
            return 200, {"value": [self._filter_view(api, n) for n in self.filters]}, None
        if method == "GET":
            if name not in store:
                return 404, _arm_error("NotFound", f"'{name}' not found"), None
            return 200, self._filter_view(api, name) if kind == "incidentFilters" else store[name], None
        if method == "DELETE":
            if name not in store:
                return (200, None, None) if api == "arm" else (404, None, None)
            del store[name]
            return (200 if api == "arm" else 204), None, None
        if kind == "incidentHandlers":
            store[name] = copy.deepcopy(body)
            return 200, body, None
        value = json.loads(base64.b64decode(body["properties"]["value"])) if api == "arm" else body["properties"]
        if _has_null(value):
            return 400, _arm_error("BadRequest", "The extension configuration is invalid."), None
        store[name] = copy.deepcopy(value)
        return 200, self._filter_view(api, name), None

    def _filter_view(self, api, name):
        value = copy.deepcopy(self.filters[name])
        if api == "agent":
            return {"name": name, "type": "IncidentFilter", "properties": value}
        echoed = {**{field: None for field in ARM_NULL_ECHO}, **value}
        encoded = base64.b64encode(json.dumps(echoed).encode()).decode()
        return {"id": f"{AGENT_ID}/incidentFilters/{name}", "name": name,
                "type": "microsoft.app/agents/incidentfilters", "properties": {"value": encoded}}

    @staticmethod
    def _reply(request, status, payload, content_type=None):
        response = Response()
        response.status_code = status
        response.reason = REASONS[status]
        if payload is None:
            content = b""
        elif isinstance(payload, str):
            content = payload.encode()
        else:
            content = json.dumps(payload).encode()
        response._content = content
        response.raw = io.BytesIO(content)
        response.encoding = "utf-8"
        response.headers["Content-Type"] = content_type or "application/json"
        response.url = request.url
        response.request = request
        return response


class _ResponsePlanCliTests:
    """Scenarios run on the route set by ROUTE (AZSRE_EXTENSION_ROUTE)."""

    ROUTE = None

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "no",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
            "AZSRE_EXTENSION_ROUTE": self.ROUTE,
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        stack.enter_context(patch(
            "azure.cli.core._profile.Profile.get_raw_token",
            return_value=(("Bearer", "fake-token", {}), SUBSCRIPTION, "tenant")))
        self.azure = _FakeAzure()
        stack.enter_context(patch(
            "requests.adapters.HTTPAdapter.send", lambda adapter, request, **kwargs: self.azure.send(request)))
        stack.enter_context(patch(
            "socket.socket.connect", side_effect=AssertionError("Response-plan CLI tests must not use the network.")))
        stack.enter_context(patch("azext_sre.custom._cli_invoke", self._nested_command))

    def tearDown(self):
        # Advisory checks swallow errors, so an unmodeled request could otherwise go unnoticed.
        self.assertEqual(self.azure.unexpected, [], "A command made a request the fake doesn't model.")

    def _nested_command(self, cli_ctx, *args, **kwargs):
        del cli_ctx, kwargs
        if args[:3] != ("sre", "agent", "show"):
            self.azure.unexpected.append(f"az {' '.join(args)}")
            raise AssertionError(f"Unexpected nested command: {args}")
        platform = self.azure.incident_platform
        return {"id": AGENT_ID, "name": "myagent", "properties": {
            "incidentManagementConfiguration": {"type": platform} if platform else None}}

    def _az(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.WARNING)
        with redirect_stdout(output), redirect_stderr(errors), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            try:
                code = get_default_cli().invoke(
                    ["sre", "response-plan", *arguments, "-g", "rg", "--agent-name", "myagent"], out_file=output)
            except SystemExit as ex:
                code = ex.code
        return code, output.getvalue(), errors.getvalue()

    @property
    def filter_api(self):
        return "arm" if self.ROUTE == "arm" else "agent"

    def _plan(self, name, handlers=(), **properties):
        self.azure.filters[name] = {"incidentPlatform": "AzMonitor", "handlingAgent": "responder",
                                    "agentMode": "review", "isEnabled": True, **properties}
        for handler in handlers:
            self.azure.handlers[handler["id"]] = {"incidentFilterId": name, **handler}

    def test_delete_removes_the_match_rules_before_the_instructions(self):
        self._plan("p", handlers=[{"id": "p", "customInstructions": "Check logs"}])
        self.azure.fail("DELETE", "agent", "incidentHandlers", 403, {"error": "Forbidden: Access denied by PDP"})
        code, _, errors = self._az("delete", "-n", "p", "--yes")
        self.assertNotEqual(code, 0)
        self.assertIn("was deleted, but deleting its instructions 'p' failed", errors)
        self.assertEqual([write[:3] for write in self.azure.writes()], [
            ("DELETE", self.filter_api, "incidentFilters"), ("DELETE", "agent", "incidentHandlers")])
        self.assertNotIn("p", self.azure.filters)
        self.assertIn("p", self.azure.handlers)

        self.azure.failures.clear()
        code, _, errors = self._az("delete", "-n", "p", "--yes")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.azure.handlers, {})

    def test_failed_match_rule_delete_keeps_the_instructions(self):
        self._plan("p", handlers=[{"id": "p", "customInstructions": "Check logs"}])
        self.azure.fail("DELETE", self.filter_api, "incidentFilters", 500,
                        _arm_error("InternalServerError", "Something went wrong."))
        code, _, errors = self._az("delete", "-n", "p", "--yes")
        self.assertNotEqual(code, 0)
        self.assertIn("Something went wrong.", errors)
        self.assertEqual(self.azure.handlers.get("p", {}).get("customInstructions"), "Check logs")
        self.assertIn("p", self.azure.filters)

    def test_create_without_instructions_warns_when_the_name_already_has_some(self):
        # 'x' was left behind by a delete that removed the plan but not its instructions.
        self.azure.handlers.update({
            "x": {"id": "x", "incidentFilterId": "x", "customInstructions": "Left over"},
            "a": {"id": "a", "incidentFilterId": "a", "customInstructions": "Plan a's own"}})
        warning = "uses instructions that already existed for that name"
        for name, warned in (("x", True), ("y", False)):
            with self.subTest(name=name):
                code, _, errors = self._az("create", "-n", name, "--platform", "AzMonitor", "--subagent", "responder")
                self.assertEqual(code, 0, errors)
                self.assertIn(name, self.azure.filters)
                self.assertEqual(warning in errors, warned, errors)

    def test_create_without_instructions_succeeds_when_instructions_cant_be_read(self):
        with self.subTest("agent without the handler API: warn and skip"):
            self.azure.fail("GET", "agent", "incidentHandlers", 200, "<!doctype html><html></html>",
                            content_type="text/html; charset=utf-8")
            code, _, errors = self._az("create", "-n", "p", "--platform", "AzMonitor", "--subagent", "responder")
            self.assertEqual(code, 0, errors)
            self.assertIn("doesn't expose response-plan instructions", errors)
            self.assertIn("p", self.azure.filters)
        with self.subTest("no role on the agent's own API"):
            self.azure.failures.clear()
            self.azure.fail("GET", "agent", "incidentHandlers", 403, {"error": "Forbidden: Access denied by PDP"})
            code, _, errors = self._az("create", "-n", "q", "--platform", "AzMonitor", "--subagent", "responder")
            self.assertEqual(code, 0, errors)
            self.assertIn("q", self.azure.filters)

    def test_create_refuses_another_plans_instructions_id(self):
        other = {"id": "b", "customInstructions": "Instructions of plan a"}
        self._plan("a", handlers=[other])
        for extra in ((), ("--overwrite",)):
            with self.subTest(extra=extra):
                code, _, errors = self._az(
                    "create", "-n", "b", "--platform", "AzMonitor", "--subagent", "responder",
                    "--instructions", "Plan b", *extra)
                self.assertNotEqual(code, 0)
                self.assertIn("already belong to response plan 'a'", errors)
                self.assertNotIn("--overwrite", errors)
        self.assertEqual(self.azure.writes(), [])
        self.assertNotIn("b", self.azure.filters)
        self.assertEqual(self.azure.handlers["b"], {"incidentFilterId": "a", **other})

    def test_instructions_on_an_agent_without_the_handler_api_save_nothing(self):
        self._plan("p")
        self.azure.fail("GET", "agent", "incidentHandlers", 200, "<!doctype html><html></html>",
                        content_type="text/html; charset=utf-8")
        for arguments in (
                ("update", "-n", "p", "--mode", "autonomous", "--instructions", "Check logs"),
                ("create", "-n", "q", "--platform", "AzMonitor", "--subagent", "responder",
                 "--instructions", "Check logs")):
            with self.subTest(command=arguments[0]):
                code, _, errors = self._az(*arguments)
                self.assertNotEqual(code, 0)
                self.assertIn("doesn't support response-plan instructions, so nothing was saved", errors)
                self.assertNotIn("Re-run", errors)
        self.assertEqual(self.azure.writes(), [])
        self.assertEqual(self.azure.filters["p"]["agentMode"], "review")
        self.assertNotIn("q", self.azure.filters)

    def test_update_clears_criteria_and_instructions_passed_empty(self):
        self._plan("p", handlers=[{"id": "p", "customInstructions": "Old", "incidentProcessingGuide": ["Step"],
                                   "tools": ["T1"]}],
                   titleContains="api", priorities=["Sev1"], impactedService="checkout",
                   azMonitorFilterSettings={"targetResourceType": "Microsoft.App/containerApps",
                                            "targetResource": "ca-api"})
        code, _, errors = self._az("update", "-n", "p", "--title-contains=", "--priority=",
                                   "--target-resource", "", "--instructions=")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.azure.filters["p"], {
            "incidentPlatform": "AzMonitor", "handlingAgent": "responder", "agentMode": "review",
            "isEnabled": True, "impactedService": "checkout",
            "azMonitorFilterSettings": {"targetResourceType": "Microsoft.App/containerApps"}})
        self.assertEqual(self.azure.handlers["p"], {
            "id": "p", "incidentFilterId": "p", "customInstructions": "", "incidentProcessingGuide": ["Step"],
            "tools": ["T1"]})

    def test_stored_nulls_and_numbers_do_not_block_changes(self):
        self._plan("az", azMonitorFilterSettings={"targetResourceType": "Microsoft.App/containerApps",
                                                  "targetResource": None})
        self._plan("icm", incidentPlatform="Icm", incidentTypes=["LiveSite"], incidentType="LiveSite",
                   owningTeamIds=[188963], priorities=[3, 4])
        with self.subTest("nested null"):
            code, _, errors = self._az("disable", "-n", "az")
            self.assertEqual(code, 0, errors)
            self.assertEqual(self.azure.filters["az"]["azMonitorFilterSettings"],
                             {"targetResourceType": "Microsoft.App/containerApps"})
            self.assertFalse(self.azure.filters["az"]["isEnabled"])

        with self.subTest("numeric IcM team IDs"):
            code, _, errors = self._az("update", "-n", "icm", "--mode", "autonomous")
            self.assertEqual(code, 0, errors)
            self.assertEqual(self.azure.filters["icm"]["agentMode"], "autonomous")
            self.assertEqual(self.azure.filters["icm"]["owningTeamIds"], [188963])
            self.assertEqual(self.azure.filters["icm"]["priorities"], [3, 4])

        with self.subTest("numeric priorities in the table"):
            code, output, errors = self._az("list", "-o", "table")
            self.assertEqual(code, 0, errors)
            self.assertRegex(output, r"icm\s+True\s+Icm\s+responder\s+3, 4\s")


class ResponsePlanArmRouteCliTests(_ResponsePlanCliTests, unittest.TestCase):
    ROUTE = "arm"

    def test_delete_falls_back_to_the_agent_api_only_when_it_deletes_the_plan(self):
        self._plan("p", handlers=[{"id": "p", "customInstructions": "Check logs"}])
        self.azure.fail("DELETE", "arm", "incidentFilters", 403, AUTHORIZATION_FAILED)
        self.azure.fail("DELETE", "agent", "incidentFilters", 404)
        code, _, errors = self._az("delete", "-n", "p", "--yes")
        self.assertNotEqual(code, 0)
        self.assertIn("Response plan 'p' was not deleted", errors)
        self.assertIn("does not have authorization to perform action", errors)
        self.assertIn("404", errors)
        self.assertIn("p", self.azure.filters)
        self.assertIn("p", self.azure.handlers)

        self.azure.failures.pop()
        code, _, errors = self._az("delete", "-n", "p", "--yes")
        self.assertEqual(code, 0, errors)
        self.assertIn("deleting it through the agent's own API", errors)
        self.assertEqual((self.azure.filters, self.azure.handlers), ({}, {}))

    def test_delete_does_not_work_around_policy_or_deny_assignments(self):
        self._plan("p", handlers=[{"id": "p", "customInstructions": "Check logs"}])
        for code_name, message in (
                ("RequestDisallowedByPolicy", "Resource 'p' was disallowed by policy 'Deny SRE plan deletion'."),
                ("DenyAssignmentAuthorizationFailed", "Access is denied because of the deny assignment "
                                                      "'Deployment stack deny assignment'.")):
            with self.subTest(code=code_name):
                self.azure.failures.clear()
                self.azure.requests.clear()
                self.azure.fail("DELETE", "arm", "incidentFilters", 403, _arm_error(code_name, message))
                code, _, errors = self._az("delete", "-n", "p", "--yes")
                self.assertNotEqual(code, 0)
                self.assertIn(message, errors)
                self.assertEqual(self.azure.writes(), [("DELETE", "arm", "incidentFilters", "p")])
        self.assertIn("p", self.azure.filters)
        self.assertIn("p", self.azure.handlers)

    def test_create_explains_only_rejections_of_the_plan(self):
        self.azure.incident_platform = None
        for status, body in ((403, _arm_error("AuthorizationFailed", "The client has no write access.")),
                             (500, _arm_error("InternalServerError", "Something went wrong."))):
            with self.subTest(status=status):
                self.azure.failures.clear()
                self.azure.fail("PUT", "arm", "incidentFilters", status, body)
                code, _, errors = self._az(
                    "create", "-n", "p", "--platform", "AzMonitor", "--subagent", "ghost")
                self.assertNotEqual(code, 0)
                self.assertIn(body["error"]["message"], errors)
                self.assertNotIn("no incident platform", errors)
                self.assertNotIn("doesn't exist", errors)

        generic = _arm_error("BadRequest", "The extension configuration is invalid.")
        with self.subTest("rejection explained with the service's reason"):
            self.azure.failures.clear()
            self.azure.fail("PUT", "arm", "incidentFilters", 400, generic)
            self.azure.fail("PUT", "agent", "incidentFilters", 400, {
                "error": "Incident platform 'AzMonitor' does not match configured incident management type 'None'"})
            code, _, errors = self._az("create", "-n", "p", "--platform", "AzMonitor", "--subagent", "responder")
            self.assertNotEqual(code, 0)
            self.assertIn("has no incident platform connected", errors)
            self.assertIn("does not match configured incident management type 'None'", errors)

        with self.subTest("meta_agent is the main agent, not a missing subagent"):
            self.azure.incident_platform = "AzMonitor"
            self.azure.failures.clear()
            self.azure.fail("PUT", "arm", "incidentFilters", 400, generic)
            self.azure.fail("PUT", "agent", "incidentFilters", 400, {"error": "Title filter is too long."})
            code, _, errors = self._az("create", "-n", "p", "--platform", "AzMonitor", "--subagent", "meta_agent")
            self.assertNotEqual(code, 0)
            self.assertIn("Title filter is too long.", errors)
            self.assertNotIn("doesn't exist", errors)
        self.assertEqual(self.azure.filters, {})

    def test_create_overwrite_reuses_the_plans_own_instructions(self):
        self._plan("p", handlers=[{"id": "portal-guid-1", "customInstructions": "Old", "tools": ["T1"]}])
        code, _, errors = self._az("create", "-n", "p", "--platform", "AzMonitor", "--subagent", "responder",
                                   "--instructions", "New", "--overwrite")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.azure.handlers, {"portal-guid-1": {
            "id": "portal-guid-1", "incidentFilterId": "p", "customInstructions": "New", "tools": ["T1"]}})

    def test_update_changes_every_linked_set_of_instructions(self):
        self._plan("p", handlers=[{"id": "h1", "customInstructions": "First", "tools": ["T1"]},
                                  {"id": "h2", "customInstructions": "Second"}])
        code, _, errors = self._az("update", "-n", "p", "--instructions", "Only one")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.azure.handlers, {
            "h1": {"id": "h1", "incidentFilterId": "p", "customInstructions": "Only one", "tools": ["T1"]},
            "h2": {"id": "h2", "incidentFilterId": "p", "customInstructions": "Only one"}})

    def test_update_to_icm_requires_an_incident_type(self):
        self._plan("p", priorities=["Sev1"])
        code, _, errors = self._az("update", "-n", "p", "--platform", "Icm")
        self.assertNotEqual(code, 0)
        self.assertIn("--incident-type is required", errors)
        self.assertEqual(self.azure.writes(), [])

        code, _, errors = self._az("update", "-n", "p", "--platform", "Icm", "--incident-type", "LiveSite")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.azure.filters["p"]["incidentTypes"], ["LiveSite"])


class ResponsePlanDirectRouteCliTests(_ResponsePlanCliTests, unittest.TestCase):
    ROUTE = "direct"


if __name__ == "__main__":
    unittest.main()

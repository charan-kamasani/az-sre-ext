"""Offline tests for the agent lifecycle and identity commands through the real Azure CLI.

ARM is faked at requests.adapters.HTTPAdapter.send. Both the AAZ pipeline and
send_raw_request (used by the hand-written commands) end there, so every
request reaches the fake. The fake keeps resources in memory, so a test can
check what a command wrote, kept or deleted. It follows the service rules
recorded in docs/operations.md: the App Insights connection string and the
incident connection key are write-only, a PUT replaces the whole agent, and a
PATCH merges.
"""

import copy
import inspect
import io
import json
import logging
import os
import re
import shlex
import socket
import tempfile
import threading
import time
import unittest
import uuid
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from http.client import responses as http_reasons
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import requests
from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
TENANT = "11111111-1111-1111-1111-111111111111"
RG_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg"
IDENTITY_PREFIX = f"{RG_ID}/providers/Microsoft.ManagedIdentity/userAssignedIdentities/"
ARM = "https://management.azure.com"


def _response(request, status, payload=None, headers=None):
    response = requests.Response()
    response.status_code = status
    response.reason = http_reasons.get(status, "")
    content = b"" if payload is None else json.dumps(payload).encode()
    response._content = content
    response.raw = io.BytesIO(content)
    response.encoding = "utf-8"
    if payload is not None:
        response.headers["Content-Type"] = "application/json"
    for key, value in (headers or {}).items():
        response.headers[key] = value
    response.url = request.url
    response.request = request
    return response


def _error(code, message):
    return {"error": {"code": code, "message": message}}


def _merge_patch(target, patch_body):
    for key, value in patch_body.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge_patch(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _strip_write_only(agent):
    view = copy.deepcopy(agent)
    properties = view.get("properties") or {}
    (properties.get("incidentManagementConfiguration") or {}).pop("connectionKey", None)
    app_insights = (properties.get("logConfiguration") or {}).get("applicationInsightsConfiguration")
    if isinstance(app_insights, dict):
        app_insights.pop("connectionString", None)
    return view


class FakeArm:
    """In-memory Microsoft.App/agents and user-assigned identities."""

    _AGENT_PATH = re.compile(
        r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft\.app/agents/([^/]+)(/.*)?$")
    _IDENTITY_PATH = re.compile(
        r"^/subscriptions/[^/]+/resourcegroups/[^/]+/providers/microsoft\.managedidentity/"
        r"userassignedidentities/[^/]+$")

    def __init__(self):
        self.resources = {}
        self.requests = []
        self.injected = []
        self.operations = {}
        self.lro_statuses = ["InProgress", "Succeeded"]
        self.action_result_body = True
        self.patch_answers_with_location_only = False
        # A PATCH answers 202, and the agent refuses other writes until its operation is polled to the end.
        self.patch_is_async = False
        self.patch_statuses = None
        # Statuses the agent's own API answers its next requests with, as its gateway does while it starts.
        self.agent_api_warmup = []
        # Called with the request's timeout instead of answering, as when the agent's API accepts
        # connections but never replies; it raises the timeout.
        self.agent_api_no_reply = None
        self.usage_pages = {}

    # ---- setup helpers -------------------------------------------------------------------
    def add_identity(self, name):
        resource_id = IDENTITY_PREFIX + name
        self.resources[resource_id.lower()] = {
            "id": resource_id, "name": name, "location": "swedencentral",
            "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
            "properties": {"principalId": str(uuid.uuid4()), "clientId": str(uuid.uuid4())},
        }
        return resource_id

    def add_agent(self, name="myagent", identity=None, properties=None, tags=None, resource_group="rg"):
        resource_id = (f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{resource_group}"
                       f"/providers/Microsoft.App/agents/{name}")
        agent = {
            "id": resource_id, "name": name, "type": "Microsoft.App/agents",
            "location": "swedencentral", "tags": tags or {},
            "identity": identity or {"type": "SystemAssigned"},
            "properties": {
                "provisioningState": "Succeeded", "powerState": "Running",
                "agentEndpoint": f"https://{name}.abc.swedencentral.azuresre.ai",
                "upgradeChannel": "Stable", **(properties or {}),
            },
        }
        self._fill_identity(agent["identity"])
        self.resources[resource_id.lower()] = agent
        return agent

    def inject(self, method, path_pattern, status, payload=None, headers=None, times=1):
        """Answer the next `times` matching requests with this response instead."""
        self.injected.append({
            "method": method, "pattern": re.compile(path_pattern, re.IGNORECASE),
            "response": (status, payload, headers), "times": times,
        })

    def agent(self, name="myagent"):
        return self.resources.get(f"{RG_ID}/providers/Microsoft.App/agents/{name}".lower())

    def writes(self, path_suffix=""):
        return [(method, body) for method, path, _, body in self.requests
                if method in ("PUT", "PATCH", "POST", "DELETE") and path.lower().endswith(path_suffix.lower())]

    # ---- transport -----------------------------------------------------------------------
    def send(self, adapter, request, **kwargs):
        del adapter
        url = urlparse(request.url)
        if url.hostname == "myagent.abc.swedencentral.azuresre.ai":
            self.requests.append((request.method, url.path, None, None))
            if self.agent_api_no_reply:
                self.agent_api_no_reply(kwargs.get("timeout"))
            status = self.agent_api_warmup.pop(0) if self.agent_api_warmup else 200
            return _response(request, status, {"value": []} if status == 200 else None)
        if url.hostname != "management.azure.com":
            raise AssertionError(f"Request to an unexpected host: {request.method} {request.url}")
        body = json.loads(request.body) if request.body else None
        query = parse_qs(url.query)
        api_version = (query.get("api-version") or [None])[0]
        self.requests.append((request.method, url.path, api_version, copy.deepcopy(body)))
        for rule in self.injected:
            if rule["times"] and rule["method"] == request.method and rule["pattern"].search(url.path):
                rule["times"] -= 1
                return _response(request, *rule["response"])
        status, payload, headers = self._route(request.method, url.path, query, body)
        return _response(request, status, payload, headers)

    def _route(self, method, path, query, body):
        lowered = path.lower()
        if lowered.startswith("/fake-operations/"):
            return self._operation(lowered.rsplit("/", 2)[-2:])
        if self._IDENTITY_PATH.match(lowered):
            return self._identity(method, path, body)
        match = self._AGENT_PATH.match(lowered)
        if not match:
            raise AssertionError(f"No fake ARM route for {method} {path}")
        agent_id = path[:len(path) - len(match.group(2) or "")]
        child = match.group(2) or ""
        if not child:
            return self._agent(method, agent_id, body)
        agent = self.resources.get(agent_id.lower())
        if agent is None:
            return 404, _error("ResourceNotFound", f"The Resource '{agent_id}' was not found."), None
        if method == "POST" and child in ("/start", "/stop"):
            agent["properties"]["powerState"] = "Running" if child == "/start" else "Stopped"
            return 202, None, self._new_operation(result=_strip_write_only(agent) if self.action_result_body else None)
        if method == "GET" and child.startswith("/connectors/"):
            connector = self.resources.get(path.lower())
            if connector is None:
                return 404, _error("ResourceNotFound", f"The Resource '{path}' was not found."), None
            return 200, copy.deepcopy(connector), None
        if method == "GET" and child in ("/usages", "/dailyusages"):
            token = (query.get("$skiptoken") or ["0"])[0]
            pages = self.usage_pages.get(child, [[]])
            page = int(token)
            payload = {"value": pages[page]}
            if page + 1 < len(pages):
                payload["nextLink"] = f"{ARM}{path}?api-version=2026-01-01&$skiptoken={page + 1}"
            return 200, payload, None
        raise AssertionError(f"No fake ARM route for {method} {path}")

    def _new_operation(self, result=None, statuses=None, on_done=None):
        operation_id = uuid.uuid4().hex
        self.operations[operation_id] = {
            "statuses": list(statuses if statuses is not None else self.lro_statuses), "result": result,
            "on_done": on_done}
        return {
            "Azure-AsyncOperation": f"{ARM}/fake-operations/{operation_id}/status",
            "Location": f"{ARM}/fake-operations/{operation_id}/result",
            "Retry-After": "0",
        }

    def _operation(self, parts):
        operation_id, kind = parts
        operation = self.operations[operation_id]
        if kind == "status":
            status = operation["statuses"].pop(0) if len(operation["statuses"]) > 1 else operation["statuses"][0]
            if status != "InProgress" and operation["on_done"]:
                operation.pop("on_done")()
                operation["on_done"] = None
            return 200, {"status": status}, {"Retry-After": "0"}
        if operation["result"] is None:
            return 204, None, None
        return 200, operation["result"], None

    def _identity(self, method, path, body):
        key = path.lower()
        if method == "PUT":
            name = path.rsplit("/", 1)[-1]
            self.resources[key] = {
                "id": path, "name": name, "location": body["location"],
                "type": "Microsoft.ManagedIdentity/userAssignedIdentities",
                "properties": {"principalId": str(uuid.uuid4()), "clientId": str(uuid.uuid4())},
            }
            return 201, copy.deepcopy(self.resources[key]), None
        if key not in self.resources:
            return 404, _error("ResourceNotFound", f"The Resource '{path}' was not found."), None
        if method == "DELETE":
            del self.resources[key]
            return 200, None, None
        return 200, copy.deepcopy(self.resources[key]), None

    def _fill_identity(self, identity):
        identity_type = (identity.get("type") or "None").replace(" ", "")
        if "SystemAssigned" in identity_type.split(","):
            identity.setdefault("principalId", str(uuid.uuid4()))
            identity.setdefault("tenantId", TENANT)
        else:
            identity.pop("principalId", None)
            identity.pop("tenantId", None)
        if "UserAssigned" not in identity_type.split(","):
            identity.pop("userAssignedIdentities", None)
            return None
        for uami_id in identity.get("userAssignedIdentities") or {}:
            uami = self.resources.get(uami_id.lower())
            if uami is None:
                return 400, _error("InvalidUserAssignedIdentity", f"Identity '{uami_id}' was not found."), None
            identity["userAssignedIdentities"][uami_id] = {
                "principalId": uami["properties"]["principalId"], "clientId": uami["properties"]["clientId"]}
        return None

    def _validate(self, agent):
        identity_type = ((agent.get("identity") or {}).get("type") or "None").replace(" ", "")
        if identity_type == "None":
            return 400, _error(
                "ManagedIdentityRequired",
                "At least one managed identity (SystemAssigned or UserAssigned) must be assigned to the agent."), None
        action = (agent.get("properties") or {}).get("actionConfiguration")
        if isinstance(action, dict) and not action.get("identity"):
            return 400, _error(
                "InvalidIdentity", f"The identity value '{action.get('identity') or ''}' of 'ActionConfiguration' "
                "is invalid."), None
        app_insights = ((agent.get("properties") or {}).get("logConfiguration") or {}).get(
            "applicationInsightsConfiguration")
        if isinstance(app_insights, dict) and (
                bool(app_insights.get("appId")) != bool(app_insights.get("connectionString"))):
            return 400, _error(
                "InvalidApplicationInsightsConfiguration",
                "The AppId and ConnectionString fields must be provided together."), None
        return self._fill_identity(agent["identity"])

    def _agent(self, method, agent_id, body):
        key = agent_id.lower()
        existing = self.resources.get(key)
        if method == "GET":
            if existing is None:
                return 404, _error("ResourceNotFound", f"The Resource '{agent_id}' was not found."), None
            return 200, _strip_write_only(existing), None
        if method == "DELETE":
            self.resources.pop(key, None)
            return 200, None, None
        if method in ("PUT", "PATCH") and existing is not None and (
                existing["properties"].get("provisioningState") == "InProgress"):
            return 409, _error("OperationConflict", f"Agent '{existing['name']}' is currently being provisioned "
                               "and cannot be created or updated."), None
        if method == "PUT":
            agent = {
                "id": agent_id, "name": agent_id.rsplit("/", 1)[-1], "type": "Microsoft.App/agents",
                "location": body.get("location"), "tags": copy.deepcopy(body.get("tags") or {}),
                "identity": copy.deepcopy(body.get("identity") or {}),
                "properties": copy.deepcopy(body.get("properties") or {}),
            }
            agent["properties"].update({
                "provisioningState": "Succeeded", "powerState": "Running",
                "agentEndpoint": f"https://{agent['name']}.abc.swedencentral.azuresre.ai",
            })
            error = self._validate(agent)
            if error:
                return error
            self.resources[key] = agent
            return 201, _strip_write_only(agent), self._new_operation()
        if method == "PATCH":
            if existing is None:
                return 404, _error("ResourceNotFound", f"The Resource '{agent_id}' was not found."), None
            agent = copy.deepcopy(existing)
            _merge_patch(agent, body)
            error = self._validate(agent)
            if error:
                return error
            self.resources[key] = agent
            if self.patch_answers_with_location_only:
                location = self._new_operation()["Location"]
                return 202, None, {"Location": location, "Retry-After": "0"}
            if self.patch_is_async:
                agent["properties"]["provisioningState"] = "InProgress"
                return 202, None, self._new_operation(
                    statuses=self.patch_statuses,
                    on_done=lambda: agent["properties"].update(provisioningState="Succeeded"))
            return 200, _strip_write_only(agent), None
        raise AssertionError(f"No fake ARM route for {method} {agent_id}")


class AgentCliTestCase(unittest.TestCase):
    """Loads this checkout as the only extension and fakes ARM over HTTP."""

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        self.config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": self.config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "no",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", self.config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        token = SimpleNamespace(token="fake-arm-token", expires_on=4102444800)
        credential = SimpleNamespace(get_token=lambda *a, **k: token, get_token_info=lambda *a, **k: token)
        stack.enter_context(patch(
            "azure.cli.core.aaz._command_ctx.AAZCommandCtx.get_login_credential", return_value=credential))
        stack.enter_context(patch(
            "azure.cli.core._profile.Profile.get_raw_token",
            return_value=(("Bearer", "fake-arm-token", {}), SUBSCRIPTION, TENANT)))
        stack.enter_context(patch(
            "azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUBSCRIPTION))
        self.arm = FakeArm()
        arm = self.arm

        def send(adapter, request, **kwargs):
            return arm.send(adapter, request, **kwargs)

        stack.enter_context(patch("requests.adapters.HTTPAdapter.send", send))
        stack.enter_context(patch.object(
            socket.socket, "connect", side_effect=AssertionError("This test must not use the network.")))
        # Polling, retries and Azure CLI's progress loop sleep for up to 30 seconds.
        real_sleep = time.sleep
        stack.enter_context(patch("time.sleep", lambda seconds: real_sleep(min(seconds, 0.01))))

    def invoke(self, *arguments):
        """Run `az <arguments>` and return (exit code, stdout, logged warnings and errors)."""
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.WARNING)
        with redirect_stdout(output), redirect_stderr(io.StringIO()), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            try:
                code = get_default_cli().invoke(list(arguments), out_file=output)
            except SystemExit as ex:
                code = ex.code
        return code, output.getvalue(), errors.getvalue()

    def invoke_with_cli_logging(self, *arguments):
        """Run `az <arguments>` with Azure CLI's own console and az.log logging set up
        from scratch, as in a new process. Returns (exit code, stderr, az.log)."""
        errors = io.StringIO()
        root, cli = logging.getLogger(), logging.getLogger("cli")
        with patch.dict(os.environ, {"AZURE_LOGGING_ENABLE_LOG_FILE": "true"}), \
                patch.object(root, "handlers", []), patch.object(cli, "handlers", []), \
                patch.object(root, "level", root.level), patch.object(cli, "level", cli.level), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(errors):
            try:
                code = get_default_cli().invoke(list(arguments), out_file=output)
            except SystemExit as ex:
                code = ex.code
            finally:
                for handler in root.handlers + cli.handlers:
                    handler.close()
        log_file = Path(self.config_dir, "logs", "az.log")
        return code, errors.getvalue(), log_file.read_text(encoding="utf-8") if log_file.exists() else ""

    def write_file(self, name, content):
        path = Path(self.config_dir, name)
        path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
        return str(path)


def _lines_with(text, secret):
    return [line for line in text.splitlines() if secret in line]


class AgentSecretLoggingTests(AgentCliTestCase):
    """VA-1: the incident connection key and the App Insights connection string
    stay out of --debug output and az.log, including on a retried request."""

    KEY = "FAKESECRET-PD-55aa"
    CONNECTION_STRING = "InstrumentationKey=FAKESECRET-CS-77bb"

    def _assert_secrets_not_logged(self, code, errors, log, secrets):
        self.assertEqual(code, 0, errors[-3000:])
        written = json.dumps([body for _, body in self.arm.writes("/agents/myagent")])
        for secret in secrets:
            self.assertIn(secret, written, "The fake never received the secret, so the check proves nothing.")
            self.assertEqual(_lines_with(errors, secret), [], "secret in --debug output")
            self.assertEqual(_lines_with(log, secret), [], "secret in az.log")
        self.assertIn("cli.azure.cli.core.sdk.policies", log, "HTTP tracing wasn't logged at all.")

    def _secret_files(self):
        incident = self.write_file("incident.json", {
            "type": "PagerDuty", "connectionName": "pd", "connectionKey": self.KEY, "oboUser": "oncall@contoso.com"})
        log_configuration = self.write_file("log.json", {
            "applicationInsightsConfiguration": {"appId": "app-1", "connectionString": self.CONNECTION_STRING}})
        return incident, log_configuration

    def test_create_keeps_secrets_out_of_logs_even_when_the_put_is_retried(self):
        incident, log_configuration = self._secret_files()
        self.arm.inject("PUT", r"/agents/myagent$", 503, _error("ServiceUnavailable", "busy"),
                        {"Retry-After": "0.01"})
        code, errors, log = self.invoke_with_cli_logging(
            "sre", "agent", "create", "-g", "rg", "-n", "myagent", "-l", "swedencentral", "--mi-system-assigned",
            "--incident-management-configuration", f"@{incident}", "--log-configuration", f"@{log_configuration}",
            "--debug")
        self.assertEqual([method for method, _ in self.arm.writes("/agents/myagent")], ["PUT", "PUT"])
        self._assert_secrets_not_logged(code, errors, log, (self.KEY, self.CONNECTION_STRING))

    def test_update_patch_keeps_the_connection_key_out_of_logs(self):
        incident, _ = self._secret_files()
        self.arm.add_agent(properties={"logConfiguration": {"applicationInsightsConfiguration": {
            "appId": "app-1", "connectionString": "InstrumentationKey=stored"}}})
        code, errors, log = self.invoke_with_cli_logging(
            "sre", "agent", "update", "-g", "rg", "-n", "myagent",
            "--incident-management-configuration", f"@{incident}", "--debug")
        self.assertEqual([method for method, _ in self.arm.writes("/agents/myagent")], ["PATCH"])
        self._assert_secrets_not_logged(code, errors, log, (self.KEY,))

    def test_a_secret_typed_on_the_command_line_gets_a_warning(self):
        self.arm.add_agent()
        incident, _ = self._secret_files()
        for flag, value, warned in (
            ("--incident-config", f"{{type:PagerDuty,connection-name:pd,connection-key:{self.KEY}}}", True),
            ("--incident-management-configuration", f"@{incident}", False),
            ("--incident-management-configuration", "{type:AzMonitor,connection-name:azmonitor}", False),
        ):
            with self.subTest(flag=flag, value=value):
                arguments = ("sre", "agent", "update", "-g", "rg", "-n", "myagent", flag, value, "-o", "none")
                with patch("sys.argv", ["az", *arguments]):
                    code, _, errors = self.invoke(*arguments)
                self.assertEqual(code, 0, errors)
                self.assertEqual(f"{flag} was typed on the command line" in errors, warned, errors)


class IdentityPatchTests(AgentCliTestCase):
    """VA-2: identity assign/remove PATCH only the identity block."""

    def setUp(self):
        super().setUp()
        self.first = self.arm.add_identity("first")
        self.second = self.arm.add_identity("second")

    def _add_full_agent(self, identity):
        return self.arm.add_agent(identity=identity, properties={
            "logConfiguration": {"applicationInsightsConfiguration": {
                "appId": "app-1", "connectionString": "InstrumentationKey=kept"}},
            "incidentManagementConfiguration": {
                "type": "PagerDuty", "connectionName": "pd", "connectionKey": "kept-key"},
            "monthlyAgentUnitLimit": 700,
            "experimentalSettings": {"EnableConnectorsV2": True, "EnableWorkspaceTools": True},
            "sandboxConfiguration": {"egress": {"mode": "Limited", "allowedHosts": ["example.com"]}},
        })

    def _assert_rest_of_agent_kept(self, before):
        after = self.arm.agent()
        self.assertEqual({k: v for k, v in after.items() if k != "identity"},
                         {k: v for k, v in before.items() if k != "identity"})

    def _agent_reads(self):
        return sum(1 for method, path, _, _ in self.arm.requests
                   if method == "GET" and path.lower().endswith("/agents/myagent"))

    def test_assign_on_an_app_insights_agent_keeps_everything_else(self):
        before = copy.deepcopy(self._add_full_agent({"type": "SystemAssigned"}))
        code, output, errors = self.invoke(
            "sre", "identity", "assign", "-g", "rg", "--agent-name", "myagent", "--user-assigned", self.first)
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.writes(), [("PATCH", {"identity": {
            "type": "SystemAssigned,UserAssigned", "userAssignedIdentities": {self.first: {}}}})])
        self.assertEqual(self._agent_reads(), 1)
        self._assert_rest_of_agent_kept(before)
        self.assertEqual(list(self.arm.agent()["identity"]["userAssignedIdentities"]), [self.first])
        self.assertIn(self.first, json.loads(output)["userAssignedIdentities"])

    def test_removing_one_user_assigned_identity_keeps_the_others(self):
        before = copy.deepcopy(self._add_full_agent({
            "type": "SystemAssigned, UserAssigned",
            "userAssignedIdentities": {self.first: {}, self.second: {}}}))
        code, _, errors = self.invoke(
            "sre", "identity", "remove", "-g", "rg", "--agent-name", "myagent", "--user-assigned", self.first)
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.writes(), [("PATCH", {"identity": {
            "type": "SystemAssigned,UserAssigned",
            "userAssignedIdentities": {self.second: {}, self.first: None}}})])
        self._assert_rest_of_agent_kept(before)
        identity = self.arm.agent()["identity"]
        self.assertEqual(list(identity["userAssignedIdentities"]), [self.second])
        self.assertIn("principalId", identity)

    def test_removing_the_last_user_assigned_identity_changes_the_type(self):
        self._add_full_agent({"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {self.first: {}}})
        code, _, errors = self.invoke(
            "sre", "identity", "remove", "-g", "rg", "--agent-name", "myagent", "--user-assigned", self.first.upper())
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.writes(), [("PATCH", {"identity": {"type": "SystemAssigned"}})])
        self.assertNotIn("userAssignedIdentities", self.arm.agent()["identity"])

    def test_output_is_read_back_when_the_patch_result_has_no_body(self):
        self._add_full_agent({
            "type": "SystemAssigned, UserAssigned",
            "userAssignedIdentities": {self.first: {}, self.second: {}}})
        self.arm.patch_answers_with_location_only = True
        code, output, errors = self.invoke(
            "sre", "identity", "remove", "-g", "rg", "--agent-name", "myagent", "--user-assigned", self.first)
        self.assertEqual(code, 0, errors)
        self.assertEqual(list(json.loads(output)["userAssignedIdentities"]), [self.second])
        self.assertEqual(self._agent_reads(), 2)

    def test_requests_that_change_nothing_are_rejected_before_any_write(self):
        self._add_full_agent({"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {self.first: {}}})
        for verb, extra, message in (
            ("assign", [], "Specify --system-assigned, --user-assigned, or both."),
            ("remove", [], "Specify --system-assigned, --user-assigned, or both."),
            ("remove", ["--user-assigned", self.second], self.second),
        ):
            with self.subTest(verb=verb, extra=extra):
                code, _, errors = self.invoke(
                    "sre", "identity", verb, "-g", "rg", "--agent-name", "myagent", *extra)
                self.assertNotEqual(code, 0)
                self.assertIn(message, errors)
                self.assertEqual(self.arm.writes(), [])


class AgentCreateTests(AgentCliTestCase):
    """VA-3 and VA-4: 'agent create' never replaces an agent, and only deletes
    the identity it made when the service says the create failed."""

    CREATE = ("sre", "agent", "create", "-g", "rg", "-n", "myagent", "-l", "swedencentral")

    def _identities(self):
        return [resource for key, resource in self.arm.resources.items() if "userassignedidentities" in key]

    def test_create_refuses_an_existing_agent(self):
        uami = self.arm.add_identity("myagent-identity-old")
        before = copy.deepcopy(self.arm.add_agent(
            identity={"type": "SystemAssigned, UserAssigned", "userAssignedIdentities": {uami: {}}},
            properties={"monthlyAgentUnitLimit": 700}, tags={"env": "prod"}))
        code, _, errors = self.invoke(*self.CREATE)
        self.assertNotEqual(code, 0)
        self.assertIn("already exists", errors)
        self.assertIn("az sre agent update", errors)
        self.assertEqual(self.arm.writes(), [])
        self.assertEqual(self.arm.agent(), before)
        self.assertEqual(len(self._identities()), 1)

    def test_create_over_a_failed_agent_offers_update_or_delete(self):
        self.arm.add_agent(properties={"provisioningState": "Failed"})
        code, _, errors = self.invoke(*self.CREATE)
        self.assertNotEqual(code, 0)
        self.assertIn("(provisioningState: Failed)", errors)
        self.assertIn("az sre agent update", errors)
        self.assertIn("az sre agent delete --name myagent --resource-group rg", errors)
        self.assertEqual(self.arm.writes(), [])

    def test_identity_is_kept_when_waiting_fails_but_the_agent_exists(self):
        for label, failure in (
            ("status polls keep failing", ("GET", r"/fake-operations/.*/status$", 503, 50, {"Retry-After": "0.01"})),
            # The first 404 answers the existence check, the second the read after success.
            ("read after success answers 404", ("GET", r"/agents/myagent$", 404, 2, None)),
        ):
            with self.subTest(label):
                self.arm.resources.clear()
                self.arm.injected.clear()
                method, pattern, status, times, headers = failure
                self.arm.inject(method, pattern, status, _error("Transient", "try later"),
                                headers, times=times)
                code, _, errors = self.invoke(*self.CREATE)
                self.assertNotEqual(code, 0)
                identities = self._identities()
                self.assertEqual(len(identities), 1, errors)
                self.assertIn(identities[0]["id"], self.arm.agent()["identity"]["userAssignedIdentities"])
                self.assertIn(f"Kept the identity '{identities[0]['name']}'", errors)
                self.assertNotIn("DELETE", [method for method, _ in self.arm.writes()])

    def test_identity_is_deleted_when_the_service_reports_the_create_failed(self):
        self.arm.lro_statuses = ["InProgress", "Failed"]
        code, _, errors = self.invoke(*self.CREATE)
        self.assertNotEqual(code, 0)
        self.assertEqual(self._identities(), [])
        self.assertIn("deleted the identity", errors)

    def test_failed_settings_patch_says_the_agent_was_created(self):
        self.arm.inject("PATCH", r"/agents/myagent$", 400, _error("InvalidMonthlyAgentUnitLimit", "too low"))
        code, _, errors = self.invoke(*self.CREATE, "--monthly-unit-limit", "10")
        self.assertNotEqual(code, 0)
        self.assertIn("Agent 'myagent' was created, but applying --monthly-unit-limit failed", errors)
        self.assertIn("az sre agent update --name myagent --resource-group rg", errors)
        self.assertIsNotNone(self.arm.agent())
        self.assertEqual(len(self._identities()), 1)

    def test_create_waits_for_the_settings_update_to_finish(self):
        self.arm.patch_is_async = True
        code, _, errors = self.invoke(*self.CREATE, "--monthly-unit-limit", "700",
                                      "--experimental-settings", '{"EnableWorkspaceTools": true}', "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.writes("/agents/myagent")[-1], ("PATCH", {"properties": {
            "experimentalSettings": {"EnableWorkspaceTools": True}, "monthlyAgentUnitLimit": 700}}))
        code, _, errors = self.invoke("sre", "agent", "update", "-g", "rg", "-n", "myagent", "--tags", "env=prod",
                                      "-o", "none")
        self.assertEqual(code, 0, errors)

    def test_settings_update_that_fails_later_says_the_agent_was_created(self):
        self.arm.patch_is_async = True
        self.arm.patch_statuses = ["InProgress", "Failed"]
        code, _, errors = self.invoke(*self.CREATE, "--monthly-unit-limit", "700")
        self.assertNotEqual(code, 0)
        self.assertIn("Agent 'myagent' was created, but applying --monthly-unit-limit failed", errors)
        self.assertEqual(len(self._identities()), 1)

    ACTIONS = ("--action-configuration", "{access-level:Low,mode:Review}")

    def test_action_configuration_without_an_identity_gets_the_agents_user_assigned_identity(self):
        uami = self.arm.add_identity("actions")
        for label, extra in (("identity the command creates", ()),
                             ("one --mi-user-assigned", ("--mi-user-assigned", uami))):
            with self.subTest(label):
                self.arm.resources = {k: v for k, v in self.arm.resources.items() if "/agents/" not in k}
                code, _, errors = self.invoke(*self.CREATE, *self.ACTIONS, *extra, "-o", "none")
                self.assertEqual(code, 0, errors)
                agent = self.arm.agent()
                self.assertEqual([agent["properties"]["actionConfiguration"]["identity"]],
                                 list(agent["identity"]["userAssignedIdentities"]))
        self.arm.resources = {k: v for k, v in self.arm.resources.items() if "/agents/" not in k}
        code, _, errors = self.invoke(*self.CREATE, *self.ACTIONS, "--mi-system-assigned", "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.agent()["properties"]["actionConfiguration"]["identity"], "system")

    def test_action_identity_is_not_guessed_among_several_user_assigned_identities(self):
        first, second = self.arm.add_identity("first"), self.arm.add_identity("second")
        code, _, errors = self.invoke(*self.CREATE, *self.ACTIONS, "--mi-user-assigned", first, second)
        self.assertNotEqual(code, 0)
        self.assertIn("--action-configuration", errors)
        self.assertEqual(self.arm.writes(), [])
        code, _, errors = self.invoke(
            *self.CREATE, "--action-configuration", f"{{access-level:Low,mode:Review,identity:{second}}}",
            "--mi-user-assigned", first, second, "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.agent()["properties"]["actionConfiguration"]["identity"], second)


class _ProbeClock:
    """Stands in for time.monotonic and time.sleep. Only the thread that probes the
    agent's API spends time, from its first probe on, and each probe uses up its
    whole timeout, as when the API accepts connections but never replies."""

    def __init__(self, sleep):
        self.now = 0.0
        self._sleep = sleep
        self._prober = None

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        if threading.get_ident() == self._prober:
            self.now += seconds
        self._sleep(seconds)

    def probe_never_replies(self, timeout):
        self._prober = threading.get_ident()
        self.now += timeout
        raise requests.exceptions.ReadTimeout("The agent's API accepted the connection but didn't reply.")


class AgentLifecycleTests(AgentCliTestCase):
    """VA-5, VA-6, VA-7, VA-8 and VA-9."""

    def test_stop_succeeds_when_the_operation_result_has_no_body(self):
        self.arm.add_agent()
        self.arm.action_result_body = False
        code, output, errors = self.invoke("sre", "agent", "stop", "-g", "rg", "-n", "myagent")
        self.assertEqual(code, 0, errors)
        self.assertEqual(output.strip(), "")
        self.assertEqual(self.arm.agent()["properties"]["powerState"], "Stopped")
        self.arm.action_result_body = True
        code, output, errors = self.invoke("sre", "agent", "start", "-g", "rg", "-n", "myagent")
        self.assertEqual(code, 0, errors)
        self.assertEqual(json.loads(output)["properties"]["powerState"], "Running")

    def test_start_or_stop_conflict_shows_the_services_reason(self):
        self.arm.add_agent()
        for verb in ("start", "stop"):
            with self.subTest(verb):
                # The service answers with a bare JSON string, not an ARM error object.
                self.arm.inject("POST", rf"/agents/myagent/{verb}$", 409, "Agent lifecycle or power policy changed.")
                code, _, errors = self.invoke("sre", "agent", verb, "-g", "rg", "-n", "myagent")
                self.assertNotEqual(code, 0)
                self.assertIn("Agent lifecycle or power policy changed.", errors)

    def test_start_waits_until_the_agents_api_answers(self):
        self.arm.add_agent(properties={"powerState": "Stopped"})
        self.arm.agent_api_warmup = [404, 502, 503]
        code, _, errors = self.invoke("sre", "agent", "start", "-g", "rg", "-n", "myagent", "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.agent_api_warmup, [])

        self.arm.agent_api_warmup = [404]
        code, _, errors = self.invoke("sre", "agent", "start", "-g", "rg", "-n", "myagent", "--no-wait")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.agent_api_warmup, [404])

    def test_start_stops_waiting_after_five_minutes_when_the_agents_api_never_replies(self):
        self.arm.add_agent(properties={"powerState": "Stopped"})
        clock = _ProbeClock(time.sleep)
        self.arm.agent_api_no_reply = clock.probe_never_replies
        with patch("time.monotonic", clock.monotonic), patch("time.sleep", clock.sleep):
            code, _, errors = self.invoke("sre", "agent", "start", "-g", "rg", "-n", "myagent", "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertEqual(self.arm.agent()["properties"]["powerState"], "Running")
        self.assertIn("Agent 'myagent' is running, but its API didn't answer within 5 minutes", errors)
        self.assertAlmostEqual(clock.now, 5 * 60, delta=10)

    def test_wait_commands_fail_when_they_time_out(self):
        self.arm.add_agent()
        for command in (
            ("sre", "agent", "wait", "-g", "rg", "-n", "ghost", "--exists"),
            ("sre", "identity", "wait", "-g", "rg", "--agent-name", "ghost", "--created"),
            ("sre", "connector", "wait", "-g", "rg", "--agent-name", "myagent", "-n", "nope", "--exists"),
        ):
            with self.subTest(command=command[1]):
                code, output, errors = self.invoke(*command, "--timeout", "2", "--interval", "1")
                self.assertNotEqual(code, 0, output)
                self.assertIn("Wait operation timed-out after 2 seconds", errors)

    def test_null_clears_a_property_on_both_write_paths(self):
        incident = {"type": "PagerDuty", "connectionName": "pd", "connectionKey": "k"}
        app_insights = {"applicationInsightsConfiguration": {"appId": "app-1", "connectionString": "cs"}}
        for label, properties, method in (
            ("PUT", {"incidentManagementConfiguration": incident}, "PUT"),
            ("PATCH on an App Insights agent", {"incidentManagementConfiguration": incident,
                                                "logConfiguration": app_insights}, "PATCH"),
        ):
            with self.subTest(label):
                self.arm.requests.clear()
                self.arm.add_agent(properties=copy.deepcopy(properties))
                code, _, errors = self.invoke(
                    "sre", "agent", "update", "-g", "rg", "-n", "myagent",
                    "--incident-management-configuration", "null", "-o", "none")
                self.assertEqual(code, 0, errors)
                self.assertEqual([m for m, _ in self.arm.writes()], [method])
                self.assertNotIn("incidentManagementConfiguration", self.arm.agent()["properties"])
        code, _, errors = self.invoke(
            "sre", "agent", "update", "-g", "rg", "-n", "myagent", "--default-model", "null", "-o", "none")
        self.assertEqual(code, 0, errors)

    def test_patch_update_removes_what_a_put_would_and_keeps_the_app_insights_link(self):
        self.arm.add_agent(tags={"env": "prod"}, properties={
            "logConfiguration": {"applicationInsightsConfiguration": {"appId": "app-1", "connectionString": "cs"}},
            "incidentManagementConfiguration": {
                "type": "PagerDuty", "connectionName": "pd", "oboUser": "oncall@contoso.com"},
        })
        code, _, errors = self.invoke(
            "sre", "agent", "update", "-g", "rg", "-n", "myagent", "--tags", "null",
            "--incident-management-configuration", "{type:AzMonitor,connection-name:azmonitor}", "-o", "none")
        self.assertEqual(code, 0, errors)
        (method, body), = self.arm.writes()
        self.assertEqual(method, "PATCH")
        self.assertEqual(body["tags"], {})
        self.assertNotIn("logConfiguration", body["properties"])
        self.assertEqual(self.arm.agent()["properties"]["incidentManagementConfiguration"],
                         {"type": "AzMonitor", "connectionName": "azmonitor"})
        self.assertEqual(self.arm.agent()["properties"]["logConfiguration"]["applicationInsightsConfiguration"],
                         {"appId": "app-1", "connectionString": "cs"})
        code, _, errors = self.invoke(
            "sre", "agent", "update", "-g", "rg", "-n", "myagent",
            "--remove", "properties.incidentManagementConfiguration", "-o", "none")
        self.assertEqual(code, 0, errors)
        self.assertNotIn("incidentManagementConfiguration", self.arm.agent()["properties"])

    def test_documented_create_and_update_examples_run(self):
        from azext_sre.custom import Create, Update

        self.write_file("pagerduty.json", {
            "type": "PagerDuty", "connectionName": "pagerduty", "connectionKey": "<api-key>",
            "oboUser": "oncall@contoso.com"})
        self.write_file("experimental.json", {"EnableWorkspaceTools": True})
        cwd = os.getcwd()
        os.chdir(self.config_dir)
        self.addCleanup(os.chdir, cwd)
        for command in (Create, Update):
            for example in _examples(command):
                with self.subTest(example=" ".join(example)):
                    self.arm.resources = {k: v for k, v in self.arm.resources.items() if "/agents/" not in k}
                    if command is Update:
                        self.arm.add_agent(resource_group="myrg")
                    code, _, errors = self.invoke(*example, "-o", "none")
                    self.assertEqual(code, 0, errors)

    def test_usage_list_returns_every_item_across_pages(self):
        self.arm.add_agent()
        self.arm.usage_pages["/usages"] = [
            [{"name": "2026-10", "agentUnits": 12}, {"name": "2026-11", "agentUnits": 30}],
            [{"name": "2026-09", "agentUnits": 7}],
        ]
        code, output, errors = self.invoke("sre", "usage", "list", "-g", "rg", "-n", "myagent")
        self.assertEqual(code, 0, errors)
        self.assertEqual([item["name"] for item in json.loads(output)], ["2026-10", "2026-11", "2026-09"])
        code, output, errors = self.invoke("sre", "usage", "list", "-g", "rg", "-n", "myagent", "-o", "table")
        self.assertEqual(code, 0, errors)
        self.assertIn("2026-09", output)
        code, _, errors = self.invoke("sre", "usage", "list", "-g", "rg", "-n", "ghost")
        self.assertEqual(code, 3, errors)
        self.assertIn("Agent 'ghost' not found in resource group 'rg'.", errors)

    def test_show_and_update_output_include_the_unit_limit_and_feature_flags(self):
        self.arm.add_agent(properties={
            "monthlyAgentUnitLimit": 700, "experimentalSettings": {"EnableWorkspaceTools": True}})
        code, output, errors = self.invoke("sre", "agent", "show", "-g", "rg", "-n", "myagent")
        self.assertEqual(code, 0, errors)
        properties = json.loads(output)["properties"]
        self.assertEqual(properties["monthlyAgentUnitLimit"], 700)
        self.assertEqual(properties["experimentalSettings"], {"EnableWorkspaceTools": True})
        code, output, errors = self.invoke(
            "sre", "agent", "update", "-g", "rg", "-n", "myagent", "--monthly-unit-limit", "2000",
            "--query", "properties.monthlyAgentUnitLimit", "-o", "tsv")
        self.assertEqual(code, 0, errors)
        self.assertEqual(output.strip(), "2000")


class NetworkUpdateTests(AgentCliTestCase):
    """VE-10: proxy credentials stay out of logs, and an update that sets nothing fails."""

    PASSWORD = "S3cretPr0xy"

    def test_proxy_credentials_stay_out_of_debug_output_and_az_log(self):
        self.arm.add_agent()
        sandbox = self.write_file("sandbox.json", {"egress": {"httpProxy": {
            "httpsUrl": f"http://svc:{self.PASSWORD}@proxy.contoso.com:3128"}}})
        code, errors, log = self.invoke_with_cli_logging(
            "sre", "network", "update", "-g", "rg", "-n", "myagent", "--sandbox-configuration", f"@{sandbox}",
            "--debug")
        self.assertEqual(code, 0, errors[-3000:])
        self.assertIn(self.PASSWORD, json.dumps(self.arm.writes()))
        self.assertEqual(_lines_with(errors, self.PASSWORD), [])
        self.assertEqual(_lines_with(log, self.PASSWORD), [])

    def test_an_update_that_sets_nothing_is_rejected(self):
        self.arm.add_agent()
        for value in ("{egress:{http-proxy:null}}", "{}"):
            with self.subTest(value=value):
                code, _, errors = self.invoke(
                    "sre", "network", "update", "-g", "rg", "-n", "myagent", "--sandbox-configuration", value)
                self.assertNotEqual(code, 0)
                self.assertIn("--sandbox-configuration has nothing to set", errors)
                self.assertEqual(self.arm.writes(), [])

    DEFAULT_HOSTS = ["management.azure.com", "api.loganalytics.io", "learn.microsoft.com"]

    def _add_limited_agent(self):
        self.arm.add_agent(properties={"sandboxConfiguration": {"egress": {
            "mode": "Limited", "allowedHosts": list(self.DEFAULT_HOSTS), "allowedRegistries": ["pypi"]}}})

    def test_allowed_hosts_are_added_to_the_current_list(self):
        self._add_limited_agent()
        code, output, errors = self.invoke(
            "sre", "network", "update", "-g", "rg", "-n", "myagent",
            "--sandbox-configuration", "{egress:{mode:Limited,allowed-hosts:[example.com,LEARN.microsoft.com]}}")
        self.assertEqual(code, 0, errors)
        expected = self.DEFAULT_HOSTS + ["example.com"]
        egress = self.arm.agent()["properties"]["sandboxConfiguration"]["egress"]
        self.assertEqual(egress["allowedHosts"], expected)
        self.assertEqual(egress["allowedRegistries"], ["pypi"])
        self.assertEqual(json.loads(output)["sandboxConfiguration"]["egress"]["allowedHosts"], expected)

    def test_replacing_the_allowed_hosts_names_the_hosts_it_drops(self):
        self._add_limited_agent()
        code, _, errors = self.invoke(
            "sre", "network", "update", "-g", "rg", "-n", "myagent", "--replace-allowed-hosts",
            "--sandbox-configuration", "{egress:{allowed-hosts:[example.com,api.loganalytics.io]}}")
        self.assertEqual(code, 0, errors)
        egress = self.arm.agent()["properties"]["sandboxConfiguration"]["egress"]
        self.assertEqual(egress["allowedHosts"], ["example.com", "api.loganalytics.io"])
        self.assertIn("management.azure.com, learn.microsoft.com", errors)
        self.assertNotIn("api.loganalytics.io", errors)


def _examples(command):
    """Each ':example:' command in a command's help, as an argument list without 'az'."""
    for block in inspect.getdoc(command).split(":example:")[1:]:
        lines = []
        for line in block.splitlines()[1:]:
            if not line.strip():
                break
            lines.append(line.strip().rstrip("\\").strip())
        yield shlex.split(" ".join(lines))[1:]


if __name__ == "__main__":
    unittest.main()

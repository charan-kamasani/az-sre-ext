"""Connector and knowledge commands through the real Azure CLI, with ARM faked
by a stateful in-memory store at the HTTP adapter, so both the generated
commands and the hand-written _arm_request calls reach it."""

import copy
import io
import json
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

import requests
from requests.structures import CaseInsensitiveDict

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
AGENT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
UAMI_ID = (f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg"
           "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/connector-identity")


class _FakeArm:
    """One agent and its connectors. A PUT replaces the whole connector, reads
    leave out the settings the service never returns, and listSecrets returns
    everything that was stored."""

    UNREAD_EXTENDED_PROPERTIES = ("endpoint", "bearerToken", "headers")

    def __init__(self):
        self.resources = {AGENT_ID.lower(): {
            "id": AGENT_ID, "name": "myagent", "type": "Microsoft.App/agents", "location": "eastus2",
            "properties": {"provisioningState": "Succeeded"},
        }}
        self.requests = []

    def add_connector(self, name, **properties):
        resource_id = f"{AGENT_ID}/connectors/{name}"
        self.resources[resource_id.lower()] = {
            "id": resource_id, "name": name, "type": "Microsoft.App/agents/connectors",
            "properties": {**properties, "provisioningState": "Succeeded"},
        }

    def connector(self, name):
        return self.resources.get(f"{AGENT_ID}/connectors/{name}".lower())

    def sent(self, method):
        return [(path, body) for verb, path, body in self.requests if verb == method]

    def _readable(self, resource):
        resource = copy.deepcopy(resource)
        properties = resource["properties"]
        properties.pop("dataSource", None)
        properties.pop("identity", None)
        for key in self.UNREAD_EXTENDED_PROPERTIES:
            (properties.get("extendedProperties") or {}).pop(key, None)
        return resource

    def send(self, request):
        path = urlsplit(request.url).path
        body = json.loads(request.body) if request.body else None
        self.requests.append((request.method, path, body))
        key = path.rstrip("/").lower()
        if request.method == "POST" and key.endswith("/listsecrets"):
            stored = self.resources.get(key[:-len("/listsecrets")])
            return self._response(request, 200, stored) if stored else self._not_found(request)
        if request.method == "GET" and key.endswith("/connectors"):
            items = [self._readable(v) for k, v in self.resources.items() if k.startswith(key + "/")]
            return self._response(request, 200, {"value": items})
        if request.method == "GET":
            stored = self.resources.get(key)
            return self._response(request, 200, self._readable(stored)) if stored else self._not_found(request)
        if request.method == "PUT":
            existed = key in self.resources
            self.resources[key] = {
                "id": path, "name": path.rsplit("/", 1)[-1], "type": "Microsoft.App/agents/connectors",
                "properties": {**(body or {}).get("properties", {}), "provisioningState": "Succeeded"},
            }
            return self._response(request, 200 if existed else 201, self._readable(self.resources[key]))
        if request.method == "DELETE":
            existed = self.resources.pop(key, None)
            for child in [k for k in self.resources if k.startswith(key + "/")]:
                del self.resources[child]
            return self._response(request, 200 if existed else 204, None)
        return self._response(request, 405, {"error": {"code": "MethodNotAllowed", "message": request.method}})

    def _not_found(self, request):
        return self._response(request, 404, {"error": {"code": "ResourceNotFound", "message": "Not found."}})

    @staticmethod
    def _response(request, status, payload):
        response = requests.Response()
        response.status_code = status
        response.reason = "OK" if status < 400 else "Error"
        response._content = json.dumps(payload).encode() if payload is not None else b""
        response.raw = io.BytesIO(response._content)
        response.headers = CaseInsensitiveDict({"Content-Type": "application/json"})
        response.url = request.url
        response.request = request
        response.encoding = "utf-8"
        return response


class ConnectorCliTests(unittest.TestCase):

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        self.files = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "no",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        token = SimpleNamespace(token="fake-token", expires_on=4102444800)
        credential = SimpleNamespace(get_token=lambda *a, **k: token, get_token_info=lambda *a, **k: token)
        stack.enter_context(patch(
            "azure.cli.core.aaz._command_ctx.AAZCommandCtx.get_login_credential", return_value=credential))
        stack.enter_context(patch(
            "azure.cli.core._profile.Profile.get_raw_token",
            return_value=(("Bearer", "fake-token", {}), SUBSCRIPTION, "tenant")))
        stack.enter_context(patch(
            "azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUBSCRIPTION))
        self.arm = _FakeArm()
        stack.enter_context(patch(
            "requests.adapters.HTTPAdapter.send", lambda adapter, request, **kwargs: self.arm.send(request)))
        self.arm.add_connector("kusto-prod", dataConnectorType="Kusto",
                               dataSource="https://prod.kusto.windows.net/db", identity=UAMI_ID)
        self.arm.add_connector("docs", dataConnectorType="KnowledgeWebPage",
                               extendedProperties={"url": "https://docs.contoso.com/"})

    def _file(self, name, content):
        path = os.path.join(self.files, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def _run(self, *arguments):
        """Return the exit code, stdout, and everything stderr and the loggers saw at any level."""
        output, errors, records = io.StringIO(), io.StringIO(), []
        capture = logging.Handler(logging.DEBUG)
        capture.emit = records.append
        root, cli = logging.getLogger(), logging.getLogger("cli")
        levels = root.level, cli.level
        root.setLevel(logging.DEBUG)
        cli.setLevel(logging.DEBUG)
        try:
            with redirect_stdout(output), redirect_stderr(errors), \
                    patch.object(root, "handlers", [capture]), patch.object(cli, "handlers", [capture]):
                code = get_default_cli().invoke(list(arguments), out_file=output)
        except SystemExit as ex:
            code = ex.code
        finally:
            root.setLevel(levels[0])
            cli.setLevel(levels[1])
        logs = SimpleNamespace(
            errors="\n".join(r.getMessage() for r in records if r.levelno >= logging.ERROR),
            warnings="\n".join(r.getMessage() for r in records if r.levelno == logging.WARNING),
            everything=errors.getvalue() + "\n".join(
                r.getMessage() + (r.exc_text or "") for r in records),
        )
        return code, output.getvalue(), logs

    def test_names_that_change_the_url_are_rejected_before_any_request(self):
        target = ["-g", "rg", "--agent-name", "myagent"]
        before = copy.deepcopy(self.arm.resources)
        for name, command in (
                ("..", ["connector", "delete", "--yes"]),
                (".", ["connector", "delete", "--yes"]),
                ("a/b", ["connector", "delete", "--yes"]),
                ("..", ["connector", "update", "--data-connector-type", "Kusto", "--data-source", "x",
                        "--identity", "null"]),
                ("..", ["connector", "create", "--data-connector-type", "Kusto", "--data-source", "x",
                        "--overwrite"]),
                ("bad name!", ["connector", "create", "--data-connector-type", "Kusto", "--data-source", "x"]),
                ("..", ["connector", "show"]),
                ("..", ["connector", "list-secret"]),
                ("..", ["connector", "wait", "--created", "--interval", "1", "--timeout", "2"]),
                ("..", ["knowledge", "delete", "--yes"]),
                ("..", ["knowledge", "show"]),
                ("..", ["knowledge", "create", "--type", "webpage", "--url", "https://x.example.com/",
                        "--overwrite"])):
            with self.subTest(command=command[:2], name=name):
                self.arm.requests.clear()
                code, _, logs = self._run("sre", *command[:2], *target, "-n", name, *command[2:])
                self.assertNotEqual(code, 0)
                self.assertIn(f"'{name}'", logs.errors)
                self.assertEqual(self.arm.requests, [])
        self.assertEqual(self.arm.resources, before)

        code, _, logs = self._run("sre", "connector", "delete", *target, "-n", "kusto-prod", "--yes")
        self.assertEqual(code, 0, logs.errors)
        self.assertIsNone(self.arm.connector("kusto-prod"))
        self.assertIn(AGENT_ID.lower(), self.arm.resources)

    def test_update_refuses_to_drop_settings_the_service_never_returns(self):
        mcp_settings = {"authType": "BearerToken", "transport": "Http",
                        "endpoint": "https://mcp.contoso.com/mcp", "bearerToken": "token-1"}
        self.arm.add_connector("mcp1", dataConnectorType="Mcp", dataSource="https://mcp.contoso.com/mcp",
                               identity=UAMI_ID, extendedProperties=dict(mcp_settings))
        full_settings = self._file("mcp.json", json.dumps(mcp_settings))
        stored = {name: copy.deepcopy(self.arm.connector(name)) for name in ("mcp1", "kusto-prod", "docs")}
        target = ["sre", "connector", "update", "-g", "rg", "--agent-name", "myagent", "-n"]
        for name, arguments, missing in (
                ("mcp1", ["--data-connector-type", "Mcp"], ["--data-source", "--identity", "--extended-properties"]),
                ("mcp1", ["--extended-properties", '{"note": "x"}'], ["--data-source", "--identity"]),
                ("mcp1", ["--identity", UAMI_ID], ["--data-source", "--extended-properties"]),
                ("mcp1", ["--set", "properties.extendedProperties.note=x"],
                 ["--data-source", "--identity", "--extended-properties"]),
                ("mcp1", ["--partner-type", "DynatraceMcp"], ["--data-source", "--identity", "--extended-properties"]),
                ("mcp1", ["--partner-type", "DynatraceMcp", "--data-source", "https://mcp.contoso.com/mcp",
                          "--extended-properties", "@" + full_settings], ["--identity"]),
                ("kusto-prod", ["--data-source", "https://prod.kusto.windows.net/db2"], ["--identity"]),
                ("docs", ["--extended-properties", '{"url": "https://new.contoso.com/"}', "--data-source", "null",
                          "--identity", "null"], ["knowledge"])):
            with self.subTest(name=name, arguments=arguments):
                self.arm.requests.clear()
                # --no-wait only skips Azure CLI's poll delay; the check runs before any PUT.
                code, _, logs = self._run(*target, name, *arguments, "--no-wait")
                self.assertNotEqual(code, 0)
                for flag in missing:
                    self.assertIn(flag, logs.errors)
                self.assertEqual(self.arm.sent("PUT"), [])
                self.assertEqual(self.arm.connector(name), stored[name])

        code, _, logs = self._run(
            *target, "mcp1", "--partner-type", "DynatraceMcp", "--data-source", "https://mcp.contoso.com/mcp",
            "--identity", UAMI_ID, "--extended-properties", "@" + full_settings)
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(self.arm.connector("mcp1")["properties"], {
            "dataConnectorType": "Mcp", "dataSource": "https://mcp.contoso.com/mcp", "identity": UAMI_ID,
            "extendedProperties": {**mcp_settings, "partnerType": "DynatraceMcp"},
            "provisioningState": "Succeeded",
        })

        self.arm.add_connector("kusto-dev", dataConnectorType="Kusto", dataSource="https://dev.kusto.windows.net/db")
        code, _, logs = self._run(
            *target, "kusto-dev", "--data-source", "https://dev.kusto.windows.net/db2", "--identity", "null")
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(self.arm.connector("kusto-dev")["properties"], {
            "dataConnectorType": "Kusto", "dataSource": "https://dev.kusto.windows.net/db2",
            "provisioningState": "Succeeded",
        })
        code, _, logs = self._run(
            *target, "kusto-prod", "--data-source", "https://prod.kusto.windows.net/db2",
            "--set", f"properties.identity={UAMI_ID}")
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(self.arm.connector("kusto-prod")["properties"]["identity"], UAMI_ID)

    def test_list_secret_prints_the_data_source(self):
        code, output, logs = self._run(
            "sre", "connector", "list-secret", "-g", "rg", "--agent-name", "myagent", "-n", "kusto-prod",
            "-o", "json")
        self.assertEqual(code, 0, logs.errors)
        properties = json.loads(output)["properties"]
        self.assertEqual(properties["dataSource"], "https://prod.kusto.windows.net/db")
        self.assertEqual(properties["identity"], UAMI_ID)

    def test_knowledge_file_is_sent_with_its_file_name_and_content_type(self):
        for file_name, content_type in (("runbook.md", "text/markdown"), ("main.tf", None)):
            with self.subTest(file_name):
                name = file_name.replace(".", "-")
                code, _, logs = self._run(
                    "sre", "knowledge", "create", "-g", "rg", "--agent-name", "myagent", "-n", name,
                    "--type", "file", "--file-path", self._file(file_name, "# Runbook\n"))
                self.assertEqual(code, 0, logs.errors)
                extended = self.arm.connector(name)["properties"]["extendedProperties"]
                self.assertEqual(extended["displayName"], file_name)
                self.assertEqual(extended.get("contentType"), content_type)

    def test_knowledge_file_the_agent_does_not_index_gets_a_warning(self):
        for file_name, warned in (("main.tf", True), ("RUNBOOK.MD", False)):
            with self.subTest(file_name):
                code, _, logs = self._run(
                    "sre", "knowledge", "create", "-g", "rg", "--agent-name", "myagent",
                    "-n", file_name.lower().replace(".", "-"), "--type", "file",
                    "--file-path", self._file(file_name, "resource x {}\n"))
                self.assertEqual(code, 0, logs.errors)
                self.assertEqual("--type text" in logs.warnings, warned, logs.warnings)

    def test_connector_table_shows_app_insights_by_its_portal_name(self):
        for name, wire_type in (("appi", "AppInsights"), ("appi2", "ApplicationInsights")):
            self.arm.add_connector(name, dataConnectorType=wire_type, dataSource="https://api.applicationinsights.io")
        code, output, logs = self._run(
            "sre", "connector", "list", "-g", "rg", "--agent-name", "myagent", "-o", "table")
        self.assertEqual(code, 0, logs.errors)
        rows = {line.split()[0]: line for line in output.splitlines()[2:] if line.strip()}
        for name in ("appi", "appi2"):
            self.assertIn("Application Insights", rows[name])

    def test_knowledge_commands_leave_other_connectors_alone(self):
        target = ["-g", "rg", "--agent-name", "myagent"]
        kusto = copy.deepcopy(self.arm.connector("kusto-prod"))
        for command in (
                ["knowledge", "delete", *target, "-n", "kusto-prod", "--yes"],
                ["knowledge", "show", *target, "-n", "kusto-prod"],
                ["knowledge", "create", *target, "-n", "kusto-prod", "--type", "webpage",
                 "--url", "https://x.example.com/", "--overwrite"]):
            with self.subTest(command=command[:2]):
                self.arm.requests.clear()
                code, output, logs = self._run("sre", *command)
                self.assertNotEqual(code, 0)
                self.assertIn("kusto-prod", logs.errors)
                self.assertEqual(output, "")
                self.assertEqual([verb for verb, _, _ in self.arm.requests], ["GET"])
                self.assertEqual(self.arm.connector("kusto-prod"), kusto)

        code, _, _ = self._run("sre", "knowledge", "show", *target, "-n", "missing")
        self.assertEqual(code, 3)

        code, output, logs = self._run("sre", "knowledge", "show", *target, "-n", "docs")
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(json.loads(output)["name"], "docs")
        code, _, logs = self._run("sre", "knowledge", "create", *target, "-n", "docs", "--type", "webpage",
                                  "--url", "https://new.contoso.com/", "--overwrite")
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(self.arm.connector("docs")["properties"]["extendedProperties"],
                         {"url": "https://new.contoso.com/"})
        code, _, logs = self._run("sre", "knowledge", "delete", *target, "-n", "docs", "--yes")
        self.assertEqual(code, 0, logs.errors)
        self.assertIsNone(self.arm.connector("docs"))

    def test_knowledge_data_source_stays_out_of_output_and_logs(self):
        secret = "PAT-3c1d-not-for-logs"
        data_source = f"https://user:{secret}@dev.azure.com/org/proj/_git/repo"
        arguments = ["sre", "knowledge", "create", "-g", "rg", "--agent-name", "myagent", "-n", "repo1",
                     "--type", "repository", "--data-source", "@" + self._file("ds.txt", data_source)]
        value_files = self.enterContext(tempfile.TemporaryDirectory())
        with patch("tempfile.tempdir", value_files):
            code, output, logs = self._run(*arguments, "--debug")
            self.assertEqual(code, 0, logs.errors)
            self.assertEqual(self.arm.connector("repo1")["properties"]["dataSource"], data_source)
            self.assertNotIn(secret, output + logs.everything)

            # A second create fails in the nested 'connector create' because the name is taken.
            code, output, logs = self._run(*arguments)
            self.assertNotEqual(code, 0)
            self.assertIn("already exists", logs.errors)
            self.assertNotIn(secret, output + logs.everything)
        for folder, _, names in os.walk(value_files):
            for name in names:
                with open(os.path.join(folder, name), encoding="utf-8", errors="replace") as handle:
                    self.assertNotIn(secret, handle.read())

    def test_oauth_dcr_create_points_to_the_portal_sign_in(self):
        code, _, logs = self._run(
            "sre", "connector", "create", "-g", "rg", "--agent-name", "myagent", "-n", "mcp-oauth",
            "--data-connector-type", "Mcp", "--mcp-endpoint", "https://mcp.contoso.com/mcp", "--oauth-dcr", "true")
        self.assertEqual(code, 0, logs.errors)
        self.assertEqual(self.arm.connector("mcp-oauth")["properties"]["extendedProperties"]["authType"], "SpecOAuth")
        self.assertIn(f"https://portal.azure.com/#@/resource{AGENT_ID}/connectors/mcp-oauth/overview", logs.warnings)


if __name__ == "__main__":
    unittest.main()

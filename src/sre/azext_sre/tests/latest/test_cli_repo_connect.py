"""'az sre repo connect' and 'az sre endpoint show' through the real Azure CLI.

Only the services are faked: ARM, the agent's own API, GitHub and Azure
DevOps answer from one in-memory store at requests' Session.send, which
both the AAZ pipeline and send_raw_request go through. Any other host fails
the test. The connections file is redirected to a temporary folder.
"""

import base64
import io
import json
import logging
import os
import re
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

from azext_sre import custom

TENANT = "33333333-3333-3333-3333-333333333333"
SUB_ONE = "11111111-1111-1111-1111-111111111111"
SUB_TWO = "22222222-2222-2222-2222-222222222222"
ENDPOINTS = {
    SUB_ONE: "https://myagent--a1b2c3d4.a1b2c3d4.swedencentral.azuresre.ai",
    SUB_TWO: "https://myagent--99999999.99999999.eastus2.azuresre.ai",
}
GITHUB_TOKEN = "fake_gh_env_GITHUB_TOKEN_2222"
OLD_GITHUB_TOKEN = "fake_gh_OLD_TOKEN_0000"
DEVICE_TOKEN = "fake_gh_device_TOKEN_4444"
FEED_PAT = "fake_feed_PAT_7777"
FEED = {"orgName": "contoso", "feedUrl": "https://pkgs.dev.azure.com/contoso/_packaging/main/nuget/v3/index.json",
        "feedType": "NuGet", "pat": FEED_PAT}
ARM_TOKEN = "fake_arm_entra_token"
ADO_TOKEN = "fake_ado_entra_token"
AGENT_PATH = re.compile(
    r"^/subscriptions/(?P<sub>[^/]+)/resourceGroups/(?P<rg>[^/]+)/providers/Microsoft\.App/agents/"
    r"(?P<agent>[^/]+)(?:/(?P<type>[^/]+)(?:/(?P<name>[^/]+))?)?$", re.IGNORECASE)


def _b64(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


class _Services:
    """In-memory ARM, agent API, GitHub and Azure DevOps."""

    def __init__(self):
        self.calls = []
        self.extensions = {}
        self.pats = {}
        self.pat_reply = None
        self.agent_api_reply = None
        self.interrupt = None

    def seed(self, extension_type, name, value, subscription=SUB_ONE):
        self.extensions[(subscription, extension_type, name.lower())] = {"name": name, "value": value}

    def value(self, extension_type, name, subscription=SUB_ONE):
        entry = self.extensions.get((subscription, extension_type, name.lower()))
        return entry and entry["value"]

    def writes(self):
        return [(method, url) for method, url, _ in self.calls if method in ("PUT", "POST", "PATCH", "DELETE")]

    def send(self, _session, request, **_kwargs):
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        self.calls.append((request.method, request.url, body))
        if self.interrupt and self.interrupt(request.method, request.url):
            raise KeyboardInterrupt
        parts = urlsplit(request.url)
        if parts.hostname == "management.azure.com":
            return self._arm(request, parts, body)
        for subscription, endpoint in ENDPOINTS.items():
            if parts.hostname == urlsplit(endpoint).hostname:
                return self._agent_api(request, parts, body, subscription)
        if parts.hostname == "github.com":
            return self._github(request, parts)
        if parts.hostname == "vssps.dev.azure.com":
            return self._vssps(request, parts, body)
        raise AssertionError(f"Unexpected request to {request.method} {request.url}")

    @staticmethod
    def _reply(request, status, payload=None):
        response = requests.Response()
        response.status_code = status
        response.reason = {200: "OK", 204: "No Content", 400: "Bad Request", 404: "Not Found"}.get(status, "Error")
        response._content = b"" if payload is None else json.dumps(payload).encode()
        response.raw = io.BytesIO(response._content)
        response.headers["Content-Type"] = "application/json; charset=utf-8"
        response.encoding = "utf-8"
        response.url = request.url
        response.request = request
        return response

    def _envelope(self, subscription, extension_type, entry):
        value = dict(entry["value"])
        if extension_type == "githubAuths" and value.get("pat"):
            value["pat"] = "******"  # ARM masks GitHub tokens; it echoes Azure DevOps PATs.
        agent_id = f"/subscriptions/{subscription}/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
        return {"id": f"{agent_id}/{extension_type}/{entry['name']}", "name": entry["name"],
                "type": f"microsoft.app/agents/{extension_type}", "properties": {"value": _b64(value)}}

    def _arm(self, request, parts, body):
        match = AGENT_PATH.match(parts.path)
        if not match:
            raise AssertionError(f"Unexpected ARM request {request.method} {request.url}")
        subscription, extension_type = match["sub"], match["type"]
        if match["rg"].lower() != "rg" or match["agent"].lower() != "myagent" or subscription not in ENDPOINTS:
            return self._reply(request, 404, {"error": {"code": "ResourceNotFound", "message": "Not found."}})
        if extension_type is None:
            if request.method != "GET":
                raise AssertionError(f"Unexpected agent request {request.method} {request.url}")
            return self._reply(request, 200, {
                "id": f"/subscriptions/{subscription}/resourceGroups/rg/providers/Microsoft.App/agents/myagent",
                "name": "myagent", "type": "Microsoft.App/agents", "location": "swedencentral",
                "properties": {"provisioningState": "Succeeded", "agentEndpoint": ENDPOINTS[subscription]},
            })
        if match["name"] is None:
            items = [self._envelope(subscription, extension_type, entry)
                     for (sub, kind, _), entry in self.extensions.items()
                     if sub == subscription and kind == extension_type]
            return self._reply(request, 200, {"value": items})
        name = unquote(match["name"])
        key = (subscription, extension_type, name.lower())
        if request.method == "PUT":
            value = json.loads(base64.b64decode(json.loads(body)["properties"]["value"]))
            self.extensions[key] = {"name": name, "value": value}
        if request.method == "DELETE":
            self.extensions.pop(key, None)
            return self._reply(request, 200)
        if key not in self.extensions:
            return self._reply(request, 404, {"error": {"code": "NotFound", "message": "Not found."}})
        return self._reply(request, 200, self._envelope(subscription, extension_type, self.extensions[key]))

    _AGENT_API = {"/api/v2/repos": "repositories", "/api/v2/github/domains": "githubAuths",
                  "/api/v2/azuredevops/orgs": "azureDevOpsAuths"}

    def _agent_api(self, request, parts, body, subscription):
        base, _, name = parts.path.rpartition("/")
        extension_type = self._AGENT_API.get(base)
        if extension_type is None:
            extension_type, name = self._AGENT_API.get(parts.path), None
        if extension_type is None:
            raise AssertionError(f"Unexpected agent API request {request.method} {request.url}")
        if name is None:
            items = [entry for (sub, kind, _), entry in self.extensions.items()
                     if sub == subscription and kind == extension_type]
            if extension_type == "repositories":
                return self._reply(request, 200, {"value": [
                    {"name": e["name"], "type": "CodeRepo", "properties": e["value"]} for e in items]})
            return self._reply(request, 200, {"values": [
                {"name": e["name"], "authType": e["value"].get("authType")} for e in items]})
        name = unquote(name)
        key = (subscription, extension_type, name.lower())
        if request.method == "GET":
            if key not in self.extensions:
                return self._reply(request, 404, {"message": "Not found."})
            entry = self.extensions[key]
            return self._reply(request, 200, {"name": entry["name"], "type": "CodeRepo", "properties": entry["value"]})
        if request.method != "PUT":
            raise AssertionError(f"Unexpected agent API request {request.method} {request.url}")
        payload = json.loads(body)
        value = payload["properties"] if extension_type == "repositories" else payload
        if self.agent_api_reply is not None:
            status, reply = self.agent_api_reply(extension_type, name, payload)
            if status != 200:
                return self._reply(request, status, reply)
        else:
            reply = {"success": True}
        self.extensions[key] = {"name": name, "value": value}
        return self._reply(request, 200, reply)

    def _github(self, request, parts):
        if parts.path == "/login/device/code":
            return self._reply(request, 200, {
                "device_code": "fake-device-code", "user_code": "WDJB-MJHT",
                "verification_uri": "https://github.com/login/device", "interval": 0, "expires_in": 900})
        if parts.path == "/login/oauth/access_token":
            return self._reply(request, 200, {"access_token": DEVICE_TOKEN})
        raise AssertionError(f"Unexpected GitHub request {request.method} {request.url}")

    def _vssps(self, request, parts, body):
        organization = parts.path.split("/")[1]
        query = parse_qs(parts.query)
        if request.method == "DELETE":
            self.pats[query["authorizationId"][0]]["revoked"] = True
            return self._reply(request, 204)
        if self.pat_reply is not None:
            return self._reply(request, 200, self.pat_reply)
        number = len(self.pats) + 1
        authorization_id = f"fake-authorization-id-{number:04d}"
        token = f"fake_ado_PAT_{number}555"
        self.pats[authorization_id] = {"organization": organization, "token": token, "revoked": False}
        return self._reply(request, 200, {"patToken": {
            "displayName": json.loads(body)["displayName"], "validTo": "2026-12-11T18:02:10.32Z",
            "scope": "vso.code", "authorizationId": authorization_id, "token": token,
        }, "patTokenError": "none"})


class _CliTestCase(unittest.TestCase):
    """Loads this checkout as the only extension, with two fake subscriptions."""

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        root = stack.enter_context(tempfile.TemporaryDirectory(ignore_cleanup_errors=True))
        self.config_dir = os.path.join(root, "cfg")
        os.makedirs(self.config_dir)
        with open(os.path.join(self.config_dir, "azureProfile.json"), "w", encoding="utf-8") as handle:
            json.dump({"subscriptions": [
                {"id": sub, "name": name, "state": "Enabled", "isDefault": sub == SUB_ONE, "tenantId": TENANT,
                 "homeTenantId": TENANT, "environmentName": "AzureCloud", "managedByTenants": [],
                 "user": {"name": "someone@contoso.com", "type": "user"}}
                for sub, name in ((SUB_ONE, "sub-one"), (SUB_TWO, "sub-two"))]}, handle)
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": self.config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_CORE_ONLY_SHOW_ERRORS": "no",
            "AZURE_CORE_NO_COLOR": "true",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
            "AZSRE_EXTENSION_ROUTE": "arm",
        }))
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(name, None)
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", self.config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        stack.enter_context(patch("azure.cli.core.util.open_page_in_browser", return_value=True))
        stack.enter_context(patch("time.sleep"))
        token = SimpleNamespace(token=ARM_TOKEN, expires_on=4102444800)
        credential = SimpleNamespace(get_token=lambda *a, **k: token, get_token_info=lambda *a, **k: token)
        stack.enter_context(patch(
            "azure.cli.core.aaz._command_ctx.AAZCommandCtx.get_login_credential", return_value=credential))
        stack.enter_context(patch(
            "azure.cli.core._profile.Profile.get_raw_token",
            lambda _self, resource=None, *args, **kwargs: (
                ("Bearer", f"fake_entra_token_for_{resource}", {}), SUB_ONE, TENANT)))
        self.services = _Services()
        stack.enter_context(patch.object(
            requests.sessions.Session, "send",
            lambda session, request, **kwargs: self.services.send(session, request, **kwargs)))
        stack.enter_context(patch.dict(custom._FEATURES_MEMORY, {}, clear=True))
        self.connections_file = os.path.join(root, "home", ".azure", "sreAgentConnections.json")
        stack.enter_context(patch.object(custom, "_CONNECTIONS_FILE", self.connections_file))
        real_invoke = custom._cli_invoke

        def nested_invoke(cli_ctx, *args, **kwargs):
            # Built-in command modules aren't loaded, so answer the one nested
            # 'az account' call; every 'az sre' call runs for real.
            if args[:2] == ("account", "get-access-token"):
                return {"accessToken": ADO_TOKEN, "tokenType": "Bearer"}
            return real_invoke(cli_ctx, *args, **kwargs)

        stack.enter_context(patch.object(custom, "_cli_invoke", nested_invoke))

    def invoke(self, *arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        # Azure CLI sets up its console log handlers once per process, on the
        # stderr of that moment, so point them at this run's stderr.
        handlers = [handler for name in ("", "cli") for handler in logging.getLogger(name).handlers
                    if isinstance(handler, logging.StreamHandler) and not isinstance(handler, logging.FileHandler)]
        previous = [handler.setStream(stderr) for handler in handlers]
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                try:
                    code = get_default_cli().invoke(list(arguments), out_file=stdout)
                except SystemExit as ex:
                    code = ex.code
                except KeyboardInterrupt:
                    code = "interrupted"
        finally:
            for handler, stream in zip(handlers, previous):
                if stream is not None:
                    handler.setStream(stream)
        return code, stdout.getvalue(), stderr.getvalue()

    def config_files_text(self):
        """Everything Azure CLI wrote under its config folder, including the
        per-command logs it keeps by default."""
        texts = []
        for path in Path(self.config_dir).rglob("*"):
            if path.is_file():
                texts.append(path.read_text(encoding="utf-8", errors="replace"))
        return "\n".join(texts)


class RepoConnectCliTests(_CliTestCase):

    CONNECT = ("sre", "repo", "connect", "--agent-name", "myagent", "--resource-group", "rg")

    def connect(self, repo_url, *extra, token=GITHUB_TOKEN):
        if token:
            os.environ["GITHUB_TOKEN"] = token
        return self.invoke(*self.CONNECT, "--repo-url", repo_url, *extra)

    def repo_url(self, name):
        value = self.services.value("repositories", name)
        return value and value["url"]

    def test_a_different_repository_with_the_same_name_is_not_replaced(self):
        cases = (
            ("https://github.com/orgA/api", "https://github.com/orgA/api", "https://github.com/orgB/api"),
            # A URL saved by an older version with a credential in it isn't echoed.
            ("https://x-access-token:fake_url_OLD_cred_9191@github.com/orgA/api", "https://github.com/orgA/api",
             "https://github.com/orgB/api"),
            # Browser URLs end in the branch, so their default names collide.
            ("https://github.com/contoso/web/tree/main", "https://github.com/contoso/web/tree/main",
             "https://github.com/contoso/api/tree/main"),
            ("https://dev.azure.com/contoso/proj/_git/api", "https://dev.azure.com/contoso/proj/_git/api",
             "https://dev.azure.com/contoso/other/_git/api"),
        )
        for stored, shown, new in cases:
            with self.subTest(new=new, stored=stored):
                self.services = _Services()
                name = new.rsplit("/", 1)[-1]
                kind = "GitHub" if "github.com" in stored else "AzureDevOps"
                self.services.seed("repositories", name, {"url": stored, "type": kind})
                self.services.seed("githubAuths", "github_com", {"authType": "Pat", "pat": OLD_GITHUB_TOKEN})
                code, stdout, stderr = self.connect(new)

                self.assertNotEqual(code, 0, stdout)
                self.assertIn(shown, stderr)
                self.assertIn("--display-name", stderr)
                self.assertIn("--overwrite", stderr)
                self.assertNotIn("fake_url_OLD_cred_9191", stderr)
                self.assertEqual(self.services.writes(), [], "Nothing may be written, and no PAT minted.")
                self.assertEqual(self.repo_url(name), stored)
                self.assertEqual(self.services.value("githubAuths", "github_com")["pat"], OLD_GITHUB_TOKEN)

    def test_overwrite_replaces_it_and_names_the_repositories_sharing_the_credential(self):
        self.services.seed("repositories", "api", {
            "url": "https://github.com/orgA/api", "type": "GitHub", "branch": "main",
            "sparseCheckoutPaths": ["src"], "feedCredentials": [FEED]})
        self.services.seed("repositories", "web", {"url": "https://github.com/orgA/web", "type": "GitHub"})
        self.services.seed("repositories", "ado", {
            "url": "https://dev.azure.com/contoso/proj/_git/ado", "type": "AzureDevOps"})
        self.services.seed("githubAuths", "github_com", {"authType": "Pat", "pat": OLD_GITHUB_TOKEN})

        code, stdout, stderr = self.connect("https://github.com/orgB/api", "--overwrite")

        self.assertEqual(code, 0, stderr)
        # Nothing is carried over from a different repository.
        self.assertEqual(self.services.value("repositories", "api"),
                         {"url": "https://github.com/orgB/api", "type": "GitHub", "description": "api"})
        self.assertEqual(self.services.value("githubAuths", "github_com")["pat"], GITHUB_TOKEN)
        shared = [line for line in stderr.splitlines() if "'web'" in line]
        self.assertTrue(shared, stderr)
        self.assertFalse(any("'ado'" in line for line in stderr.splitlines()), stderr)
        self.assertIn("https://github.com/orgA/api", stderr)
        self.assertEqual(json.loads(stdout)["repository"]["properties"]["value"]["url"], "https://github.com/orgB/api")

    def test_reconnecting_the_same_repository_needs_no_overwrite_and_keeps_its_settings(self):
        # An older URL with a credential in it, no 'type', and settings made outside the CLI.
        stored = {"url": "https://x-access-token:fake_url_OLD_cred_9191@github.com/orgA/api.git",
                  "description": "Orders API", "branch": "main", "sparseCheckoutPaths": ["src/orders"],
                  "feedCredentials": [FEED], "indexingEnabled": True}
        kept = dict(stored, url="https://github.com/orgA/api", type="GitHub")
        for route in ("arm", "direct"):
            with self.subTest(route=route):
                os.environ["AZSRE_EXTENSION_ROUTE"] = route
                self.services = _Services()
                self.services.seed("repositories", "api", stored)

                code, _, stderr = self.connect("https://github.com/orgA/api")
                self.assertEqual(code, 0, stderr)
                self.assertEqual(self.services.value("repositories", "api"), kept)

                code, _, stderr = self.connect("https://github.com/orgA/api", "--branch", "release")
                self.assertEqual(code, 0, stderr)
                self.assertEqual(self.services.value("repositories", "api"), dict(kept, branch="release"))

    def test_fields_the_agent_returns_as_null_are_left_out(self):
        self.services.seed("repositories", "api", {
            "url": "https://github.com/orgA/api", "type": "GitHub", "description": None, "branch": None,
            "sparseCheckoutPaths": None, "feedCredentials": None})

        code, _, stderr = self.connect("https://github.com/orgA/api")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.services.value("repositories", "api"),
                         {"url": "https://github.com/orgA/api", "type": "GitHub", "description": "api"})

    def test_a_kept_feed_pat_is_not_printed_or_logged(self):
        stored = {"url": "https://github.com/orgA/api", "type": "GitHub", "feedCredentials": [FEED]}
        for route in ("arm", "direct"):
            with self.subTest(route=route):
                os.environ["AZSRE_EXTENSION_ROUTE"] = route
                self.services = _Services()
                self.services.seed("repositories", "api", stored)

                code, stdout, stderr = self.connect("https://github.com/orgA/api", "--debug")

                self.assertEqual(code, 0, stderr)
                saved = self.services.value("repositories", "api")
                self.assertEqual(saved.get("feedCredentials"), [FEED])
                printed = json.loads(stdout)["repository"]["properties"]["value"]["feedCredentials"]
                self.assertEqual([feed["pat"] for feed in printed], ["******"])
                # Plain, and inside the base64 values ARM sends and receives.
                forms = [FEED_PAT, _b64(stored), _b64(saved)]
                forms += [json.loads(body)["properties"]["value"] for method, url, body in self.services.calls
                          if method == "PUT" and "/repositories/" in url]
                output = stdout + stderr + self.config_files_text()
                for form in forms:
                    self.assertNotIn(form, output)

    def test_feeds_whose_pat_the_agent_does_not_return_are_not_written_back(self):
        masked = dict(FEED, feedUrl="https://pkgs.dev.azure.com/contoso/_packaging/masked/nuget/v3/index.json",
                      pat="******")
        missing = {"orgName": "contoso", "feedType": "Npm",
                   "feedUrl": "https://pkgs.dev.azure.com/contoso/_packaging/missing/npm/registry/"}
        self.services.seed("repositories", "api", {
            "url": "https://github.com/orgA/api", "type": "GitHub", "feedCredentials": [masked, FEED, missing]})

        code, _, stderr = self.connect("https://github.com/orgA/api")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.services.value("repositories", "api").get("feedCredentials"), [FEED])
        warning = [line for line in stderr.splitlines() if masked["feedUrl"] in line]
        self.assertTrue(warning, stderr)
        self.assertIn(missing["feedUrl"], warning[0])
        self.assertNotIn(FEED["feedUrl"], warning[0])

    def test_saved_settings_that_are_not_valid_stop_it_before_sign_in(self):
        self.services.seed("repositories", "api", {
            "url": "https://github.com/orgA/api", "type": "GitHub", "sparseCheckoutPaths": "src/orders"})

        code, _, stderr = self.connect("https://github.com/orgA/api", token=None)

        self.assertNotEqual(code, 0)
        self.assertIn("saved settings of repository 'api' on agent 'myagent'", stderr)
        self.assertIn("sparseCheckoutPaths must be a JSON array of strings", stderr)
        self.assertNotIn("--value", stderr)
        self.assertNotIn("WDJB-MJHT", stderr)
        self.assertEqual(self.services.writes(), [])

    def test_the_check_runs_before_github_sign_in(self):
        self.services.seed("repositories", "api", {"url": "https://github.com/orgA/api", "type": "GitHub"})

        code, _, stderr = self.connect("https://github.com/orgB/api", token=None)

        self.assertNotEqual(code, 0)
        self.assertNotIn("WDJB-MJHT", stderr)
        self.assertFalse([url for _, url, _ in self.services.calls if "github.com/login" in url])

    def test_azure_devops_pat_expiry_is_reported(self):
        code, stdout, stderr = self.connect("https://dev.azure.com/contoso/proj/_git/repo", token=None)

        self.assertEqual(code, 0, stderr)
        minted = [json.loads(body) for method, url, body in self.services.calls
                  if method == "POST" and "/_apis/tokens/pats" in url]
        self.assertEqual(len(minted), 1)
        self.assertEqual(json.loads(stdout)["patExpiresOn"], "2026-12-11T18:02:10.32Z")
        warning = [line for line in stderr.splitlines() if "2026-12-11" in line]
        self.assertTrue(warning, stderr)
        self.assertIn("managed-identity", warning[0])

    def test_an_explicit_provider_still_needs_that_providers_host(self):
        cases = (
            ("AzureDevOps", "https://evilvisualstudio.com/contoso/proj/_git/repo"),
            ("AzureDevOps", "https://dev.azure.com.evil.example/contoso/proj/_git/repo"),
            ("GitHub", "https://ghe.contoso.example/org/repo"),
            ("GitHub", "https://dev.azure.com/contoso/proj/_git/repo"),
            (None, "https://evilvisualstudio.com/contoso/proj/_git/repo"),
            (None, "https://ghe.contoso.example/org/repo"),
        )
        for provider, url in cases:
            with self.subTest(provider=provider, url=url):
                self.services.calls.clear()
                extra = ("--provider", provider) if provider else ()
                code, _, stderr = self.connect(url, *extra)
                self.assertNotEqual(code, 0)
                self.assertEqual(self.services.calls, [], "No PAT may be minted and nothing written.")
                self.assertNotIn("Pass --provider", stderr)
        self.assertEqual(self.services.extensions, {})

    def test_repo_url_must_not_hide_another_host_or_carry_credentials(self):
        for url in (
            "https://evil.example\\@dev.azure.com/contoso/proj/_git/repo",
            "https://evil.example\\@github.com/contoso/api",
            "https://x-access-token:fake_url_cred_TOKEN_1212@github.com/contoso/api",
            "https://fake_url_cred_TOKEN_1212@github.com/contoso/api",
            "https://user:fake_url_cred_TOKEN_1212@dev.azure.com/contoso/proj/_git/repo",
            "http://github.com/contoso/api",
            "https://github.com/contoso/api\n",
        ):
            with self.subTest(url=url):
                self.services.calls.clear()
                code, stdout, stderr = self.connect(url)
                self.assertNotEqual(code, 0)
                self.assertEqual(self.services.calls, [])
                self.assertNotIn("fake_url_cred_TOKEN_1212", stdout + stderr)
        self.assertEqual(self.services.extensions, {})

    def test_azure_devops_clone_url_with_the_organization_as_user_still_works(self):
        code, _, stderr = self.connect("https://contoso@dev.azure.com/contoso/proj/_git/repo")

        self.assertEqual(code, 0, stderr)
        self.assertEqual(self.services.value("azureDevOpsAuths", "contoso")["authType"], "Pat")
        self.assertEqual(self.repo_url("repo"), "https://contoso@dev.azure.com/contoso/proj/_git/repo")

    def test_pat_token_error_reason_is_shown(self):
        self.services.pat_reply = {"patToken": None, "patTokenError": "patLifespanPolicyViolation"}

        code, _, stderr = self.connect("https://dev.azure.com/contoso/proj/_git/repo", token=None)

        self.assertNotEqual(code, 0)
        self.assertIn("patLifespanPolicyViolation", stderr)
        self.assertIn("--devops-auth-type managed-identity", stderr)
        self.assertFalse([url for method, url in self.services.writes() if "management.azure.com" in url])

    def test_secrets_echoed_by_the_agent_api_are_not_printed(self):
        os.environ["AZSRE_EXTENSION_ROUTE"] = "direct"
        self.services.agent_api_reply = lambda kind, name, payload: (
            (200, {"name": name, "auth": {"authType": "Pat", "pat": payload.get("pat")}})
            if kind != "repositories" else (200, {}))
        for url, secret in (("https://github.com/contoso/api", GITHUB_TOKEN),
                            ("https://dev.azure.com/contoso/proj/_git/repo", "fake_ado_PAT_1555")):
            with self.subTest(url=url):
                code, stdout, stderr = self.connect(url)
                self.assertEqual(code, 0, stderr)
                self.assertIn("******", stdout)
                self.assertNotIn(secret, stdout + stderr)
                self.assertNotIn(secret, self.config_files_text())

    def test_secrets_echoed_in_an_error_are_not_printed_or_logged(self):
        os.environ["AZSRE_EXTENSION_ROUTE"] = "direct"
        self.services.agent_api_reply = lambda kind, name, payload: (
            400, {"message": f"Invalid credential in request {json.dumps(payload)}"})
        for url, secret in (("https://github.com/contoso/api", GITHUB_TOKEN),
                            ("https://dev.azure.com/contoso/proj/_git/repo", "fake_ado_PAT_1555")):
            with self.subTest(url=url):
                code, stdout, stderr = self.connect(url)
                self.assertNotEqual(code, 0)
                self.assertIn("Invalid credential in request", stderr)
                self.assertNotIn(secret, stdout + stderr)
                logs = self.config_files_text()
                self.assertIn("Invalid credential in request", logs)
                self.assertNotIn(secret, logs)
        self.assertTrue(self.services.pats["fake-authorization-id-0001"]["revoked"])

    def test_pat_is_revoked_when_interrupted_while_saving_it(self):
        self.services.interrupt = lambda method, url: method == "PUT" and "/azureDevOpsAuths/" in url

        code, _, _ = self.connect("https://dev.azure.com/contoso/proj/_git/repo", token=None)

        self.assertNotEqual(code, 0)
        self.assertEqual(len(self.services.pats), 1)
        self.assertTrue(self.services.pats["fake-authorization-id-0001"]["revoked"])


class EndpointShowCliTests(_CliTestCase):

    SHOW = ("sre", "endpoint", "show", "--name", "myagent", "--resource-group", "rg")

    def saved(self):
        with open(self.connections_file, encoding="utf-8") as handle:
            return json.load(handle)

    def write_file(self, text, encoding="utf-8"):
        os.makedirs(os.path.dirname(self.connections_file), exist_ok=True)
        with open(self.connections_file, "w", encoding=encoding) as handle:
            handle.write(text)

    def test_same_named_agents_in_two_subscriptions_are_both_kept(self):
        for subscription in ("sub-one", "sub-two"):
            code, _, stderr = self.invoke(*self.SHOW, "--subscription", subscription)
            self.assertEqual(code, 0, stderr)

        endpoints = {entry["agentEndpoint"] for entry in self.saved().values()}
        self.assertEqual(endpoints, set(ENDPOINTS.values()))

    def test_entries_saved_by_older_versions_are_kept(self):
        older = {"rg2/other": {"name": "other", "resourceGroup": "rg2",
                               "agentEndpoint": "https://other.example.azuresre.ai",
                               "dataPlaneAudience": "https://azuresre.dev"}}
        self.write_file("\ufeff" + json.dumps(older), encoding="utf-8")

        code, stdout, stderr = self.invoke(*self.SHOW)

        self.assertEqual(code, 0, stderr)
        saved = self.saved()
        self.assertEqual(saved["rg2/other"], older["rg2/other"])
        self.assertIn(ENDPOINTS[SUB_ONE], [entry["agentEndpoint"] for entry in saved.values()])
        self.assertEqual(json.loads(stdout)["connectionsFile"], self.connections_file)

    def test_a_failed_write_leaves_the_file_as_it_was(self):
        original = json.dumps({"rg2/other": {"name": "other", "agentEndpoint": "https://other.example"}}, indent=2)
        self.write_file(original)
        attempts = []

        def disk_full(obj, handle, **kwargs):
            attempts.append(True)
            handle.write(json.dumps(obj, **kwargs)[:25])
            raise OSError(28, "No space left on device")

        failing_json = SimpleNamespace(**{name: getattr(json, name) for name in dir(json) if not name.startswith("__")})
        failing_json.dump = disk_full
        with patch.object(custom, "json", failing_json):
            code, _, stderr = self.invoke(*self.SHOW)

        self.assertTrue(attempts, "The write was never attempted.")
        self.assertNotEqual(code, 0)
        self.assertNotIn("Traceback", stderr)
        with open(self.connections_file, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(os.listdir(os.path.dirname(self.connections_file)), ["sreAgentConnections.json"])


if __name__ == "__main__":
    unittest.main()

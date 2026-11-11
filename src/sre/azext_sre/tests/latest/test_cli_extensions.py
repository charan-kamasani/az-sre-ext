"""Offline tests for the extension noun commands (tool, skill, hook,
instructions, subagent, plugin, automation) through the real Azure CLI.

Only Azure is faked, at requests' HTTPAdapter.send, which both
send_raw_request and the AAZ pipeline reach. The fake keeps one store behind
ARM and the agent's own API, so a test can check what a command wrote or
deleted on either route.
"""

import base64
import copy
import io
import json
import logging
import os
import shlex
import tempfile
import unittest
from collections import namedtuple
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from requests.structures import CaseInsensitiveDict

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

SUBSCRIPTION = "00000000-0000-0000-0000-000000000000"
AGENT_ID = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
ARM_HOST = "management.azure.com"
AGENT_HOST = "myagent--1a2b3c4d.5e6f.eastus2.azuresre.ai"
EXTENSION_API_VERSION = "2026-11-01-preview"
PAT = "PATSECRETzq81mx0vY7"
HEADER_TOKEN = "HDRSECRETk4Lw2pQ9rT"
FEED_URL = "https://pkgs.dev.azure.com/contoso/_packaging/feed/nuget/v3/index.json"

Noun = namedtuple("Noun", "words extension_type direct_route envelope_type value")

# The agent API's route and envelope type for each noun, as the portal uses them.
NOUNS = {
    "tool": Noun(("tool",), "tools", "tools", "ExtendedAgentTool",
                 {"type": "LinkTool", "description": "Docs", "template": "https://learn.microsoft.com/"}),
    "skill": Noun(("skill",), "skills", "skills", "Skill",
                  {"description": "Triage", "tools": [], "skillContent": "# Triage"}),
    "hook": Noun(("hook",), "hooks", "hooks", "GlobalHook",
                 {"eventType": "Stop", "activationMode": "always", "hook": {"type": "prompt", "prompt": "Sum up"}}),
    "instructions": Noun(("instructions",), "commonPrompts", "commonprompts", "CommonPrompt",
                         {"prompt": "Cite the runbook."}),
    "subagent": Noun(("subagent",), "subagents", None, None,
                     {"instructions": "Gather read-only evidence from the supplied files and report it. " * 2,
                      "handoffDescription": "Use for read-only evidence."}),
    "plugin marketplace": Noun(("plugin", "marketplace"), "pluginMarketplaces", "pluginMarketplaces", "Marketplace",
                               {"sourceType": "github", "sourceUrl": "contoso/sre-plugins"}),
    "plugin install": Noun(("plugin", "install"), "pluginInstallations", "pluginInstallations", "PluginInstallation",
                           {"marketplaceName": "contoso-plugins", "pluginName": "datadog",
                            "source": {"type": "relative", "repo": "contoso/sre-plugins", "url": "plugins/datadog"}}),
    "scheduled-task": Noun(("automation", "scheduled-task"), "scheduledTasks", "scheduledtasks", "ScheduledTask",
                           {"cronExpression": "0 9 * * 1-5", "agentPrompt": "Summarize overnight alerts"}),
    "http-trigger": Noun(("automation", "http-trigger"), "httpTriggers", "httpTriggers", "HttpTrigger",
                         {"agentPrompt": "Investigate the alert"}),
}
DIRECT_ROUTES = {noun.direct_route: noun for noun in NOUNS.values() if noun.direct_route}
ARM_TYPES = {noun.extension_type for noun in NOUNS.values()}

Request = namedtuple("Request", "method host path query body")


def _response(request, status, body=None, content_type="application/json"):
    response = requests.Response()
    response.status_code = status
    response.reason = {200: "OK", 202: "Accepted", 204: "No Content"}.get(status, "Fake error")
    response.url = request.url
    response.request = request
    response.encoding = "utf-8"
    if body is None:
        response._content = b""
        response.headers = CaseInsensitiveDict()
    else:
        if isinstance(body, str):
            body = body.encode()
        elif not isinstance(body, bytes):
            body = json.dumps(body).encode()
        response._content = body
        response.headers = CaseInsensitiveDict({"Content-Type": content_type})
    return response


def _encode(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


class FakeAgentService:
    """ARM and the agent's own API over one store keyed by (extension type, name)."""

    def __init__(self):
        self.store = {}
        self.requests = []
        self.arm_page_size = None
        self.next_link_host = ARM_HOST
        self.direct_list_key = "value"
        self.direct_put_answer = None
        self.trigger_answer = (200, {"success": True}, "application/json")

    def send(self, request, **kwargs):
        del kwargs
        url = urlsplit(request.url)
        body = request.body.decode() if isinstance(request.body, bytes) else request.body
        self.requests.append(Request(request.method, url.hostname, url.path, parse_qs(url.query), body))
        if url.hostname == ARM_HOST:
            return self._arm(request, url, body)
        if url.hostname == AGENT_HOST:
            return self._agent_api(request, url, body)
        raise AssertionError(f"Request to an unexpected host: {request.method} {request.url}")

    def _arm(self, request, url, body):
        path = url.path.rstrip("/")
        query = parse_qs(url.query)
        if path == AGENT_ID and request.method == "GET":
            return _response(request, 200, {
                "id": AGENT_ID, "name": "myagent", "properties": {"agentEndpoint": f"https://{AGENT_HOST}"}})
        if not path.startswith(AGENT_ID + "/"):
            return _response(request, 404, {"error": {"message": "fake ARM: no route"}})
        if query.get("api-version") != [EXTENSION_API_VERSION]:
            return _response(request, 400, {"error": {"message": "fake ARM: wrong api-version"}})
        segments = path[len(AGENT_ID) + 1:].split("/")
        if segments[0] not in ARM_TYPES or len(segments) > 2:
            return _response(request, 404, {"error": {"message": "fake ARM: no route"}})
        extension_type = segments[0]
        if len(segments) == 1:
            skip = int(query.get("$skiptoken", ["0"])[0])
            return self._collection(request, extension_type, lambda name, value: self._arm_item(
                extension_type, name, value), skip=skip)
        name = unquote(segments[1])
        if request.method == "PUT":
            value = json.loads(base64.b64decode(json.loads(body)["properties"]["value"]))
            self._save(extension_type, name, value)
        return self._item(request, extension_type, name, lambda value: self._arm_item(extension_type, name, value))

    def _agent_api(self, request, url, body):
        path = url.path.rstrip("/")
        if path.startswith("/api/v1/httptriggers/trigger/") and request.method == "POST":
            status, content, content_type = self.trigger_answer
            return _response(request, status, content, content_type)
        prefix = "/api/v2/extendedAgent/"
        segments = path[len(prefix):].split("/") if path.startswith(prefix) else []
        if not segments or segments[0] not in DIRECT_ROUTES or len(segments) > 2:
            return _response(request, 404, {"error": "fake agent API: no route"})
        noun = DIRECT_ROUTES[segments[0]]
        if len(segments) == 1:
            return self._collection(request, noun.extension_type, lambda name, value: {
                "name": name, "type": noun.envelope_type, "properties": value}, list_key=self.direct_list_key)
        name = unquote(segments[1])
        if request.method == "PUT":
            self._save(noun.extension_type, name, json.loads(body)["properties"])
            if self.direct_put_answer is not None:
                return _response(request, *self.direct_put_answer)
        return self._item(request, noun.extension_type, name, lambda value: {
            "name": name, "type": noun.envelope_type, "properties": value}, deleted_status=204)

    def _save(self, extension_type, name, value):
        if extension_type == "httpTriggers":
            value.setdefault("triggerUrl", f"https://{AGENT_HOST}/api/v1/httptriggers/trigger/{name}")
            value.setdefault("triggerEnabled", True)
        self.store[(extension_type, name)] = value

    @staticmethod
    def _arm_item(extension_type, name, value):
        return {"id": f"{AGENT_ID}/{extension_type}/{name}", "name": name,
                "type": f"Microsoft.App/agents/{extension_type}", "properties": {"value": _encode(value)}}

    def _item(self, request, extension_type, name, envelope, deleted_status=200):
        key = (extension_type, name)
        if request.method in ("GET", "PUT"):
            if key not in self.store:
                return _response(request, 404, {"error": {"message": "fake: not found"}})
            return _response(request, 200, envelope(copy.deepcopy(self.store[key])))
        if request.method == "DELETE":
            self.store.pop(key, None)
            return _response(request, deleted_status, None if deleted_status == 204 else {})
        return _response(request, 405, {"error": {"message": "fake: method not allowed"}})

    def _collection(self, request, extension_type, envelope, list_key="value", skip=0):
        names = sorted(name for (stored_type, name) in self.store if stored_type == extension_type)
        if request.method == "DELETE":
            # The worst case: a server that deletes everything it was pointed at.
            for name in names:
                del self.store[(extension_type, name)]
            return _response(request, 200, {})
        if request.method != "GET":
            return _response(request, 405, {"error": {"message": "fake: method not allowed"}})
        page = names[skip:skip + self.arm_page_size] if self.arm_page_size and list_key == "value" else names
        result = {list_key: [envelope(name, copy.deepcopy(self.store[(extension_type, name)])) for name in page]}
        if self.arm_page_size and skip + len(page) < len(names):
            result["nextLink"] = (f"https://{self.next_link_host}{AGENT_ID}/{extension_type}"
                                  f"?api-version={EXTENSION_API_VERSION}&$skiptoken={skip + len(page)}")
        return _response(request, 200, result)


def _fake_raw_token(profile, *args, **kwargs):
    del profile
    resource = args[0] if args else kwargs.get("resource")
    return ("Bearer", f"FAKE-TOKEN[{resource}]", {}), SUBSCRIPTION, "tenant"


def _base64_forms(secret):
    """The secret's text inside base64 at each of the three byte alignments."""
    forms = []
    for offset in range(3):
        encoded = base64.b64encode(b"\0" * offset + secret.encode()).decode()
        start = 4 if offset else 0
        usable = (len(secret) - (3 - offset) % 3) // 3 * 4
        forms.append(encoded[start:start + usable])
    return forms


class ExtensionCommandCliTests(unittest.TestCase):
    """Runs `az sre <noun> ...` through the real parser and command code
    with the checkout loaded as the only extension. Each command is run on
    the ARM route and on the agent's own API (AZSRE_EXTENSION_ROUTE)."""

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
        # Merging group help examples re-parses YAML on every invocation and
        # these tests never render help, so skip it to keep them fast.
        stack.enter_context(patch("azext_sre._help.apply_group_examples"))
        stack.enter_context(patch("azure.cli.core._profile.Profile.get_raw_token", _fake_raw_token))
        stack.enter_context(patch("azext_sre.custom._cli_invoke", self._nested_command))
        self.service = FakeAgentService()
        stack.enter_context(patch.object(
            requests.adapters.HTTPAdapter, "send",
            lambda adapter, request, **kwargs: self.service.send(request, **kwargs)))

    @staticmethod
    def _nested_command(cli_ctx, *args, **kwargs):
        del cli_ctx, kwargs
        if args[:3] == ("sre", "agent", "show"):
            return {"id": AGENT_ID, "name": "myagent"}
        raise AssertionError(f"Unexpected nested command: {args}")

    def _reset(self):
        self.service = FakeAgentService()

    def _az(self, *args, route="arm", debug=False):
        """Run 'az sre <args>' and return (exit code, stdout, logged errors)."""
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.DEBUG if debug else logging.ERROR)
        cli_logger = logging.getLogger("cli")
        previous_level = cli_logger.level
        argv = ["sre", *args] + (["--debug"] if debug else [])
        try:
            with patch.dict(os.environ, {"AZSRE_EXTENSION_ROUTE": route}), redirect_stdout(output), \
                    redirect_stderr(errors if debug else io.StringIO()), \
                    patch.object(cli_logger, "handlers", [capture]):
                try:
                    code = get_default_cli().invoke(argv, out_file=output)
                except SystemExit as ex:
                    code = ex.code
        finally:
            cli_logger.setLevel(previous_level)
        return code, output.getvalue(), errors.getvalue()

    def _command(self, noun, verb, *rest):
        return (*NOUNS[noun].words, verb, "-g", "rg", "--agent-name", "myagent", *rest)

    def _write(self, name, text):
        path = os.path.join(self.config_dir, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def _extension_requests(self):
        return [(r.method, r.path) for r in self.service.requests if r.path.rstrip("/") != AGENT_ID]

    def _puts(self):
        return [r for r in self.service.requests if r.method == "PUT"]

    @staticmethod
    def _own_path(noun, route):
        if route == "arm":
            return f"{AGENT_ID}/{noun.extension_type}"
        return f"/api/v2/extendedAgent/{noun.direct_route}"

    def test_each_noun_command_touches_only_its_own_extension_type(self):
        for name, noun in NOUNS.items():
            for route in ("arm", "direct") if noun.direct_route else ("arm",):
                with self.subTest(noun=name, route=route):
                    for other in NOUNS.values():
                        self.service.store[(other.extension_type, "x1")] = {"seed": other.extension_type}
                    own = self._own_path(noun, route) + "/x1"
                    seeded = copy.deepcopy(self.service.store)

                    def run(verb, *rest):
                        self.service.requests.clear()
                        code, out, err = self._az(*self._command(name, verb, *rest), route=route)
                        self.assertEqual(code, 0, err)
                        return out

                    run("create", "--name", "x1", "--value", json.dumps(noun.value), "--overwrite")
                    self.assertEqual(self._extension_requests(), [("PUT", own)])
                    self.assertEqual({k: v for k, v in self.service.store.items() if k != (noun.extension_type, "x1")},
                                     {k: v for k, v in seeded.items() if k != (noun.extension_type, "x1")})
                    saved = self.service.store[(noun.extension_type, "x1")]
                    self.assertNotIn("seed", saved)

                    shown = json.loads(run("show", "--name", "x1"))
                    self.assertEqual(self._extension_requests(), [("GET", own)])
                    self.assertEqual(shown["properties"]["value"], saved)

                    listed = json.loads(run("list"))
                    self.assertEqual(self._extension_requests(), [("GET", own[:-len("/x1")])])
                    self.assertEqual([item["name"] for item in listed], ["x1"])

                    run("delete", "--name", "x1", "--yes")
                    self.assertEqual(self._extension_requests(), [("GET", own), ("DELETE", own)])
                    seeded.pop((noun.extension_type, "x1"))
                    self.assertEqual(self.service.store, seeded)
                    self.service.store.clear()

    def test_names_that_address_a_collection_or_another_item_are_refused(self):
        value = json.dumps(NOUNS["tool"].value)
        cases = [("direct", name) for name in ("", ".", "..", "a/b", "a\\b")]
        cases += [("arm", name) for name in ("..", "a/b", "a\\b")]
        for route, name in cases:
            for verb, rest in (("create", ("--value", value, "--overwrite")), ("show", ()), ("delete", ("--yes",))):
                with self.subTest(route=route, name=name, verb=verb):
                    self.service.store[("tools", "x1")] = {"seed": "tools"}
                    self.service.requests.clear()
                    code, out, err = self._az(*self._command("tool", verb, "--name", name, *rest), route=route)
                    self.assertNotEqual(code, 0)
                    self.assertEqual(out.strip(), "")
                    self.assertIn("valid name", err)
                    self.assertEqual(self.service.requests, [])
                    self.assertEqual(self.service.store, {("tools", "x1"): {"seed": "tools"}})
        for name, noun in NOUNS.items():
            if noun.direct_route and name != "tool":
                with self.subTest(noun=name):
                    self.service.store[(noun.extension_type, "x1")] = {"seed": noun.extension_type}
                    self.service.requests.clear()
                    code, _, _ = self._az(*self._command(name, "delete", "--name", ".", "--yes"), route="direct")
                    self.assertNotEqual(code, 0)
                    self.assertEqual(self.service.requests, [])
                    self.assertIn((noun.extension_type, "x1"), self.service.store)

    def _private_marketplace(self, pat=PAT):
        return {"sourceType": "github", "sourceUrl": "contoso/private-plugins", "feedCredentials": [
            {"orgName": "contoso", "feedUrl": FEED_URL, "feedType": "NuGet", "pat": pat}]}

    def test_create_output_never_carries_the_credential(self):
        value_file = self._write("marketplace.json", json.dumps(self._private_marketplace()))
        answers = [("arm", None), ("direct", None), ("direct", (204,)), ("direct", (200, {})),
                   ("direct", (200, {"success": True}))]
        for route, answer in answers:
            with self.subTest(route=route, answer=answer):
                self._reset()
                self.service.direct_put_answer = answer
                code, out, err = self._az(*self._command(
                    "plugin marketplace", "create", "--name", "privmp", "--value", "@" + value_file, "--overwrite"),
                    route=route)
                self.assertEqual(code, 0, err)
                self.assertNotIn(PAT, out)
                shown = json.loads(out)
                self.assertEqual(shown["name"], "privmp")
                if answer is not None:
                    # The reply had no item, so the request isn't shown in its place.
                    self.assertNotIn("properties", shown)
                saved = self.service.store[("pluginMarketplaces", "privmp")]
                self.assertEqual(saved["feedCredentials"][0]["pat"], PAT)

    def test_reads_do_not_reveal_stored_credentials_in_output_or_debug_logs(self):
        http_tool = {"type": "HttpClientTool", "url": "https://api.contoso.com/status", "headers": [
            {"key": "Authorization", "value": f"Bearer {HEADER_TOKEN}"},
            {"key": "Accept", "value": "application/json"}]}
        for route in ("arm", "direct"):
            for args in (self._command("plugin marketplace", "show", "--name", "privmp"),
                         self._command("plugin marketplace", "list"),
                         self._command("tool", "show", "--name", "legacy-http"),
                         self._command("tool", "list"),
                         self._command("plugin marketplace", "delete", "--name", "privmp", "--yes")):
                with self.subTest(route=route, command=" ".join(args[:3])):
                    self._reset()
                    self.service.store[("pluginMarketplaces", "privmp")] = self._private_marketplace()
                    self.service.store[("tools", "legacy-http")] = copy.deepcopy(http_tool)
                    code, out, err = self._az(*args, route=route, debug=True)
                    self.assertEqual(code, 0, err)
                    for secret in (PAT, HEADER_TOKEN):
                        for form in (secret, *_base64_forms(secret)):
                            self.assertNotIn(form, out + err)
                    if args[0] == "tool":
                        self.assertIn("application/json", out)

    def test_a_masked_credential_is_not_written_back(self):
        masked = json.dumps(self._private_marketplace(pat="******"))
        for route in ("arm", "direct"):
            with self.subTest(route=route):
                self._reset()
                self.service.store[("pluginMarketplaces", "privmp")] = self._private_marketplace()
                code, _, err = self._az(*self._command(
                    "plugin marketplace", "create", "--name", "privmp", "--value", masked, "--overwrite"), route=route)
                self.assertNotEqual(code, 0)
                self.assertIn("pat", err)
                self.assertEqual(self._puts(), [])
                self.assertEqual(self.service.store[("pluginMarketplaces", "privmp")], self._private_marketplace())

    def test_skill_md_frontmatter_is_read_as_yaml(self):
        nested_name = self._write("SKILL.md", (
            "---\n"
            "name: real-name\n"
            "description: >\n"
            "  Checks service health\n"
            "  before escalating.\n"
            "tools: [kusto-query, log-search]\n"
            "metadata:\n"
            "  name: victim\n"
            "---\n"
            "# Service health\n"))
        spaced_name = self._write("PDF.md", "---\nname: PDF Processing\ndescription: Fills PDF forms\n---\nBody\n")
        victim = {"description": "Keep me", "tools": [], "skillContent": "# Victim"}
        for route in ("arm", "direct"):
            with self.subTest(route=route):
                self._reset()
                self.service.store[("skills", "victim")] = copy.deepcopy(victim)
                code, _, err = self._az(*self._command("skill", "create", "--file-path", nested_name, "--overwrite"),
                                        route=route)
                self.assertEqual(code, 0, err)
                self.assertEqual(len(self._puts()), 1)
                self.assertEqual(self.service.store[("skills", "victim")], victim)
                self.assertEqual(self.service.store[("skills", "real-name")], {
                    "description": "Checks service health before escalating.",
                    "tools": ["kusto-query", "log-search"],
                    "skillContent": "# Service health",
                })

                code, _, err = self._az(*self._command("skill", "create", "--file-path", spaced_name, "--name", "pdf"),
                                        route=route)
                self.assertEqual(code, 0, err)
                self.assertEqual(self.service.store[("skills", "pdf")]["description"], "Fills PDF forms")

        unquoted_colon = self._write("CPU.md", "---\nname: cpu\ndescription: Triage CPU: check processes\n---\nBody\n")
        self._reset()
        code, _, err = self._az(*self._command("skill", "create", "--file-path", unquoted_colon))
        self.assertNotEqual(code, 0)
        self.assertIn("line 3", err)
        self.assertNotIn("unexpected error", err)
        self.assertEqual(self.service.requests, [])

    def test_pre_tool_use_script_is_added_to_existing_hooks(self):
        script = self._write("readonly.py", "print('deny writes')\n")
        script_hook = {"type": "command", "matcher": "(?s:.*)", "timeout": 30, "failMode": "block",
                       "script": "print('deny writes')\n"}
        guard = {"type": "command", "matcher": "Bash.*", "timeout": 10, "failMode": "block", "script": "echo guard"}
        stop = {"type": "command", "matcher": ".*", "timeout": 5, "failMode": "allow", "script": "echo stop"}
        base = NOUNS["subagent"].value
        cases = (
            ({"PreToolUse": [guard], "Stop": [stop]}, {"PreToolUse": [guard, script_hook], "Stop": [stop]}),
            (None, {"PreToolUse": [script_hook]}),
        )
        for hooks, expected in cases:
            with self.subTest(hooks=hooks):
                self._reset()
                value = json.dumps({**base, "hooks": hooks})
                code, _, err = self._az(*self._command(
                    "subagent", "create", "--name", "sa1", "--value", value, "--pre-tool-use-script-file", script))
                self.assertEqual(code, 0, err)
                self.assertEqual(self.service.store[("subagents", "sa1")]["hooks"], expected)

        self._reset()
        code, _, err = self._az(*self._command(
            "subagent", "create", "--name", "sa1", "--value", json.dumps({**base, "hooks": []}),
            "--pre-tool-use-script-file", script))
        self.assertNotEqual(code, 0)
        self.assertIn("--value.hooks must be a JSON object", err)
        self.assertNotIn("unexpected error", err)
        self.assertEqual(self._puts(), [])

    def test_invoke_reports_a_plain_text_reply_instead_of_failing(self):
        trigger = {"agentPrompt": "p", "triggerUrl": f"https://{AGENT_HOST}/api/v1/httptriggers/trigger/alert",
                   "triggerEnabled": True}
        for route in ("arm", "direct"):
            with self.subTest(route=route):
                self._reset()
                self.service.store[("httpTriggers", "alert")] = trigger
                self.service.trigger_answer = (202, "Accepted", "text/plain")
                code, out, err = self._az(*self._command(
                    "http-trigger", "invoke", "--name", "alert", "--payload", '{"alert": "x"}'), route=route)
                self.assertEqual(code, 0, err)
                self.assertEqual(json.loads(out), {"statusCode": 202, "body": "Accepted"})
                posts = [r for r in self.service.requests if r.method == "POST"]
                self.assertEqual([(r.host, r.body) for r in posts], [(AGENT_HOST, '{"alert": "x"}')])

    def test_plugin_install_needs_marketplace_plugin_and_source(self):
        for route in ("arm", "direct"):
            for value, missing in (({"marketplaceName": "contoso-plugins", "pluginName": "datadog"}, "source"),
                                   ({}, "marketplaceName")):
                with self.subTest(route=route, value=value):
                    self._reset()
                    code, _, err = self._az(*self._command(
                        "plugin install", "create", "--name", "datadog", "--value", json.dumps(value)), route=route)
                    self.assertNotEqual(code, 0)
                    self.assertIn(missing, err)
                    self.assertEqual(self._puts(), [])
                    self.assertEqual(self.service.store, {})

    def _seed_tools(self, count):
        for index in range(count):
            self.service.store[("tools", f"t{index}")] = {"type": "LinkTool", "template": f"https://x/{index}"}
        return [f"t{index}" for index in range(count)]

    def test_list_returns_every_item(self):
        self._reset()
        names = self._seed_tools(5)
        self.service.arm_page_size = 2
        code, out, err = self._az(*self._command("tool", "list"), route="arm")
        self.assertEqual(code, 0, err)
        self.assertEqual([item["name"] for item in json.loads(out)], names)

        self._reset()
        names = self._seed_tools(3)
        self.service.direct_list_key = "values"
        code, out, err = self._az(*self._command("tool", "list"), route="direct")
        self.assertEqual(code, 0, err)
        self.assertEqual([item["name"] for item in json.loads(out)], names)

    def test_list_does_not_follow_a_next_page_on_another_host(self):
        self._reset()
        self._seed_tools(5)
        self.service.arm_page_size = 2
        self.service.next_link_host = "management.azure.com.attacker.example"
        code, _, _ = self._az(*self._command("tool", "list"), route="arm")
        self.assertNotEqual(code, 0)
        self.assertEqual({r.host for r in self.service.requests}, {ARM_HOST})


def _bash_command_lines(text):
    """Split an example into command lines the way bash reads them: a
    backslash-newline outside single quotes continues the line."""
    lines, line, quote, index = [], "", None, 0
    while index < len(text):
        char = text[index]
        if char == "\\" and quote != "'" and text[index + 1:index + 2] == "\n":
            index += 2
            continue
        if char == "\n" and quote is None:
            lines.append(line)
            line, index = "", index + 1
            continue
        if char == "\\" and quote != "'" and index + 1 < len(text):
            line += text[index:index + 2]
            index += 2
            continue
        if char in "'\"":
            quote = char if quote is None else (None if quote == char else quote)
        line += char
        index += 1
    lines.append(line)
    return lines


class HelpExampleValueTests(unittest.TestCase):
    """Help examples get copied into bash, so an inline --value must be JSON
    after bash's own quoting rules."""

    def test_inline_values_in_bash_examples_are_json(self):
        from azure.cli.core.mock import DummyCli
        from azext_sre import SreCommandsLoader
        from azext_sre._help import GROUP_EXAMPLES

        loader = SreCommandsLoader(cli_ctx=DummyCli())
        loader.load_command_table(None)
        examples = [(name, example) for name, command in loader.command_table.items()
                    for example in (command.help or {}).get("examples") or []]
        examples += [(name, example) for name, group in GROUP_EXAMPLES.items() for example in group]
        checked = 0
        for name, example in examples:
            title, text = example.get("name") or "", example.get("text") or ""
            if "powershell" in title.lower() or "<<" in text:
                continue
            for line in _bash_command_lines(text):
                if "--value" not in line:
                    continue
                arguments = shlex.split(line)
                for flag, value in zip(arguments, arguments[1:]):
                    if flag == "--value" and not value.startswith("@"):
                        checked += 1
                        with self.subTest(command=name, example=title):
                            json.loads(value)
        self.assertGreater(checked, 10)


if __name__ == "__main__":
    unittest.main()

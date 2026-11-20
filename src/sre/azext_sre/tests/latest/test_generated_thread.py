"""Generated data-plane `sre thread` commands, run through the real Azure CLI with a fake network."""

import io
import json
import logging
import os
import tempfile
import time
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension
from azure.core.credentials import AccessToken
from requests import Response


SUBSCRIPTION = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ARM_SCOPE = "https://management.core.windows.net//.default"
DATA_PLANE_SCOPE = "https://azuresre.dev/.default"
ENDPOINT = "https://myagent.hash.eastus2.azuresre.ai"


class _Credential:
    def get_token(self, *scopes, **kwargs):
        del kwargs
        token = {ARM_SCOPE: "arm-token", DATA_PLANE_SCOPE: "data-plane-token"}[scopes[0]]
        return AccessToken(token, int(time.time()) + 3600)


class GeneratedThreadCommandTests(unittest.TestCase):

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
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        stack.enter_context(patch(
            "azure.cli.core.commands.client_factory.get_subscription_id", return_value=SUBSCRIPTION))
        stack.enter_context(patch(
            "azure.cli.core._profile.Profile.get_login_credentials",
            return_value=(_Credential(), SUBSCRIPTION, "tenant"),
        ))
        stack.enter_context(patch("requests.adapters.HTTPAdapter.send", side_effect=self._send))
        self.requests = []
        self.endpoint = ENDPOINT
        self.status = 200
        self.response = {"id": "thread1", "futureField": {"kept": True}}

    def _send(self, request, **kwargs):
        del kwargs
        self.requests.append(request)
        url = urlparse(request.url)
        if url.hostname == "management.azure.com":
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.headers["Authorization"], "Bearer arm-token")
            self.assertEqual(
                url.path, f"/subscriptions/{SUBSCRIPTION}/resourceGroups/myrg/providers/Microsoft.App/agents/myagent")
            status, data = 200, {"location": "eastus2", "properties": {"agentEndpoint": self.endpoint}}
        else:
            self.assertEqual(f"https://{url.hostname}", ENDPOINT)
            self.assertEqual(request.headers["Authorization"], "Bearer data-plane-token")
            self.assertNotIn("api-version", url.query)
            status, data = self.status, self.response
        response = Response()
        response.status_code = status
        response._content = json.dumps(data).encode()  # pylint: disable=protected-access
        response.raw = io.BytesIO(response.content)
        response.headers["Content-Type"] = "application/json"
        response.request = request
        response.url = request.url
        return response

    def _run(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.ERROR)
        with redirect_stdout(output), redirect_stderr(io.StringIO()), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            code = get_default_cli().invoke(
                ["sre", "thread", *arguments, "-g", "myrg", "--agent-name", "myagent"], out_file=output)
        return code, output.getvalue(), errors.getvalue()

    def _invoke(self, *arguments):
        code, output, errors = self._run(*arguments)
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(self.requests), 2)
        return json.loads(output)

    def _last(self):
        return self.requests[-1], urlparse(self.requests[-1].url)

    def test_create_sends_message_and_subagent(self):
        self.status = 201
        self.assertEqual(self._invoke("create", "--message", "Why is checkout slow?", "--subagent", "triage"),
                         self.response)
        request, url = self._last()
        self.assertEqual((request.method, url.path), ("POST", "/api/v1/threads"))
        self.assertEqual(json.loads(request.body),
                         {"startMessage": {"text": "Why is checkout slow?", "agent": "triage"}})

    def test_create_omits_subagent_when_not_given(self):
        self.status = 201
        self._invoke("create", "--message", "hello")
        self.assertEqual(json.loads(self._last()[0].body), {"startMessage": {"text": "hello"}})

    def test_list_defaults_top_to_25_and_returns_value(self):
        self.response = {"value": [self.response]}
        self.assertEqual(self._invoke("list"), self.response["value"])
        request, url = self._last()
        self.assertEqual((request.method, url.path), ("GET", "/api/v1/threads"))
        self.assertEqual(parse_qs(url.query), {"top": ["25"]})

    def test_list_passes_paging_and_filter(self):
        self.response = {"value": []}
        self._invoke("list", "--top", "5", "--skip", "10", "--filter", "status eq 'Active'")
        self.assertEqual(parse_qs(self._last()[1].query),
                         {"top": ["5"], "skip": ["10"], "filter": ["status eq 'Active'"]})

    def test_show_escapes_thread_id(self):
        self.assertEqual(self._invoke("show", "--thread-id", "id/with space"), self.response)
        self.assertEqual(self._last()[1].path, "/api/v1/threads/id%2Fwith%20space")

    def test_untrusted_agent_endpoint_gets_no_token(self):
        for endpoint in ("https://attacker.example", "http://myagent.hash.eastus2.azuresre.ai",
                         "https://attacker.example\\@myagent.hash.eastus2.azuresre.ai"):
            with self.subTest(endpoint=endpoint):
                self.requests.clear()
                self.endpoint = endpoint
                code, _, errors = self._run("show", "--thread-id", "thread1")
                self.assertNotEqual(code, 0)
                self.assertIn("not an https endpoint on *.azuresre.ai", errors)
                self.assertEqual(len(self.requests), 1, "only the ARM lookup may be sent")


if __name__ == "__main__":
    unittest.main()

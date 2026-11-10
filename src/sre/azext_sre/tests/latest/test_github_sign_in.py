"""GitHub sign-in (OAuth device flow) for 'az sre repo connect', as a person
at a terminal experiences it: where the one-time code is written, when the
browser takes focus, and how failures are reported. GitHub and ARM are faked.
"""

import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
from azure.cli.core import get_default_cli
from azure.cli.core.azclierror import CLIError
from azure.cli.core.extension import DevExtension

from azext_sre.custom import _github_device_flow

USER_CODE = "WDJB-MJHT"
APPROVED = ({"error": "authorization_pending"}, {"access_token": "gho_test"})


def _fake_github(*token_replies):
    """Stand-in for requests.post: a device code, then the given token replies."""
    replies = iter(token_replies)

    def post(url, **kwargs):
        if url.endswith("/login/device/code"):
            payload = {
                "device_code": "device-code", "user_code": USER_CODE,
                "verification_uri": "https://github.com/login/device",
                "interval": 0, "expires_in": 900,
            }
        else:
            payload = next(replies)
        return SimpleNamespace(json=lambda: payload, raise_for_status=lambda: None)

    return post


class _Terminal(io.StringIO):
    """A console stream. Sign-in must never wait for typed input."""

    def isatty(self):
        return True

    def readline(self, *args):
        raise AssertionError("The sign-in waited for input.")


class GithubSignInTerminalTests(unittest.TestCase):

    def _sign_in(self, stderr, open_browser, post=None):
        with patch("sys.stdin", _Terminal()), patch("sys.stderr", stderr), \
                patch("requests.post", side_effect=post or _fake_github(*APPROVED)), \
                patch("time.sleep"), \
                patch("azure.cli.core.util.open_page_in_browser", side_effect=open_browser):
            return _github_device_flow()

    def test_code_is_on_screen_before_the_browser_takes_focus(self):
        stderr = _Terminal()
        code_shown_when_opened = []

        token = self._sign_in(
            stderr, lambda url: code_shown_when_opened.append(USER_CODE in stderr.getvalue()) or True)

        self.assertEqual(token, "gho_test")
        self.assertEqual(code_shown_when_opened, [True])

    def test_transport_failures_are_reported_as_cli_errors_not_tracebacks(self):
        def failing(exception):
            def post(url, **kwargs):
                raise exception
            return post

        server_error = requests.Response()
        server_error.status_code = 500
        proxy_page = SimpleNamespace(raise_for_status=lambda: None,
                                     json=lambda: json.loads("<html>Proxy sign-in</html>"))
        cases = (
            ("offline", failing(requests.exceptions.ConnectionError("getaddrinfo failed")), CLIError),
            ("timeout", failing(requests.exceptions.ConnectTimeout("timed out")), CLIError),
            ("server error", lambda url, **kwargs: server_error, CLIError),
            ("proxy page", lambda url, **kwargs: proxy_page, CLIError),
            # Azure CLI adds its own certificate and proxy guidance to these.
            ("certificate", failing(requests.exceptions.SSLError("self-signed")), requests.exceptions.SSLError),
        )
        for name, post, expected in cases:
            with self.subTest(name), self.assertRaises(expected):
                self._sign_in(_Terminal(), lambda url: True, post=post)


class GithubSignInCliTests(unittest.TestCase):
    """'az sre repo connect' through the real Azure CLI."""

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
        for name in ("GITHUB_TOKEN", "GH_TOKEN"):
            os.environ.pop(name, None)
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        stack.enter_context(patch("requests.post", side_effect=_fake_github(*APPROVED)))
        stack.enter_context(patch("time.sleep"))
        stack.enter_context(patch("azure.cli.core.util.open_page_in_browser", return_value=True))
        stack.enter_context(patch("azext_sre.custom._extension_resource_create", side_effect=self._create))

    @staticmethod
    def _create(cli_ctx, agent_name, resource_group, extension_type, name, value, overwrite=False):
        return {"name": name, "type": extension_type, "properties": {"value": json.loads(value)}}

    def test_only_show_errors_still_shows_the_one_time_code_and_keeps_stdout_json(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin", io.StringIO()), redirect_stdout(output), redirect_stderr(errors):
            try:
                code = get_default_cli().invoke([
                    "sre", "repo", "connect", "--agent-name", "myagent", "--resource-group", "myrg",
                    "--repo-url", "https://github.com/contoso/my-service", "--only-show-errors",
                ], out_file=output)
            except SystemExit as ex:
                code = ex.code

        self.assertEqual(code, 0, errors.getvalue())
        self.assertIn(USER_CODE, errors.getvalue())
        self.assertIn("repository", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()

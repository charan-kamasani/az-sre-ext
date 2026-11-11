"""Offline argument-enforcement tests through the real Azure CLI parser."""

import base64
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

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension


class CliArgumentEnforcementTests(unittest.TestCase):
    """Runs `az sre ...` through the real Azure CLI parser with this checkout
    loaded as the only extension. Each rejected argument list has an accepted
    twin that reaches the command handler, so a retired or renamed command
    fails here instead of passing as "not recognized".
    """

    AGENT_ID = "/subscriptions/sub/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"
    ASSIGNEE = "someone@contoso.com"
    SIGNED_IN_USER = "11111111-1111-1111-1111-111111111111"

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
        self.http = stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("CLI argument tests must not use the network."),
        ))
        stack.enter_context(patch("azext_sre.custom._cli_invoke", self._nested_command))
        self.nested_calls = []

    def tearDown(self):
        self.assertFalse(self.http.called, "A supposedly offline test attempted a network request.")

    def _nested_command(self, cli_ctx, *args, **kwargs):
        del cli_ctx, kwargs
        self.nested_calls.append(args)
        if args[:3] == ("sre", "agent", "show"):
            return {"id": self.AGENT_ID}
        if args[0] == "ad":
            raise AssertionError("CLI argument tests must not call Microsoft Graph.")
        if args[:2] == ("account", "get-access-token"):
            claims = base64.urlsafe_b64encode(json.dumps({"oid": self.SIGNED_IN_USER}).encode())
            return {"accessToken": f"e30.{claims.decode().rstrip('=')}.sig"}
        if args[:2] == ("account", "show"):
            return {"user": {"type": "user"}}
        if args[:3] == ("role", "assignment", "list"):
            return []
        return {}

    def _run(self, arguments):
        self.nested_calls.clear()
        output, errors = io.StringIO(), io.StringIO()
        # Keep only logged errors: help examples are printed to stderr, and
        # loader warnings depend on which Azure CLI packages are installed.
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.ERROR)
        with redirect_stdout(output), redirect_stderr(io.StringIO()), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            try:
                code = get_default_cli().invoke(arguments, out_file=output)
            except SystemExit as ex:
                code = ex.code
        return code, errors.getvalue()

    def _accepted_call(self, arguments):
        """Run valid arguments and return the last nested az call as (command, options)."""
        code, errors = self._run(arguments)
        self.assertEqual(code, 0, errors)
        self.assertTrue(self.nested_calls, "The command never reached its handler.")
        call = self.nested_calls[-1]
        return call[:3], dict(zip(call[3::2], call[4::2]))

    def _assert_rejected(self, arguments, *fragments):
        code, errors = self._run(arguments)
        self.assertNotEqual(code, 0, "Invalid arguments were accepted.")
        self.assertTrue(
            any(all(fragment in line for fragment in fragments) for line in errors.splitlines()),
            f"Expected an error naming {fragments}, got: {errors!r}",
        )
        self.assertEqual(self.nested_calls, [], "A nested az command ran despite invalid arguments.")

    def test_access_role_is_required_and_must_be_built_in(self):
        for verb, action, role, role_name in (
            ("grant", "create", "reader", "SRE Agent Reader"),
            ("revoke", "delete", "admin", "SRE Agent Administrator"),
        ):
            with self.subTest(verb=verb):
                arguments = [
                    "sre", "access", verb, "--agent-name", "myagent", "--resource-group", "myrg",
                    "--assignee", self.ASSIGNEE,
                ]
                command, options = self._accepted_call(arguments + ["--role", role])
                self.assertEqual(command, ("role", "assignment", action))
                self.assertEqual(options, {
                    "--role": role_name, "--assignee": self.ASSIGNEE, "--scope": self.AGENT_ID,
                })
                self._assert_rejected(arguments + ["--role", "bogus"], "--role", "bogus")
                self._assert_rejected(arguments, "--role", "required")

    def test_access_grant_requires_an_assignee(self):
        arguments = [
            "sre", "access", "grant", "--agent-name", "myagent", "--resource-group", "myrg",
            "--role", "author",
        ]
        command, options = self._accepted_call(arguments + ["--assignee-me"])
        self.assertEqual(command, ("role", "assignment", "create"))
        self.assertEqual(options, {
            "--assignee-object-id": self.SIGNED_IN_USER, "--assignee-principal-type": "User",
            "--role": "SRE Agent Author", "--scope": self.AGENT_ID,
        })
        self._assert_rejected(arguments, "--assignee")

    def test_knowledge_type_must_be_supported(self):
        arguments = [
            "sre", "knowledge", "create", "--agent-name", "myagent", "--resource-group", "myrg",
            "--name", "docs", "--url", "https://learn.microsoft.com/azure/",
        ]
        command, options = self._accepted_call(arguments + ["--type", "webpage"])
        self.assertEqual(command, ("sre", "connector", "create"))
        self.assertEqual(options["--data-connector-type"], "KnowledgeWebPage")
        self._assert_rejected(arguments + ["--type", "bogus"], "--type", "bogus")

    def test_connector_type_sends_managed_connectors_to_the_portal(self):
        # Only the command handler produces this message, so it needs no accepted twin.
        for verb in ("create", "update"):
            with self.subTest(verb=verb):
                self._assert_rejected(
                    ["sre", "connector", verb, "--agent-name", "myagent", "--resource-group", "myrg",
                     "--name", "outlook", "--data-connector-type", "Office 365 Outlook"],
                    "Set up Office 365 Outlook in the portal: Connectors > Add connector.",
                )

    def test_agent_url_token_only_goes_to_the_validated_host(self):
        sent = []

        def fake_send_raw_request(cli_ctx, method, url, **kwargs):
            del cli_ctx, kwargs
            sent.append((method, url))
            return SimpleNamespace(content=b"{}", json=lambda: {"value": []})

        arguments = ["sre", "response-plan", "list", "--agent-url"]
        with patch("azext_sre.custom.send_raw_request", fake_send_raw_request):
            # requests and urllib3 end the host at the backslash: attacker.example.
            self._assert_rejected(
                arguments + ["https://attacker.example\\@a.x.eastus2.azuresre.ai/api"], "--agent-url")
            self.assertEqual(sent, [], "--agent-url was rejected, but a token-bearing request was still sent.")
            code, errors = self._run(arguments + ["https://a.x.eastus2.azuresre.ai/ignored"])
        self.assertEqual(code, 0, errors)
        self.assertEqual(len(sent), 1)
        self.assertTrue(sent[0][1].startswith("https://a.x.eastus2.azuresre.ai/api/"), sent)

    def test_knowledge_overwrite_is_accepted_by_connector_create(self):
        from azure.cli.core.aaz import AAZCommand
        from azext_sre.custom import ConnectorCreate

        command, options = self._accepted_call([
            "sre", "knowledge", "create", "--agent-name", "myagent", "--resource-group", "myrg",
            "--name", "docs", "--url", "https://learn.microsoft.com/azure/", "--type", "webpage",
            "--overwrite",
        ])
        self.assertEqual(command, ("sre", "connector", "create"))
        nested = list(self.nested_calls[-1])
        self.assertIn("--overwrite", nested)

        seen = {}

        def fake_handler(cmd, command_args):
            AAZCommand._handler(cmd, command_args)
            seen["overwrite"] = cmd.ctx.args.overwrite.to_serialized_data()

        with patch.object(ConnectorCreate, "_handler", fake_handler):
            code, errors = self._run(nested)
        self.assertEqual(code, 0, errors)
        self.assertTrue(seen["overwrite"])


if __name__ == "__main__":
    unittest.main()

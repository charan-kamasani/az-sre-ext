"""'agent create'/'agent update' reject --action-configuration mode ReadOnly,
which the generated enum lists but the live service rejects with
(InvalidActionMode)."""

import io
import logging
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from azure.cli.core import get_default_cli
from azure.cli.core.extension import DevExtension

from azext_sre.custom import Create, Update


class ActionModeCliTests(unittest.TestCase):
    """Runs the real Azure CLI offline against this extension's source."""

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
        # Below both azure-core's Session.request and send_raw_request's Session.send.
        self.http = stack.enter_context(patch(
            "requests.adapters.HTTPAdapter.send",
            side_effect=AssertionError("Action-mode CLI tests must not use the network."),
        ))
        # A resolvable subscription lets 'agent create' reach its first side
        # effect offline: auto-creating a managed identity when no --mi-* flag
        # is given.
        stack.enter_context(patch(
            "azure.cli.core.commands.client_factory.get_subscription_id",
            return_value="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        ))
        self.create_identity = stack.enter_context(patch(
            "azext_sre.custom._create_user_assigned_identity",
            return_value="/subscriptions/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/resourceGroups/myrg"
            "/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myagent-identity",
        ))

    def tearDown(self):
        self.assertFalse(self.http.called, "A supposedly offline test attempted a network request.")

    def _invoke(self, *arguments):
        output, errors = io.StringIO(), io.StringIO()
        capture = logging.StreamHandler(errors)
        capture.setLevel(logging.WARNING)
        with redirect_stdout(output), redirect_stderr(errors), \
                patch.object(logging.getLogger("cli"), "handlers", [capture]):
            try:
                code = get_default_cli().invoke(list(arguments), out_file=output)
            except SystemExit as ex:
                code = ex.code
        return code, errors.getvalue()

    def test_readonly_mode_is_rejected_before_anything_is_created(self):
        for command in (("create", "--location", "eastus2"), ("update",)):
            for value in ("{mode:ReadOnly}", '{"mode": "readonly"}'):
                with self.subTest(command=command[0], value=value):
                    code, errors = self._invoke(
                        "sre", "agent", *command, "--name", "myagent", "--resource-group", "myrg",
                        "--action-configuration", value,
                    )
                    self.assertNotEqual(code, 0)
                    self.assertIn("--action-configuration", errors)
                    self.assertIn("Autonomous", errors)
                    self.assertIn("Review", errors)
        self.create_identity.assert_not_called()


class ActionModeChoicesTests(unittest.TestCase):

    def test_only_service_supported_modes_are_offered_and_accepted(self):
        for command in (Create, Update):
            with self.subTest(command=command.AZ_NAME):
                mode = command._build_arguments_schema().action_configuration.mode
                self.assertNotIn("ReadOnly", mode.enum.to_choices())
                self.assertEqual(mode.enum["review"], "Review")
                self.assertEqual(mode.enum["AUTONOMOUS"], "Autonomous")


if __name__ == "__main__":
    unittest.main()

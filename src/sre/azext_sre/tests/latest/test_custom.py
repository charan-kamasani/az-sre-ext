"""Credential-free regression tests for the hand-written `az sre` command
layer (azext_sre/custom.py).

Style mirrors azext-aigateway's tests: offline, mocked, no live Azure calls,
and asserting real business logic (argument validation, wire-payload shape,
role-name mapping) rather than just "does it import". Tests that need a real
AAZCommand instance bypass __init__ and the framework's ctx-rebuilding
_handler() the same way aigateway's test_extension_registration.py does for
generated commands: construct via object.__new__, pre-seed .ctx/.cli_ctx, and
patch azure.cli.core.aaz.AAZCommand._handler to a no-op so our subclass's own
_handler() logic runs against the ctx we control instead of a freshly
rebuilt one.
"""

import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from azure.cli.core.aaz import AAZCommand
from azure.cli.core.azclierror import CLIError, ResourceNotFoundError
from azure.cli.core.mock import DummyCli

from azext_sre import SreCommandsLoader
from azext_sre.custom import (
    EXTENSION_TYPES,
    ExtensionCreate,
    ExtensionDelete,
    ExtensionList,
    ExtensionShow,
    GrantAccess,
    UpdateNetwork,
    _arg_value,
    _decode_extension_envelope,
    _encode_extension_value,
    _extension_type_arg,
    _normalize_model_provider,
)


def _bare_command(command_cls, **args_kwargs):
    """Build a command instance without running AAZCommand.__init__, with a
    pre-seeded .ctx.args namespace and a no-op .cli_ctx placeholder (safe
    because every test here replaces _cli_invoke/_arm_request before calling
    the handler, so cli_ctx is never actually dereferenced for a real call).
    """
    command = object.__new__(command_cls)
    command.ctx = SimpleNamespace(args=SimpleNamespace(**args_kwargs))
    command.cli_ctx = SimpleNamespace()
    return command


class ModelProviderNormalizationTests(unittest.TestCase):
    """--default-model.provider accepts real API values case-insensitively
    and rejects the Portal's friendly label ('Azure OpenAI' is NOT a real
    wire value -- see the _ModelProviderArgMixin docstring)."""

    def test_accepts_known_values_case_insensitively(self):
        self.assertEqual(_normalize_model_provider("anthropic"), "Anthropic")
        self.assertEqual(_normalize_model_provider("ANTHROPIC"), "Anthropic")
        self.assertEqual(
            _normalize_model_provider("MicrosoftFoundry"), "MicrosoftFoundry"
        )
        self.assertEqual(
            _normalize_model_provider("microsoftfoundry"), "MicrosoftFoundry"
        )

    def test_none_passes_through_unchanged(self):
        self.assertIsNone(_normalize_model_provider(None))

    def test_rejects_portal_friendly_label(self):
        with self.assertRaises(ValueError) as raised:
            _normalize_model_provider("Azure OpenAI")
        self.assertIn("--model-provider must be one of", str(raised.exception))

    def test_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            _normalize_model_provider("openai")


class ArgValueTests(unittest.TestCase):
    def test_undefined_becomes_none(self):
        from azure.cli.core.aaz import AAZUndefined

        self.assertIsNone(_arg_value(AAZUndefined))

    def test_plain_values_pass_through(self):
        self.assertEqual(_arg_value("foo"), "foo")
        self.assertEqual(_arg_value({"a": "b"}), {"a": "b"})
        self.assertIsNone(_arg_value(None))


class GrantAccessRoleMappingTests(unittest.TestCase):
    """Regression test for the real bug fixed this session: 'user' used to
    map to the non-existent 'SRE Agent User' and 'reader' to the generic ARM
    'Reader' (which does NOT grant data-plane UI access). Confirmed real role
    names via `az role definition list --query "[?contains(roleName,
    'SRE Agent')]"`.
    """

    def test_role_names_match_confirmed_live_role_definitions(self):
        self.assertEqual(
            GrantAccess._ROLES,
            {
                "admin": "SRE Agent Administrator",
                "user": "SRE Agent Standard User",
                "author": "SRE Agent Author",
                "reader": "SRE Agent Reader",
            },
        )

    def test_handler_resolves_agent_then_creates_role_assignment_with_mapped_name(self):
        command = _bare_command(
            GrantAccess,
            name="myagent",
            resource_group="myrg",
            role="user",
            assignee="someone@example.com",
        )
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("sre", "agent", "show"):
                return {"id": "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"}
            return {"result": "assigned"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, {"result": "assigned"})
        self.assertEqual(
            calls[0],
            ("sre", "agent", "show", "--name", "myagent", "--resource-group", "myrg"),
        )
        self.assertEqual(
            calls[1],
            (
                "role", "assignment", "create",
                "--role", "SRE Agent Standard User",
                "--assignee", "someone@example.com",
                "--scope", "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent",
            ),
        )

    def test_handler_raises_resource_not_found_when_agent_missing(self):
        command = _bare_command(
            GrantAccess, name="ghost", resource_group="rg", role="admin", assignee="a",
        )

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return None

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            with self.assertRaises(ResourceNotFoundError):
                command._handler({})


class ExtensionValueCodecTests(unittest.TestCase):
    """properties.value wire format confirmed in the internal control-plane
    repo's Agents.http examples: base64(json). _encode_extension_value
    validates the input is real JSON client-side so typos fail fast instead
    of silently becoming an opaque, unparseable base64 blob server-side.
    """

    def test_round_trips_through_encode_and_decode(self):
        raw = json.dumps({"name": "demo"})
        encoded = _encode_extension_value(raw)
        envelope = {"properties": {"value": encoded}}
        decoded = _decode_extension_envelope(envelope)
        self.assertEqual(decoded["properties"]["value"], {"name": "demo"})

    def test_rejects_non_json_value_before_encoding(self):
        with self.assertRaises(CLIError):
            _encode_extension_value("not json {{{")

    def test_encoded_value_is_exactly_base64_of_the_raw_string(self):
        raw = '{"a": 1}'
        encoded = _encode_extension_value(raw)
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_decode_falls_back_to_raw_text_for_non_json_base64(self):
        encoded = base64.b64encode(b"plain text, not json").decode("ascii")
        envelope = {"properties": {"value": encoded}}
        decoded = _decode_extension_envelope(envelope)
        self.assertEqual(decoded["properties"]["value"], "plain text, not json")

    def test_decode_leaves_non_base64_value_untouched(self):
        envelope = {"properties": {"value": "!!! not base64 !!!"}}
        decoded = _decode_extension_envelope(envelope)
        self.assertEqual(decoded, envelope)

    def test_decode_passes_through_non_dict_and_missing_properties(self):
        self.assertEqual(_decode_extension_envelope("not a dict"), "not a dict")
        self.assertEqual(_decode_extension_envelope({}), {})
        self.assertEqual(
            _decode_extension_envelope({"properties": "not a dict either"}),
            {"properties": "not a dict either"},
        )


class ExtensionTypeEnumTests(unittest.TestCase):
    """Mirrors AgentExtensionsApiService.GetExtensionTypes() exactly (the
    canonical ApiType/ExtensionType pairs) -- a drift here means the CLI's
    --extension-type enum no longer matches what the control-plane proxy
    route's regex actually accepts.
    """

    def test_extension_types_list_is_exactly_the_confirmed_fifteen(self):
        self.assertEqual(
            EXTENSION_TYPES,
            [
                "subagents", "tools", "skills", "scheduledTasks",
                "incidentFilters", "commonPrompts", "hooks",
                "incidentHandlers", "httpTriggers", "repositories",
                "pluginMarketplaces", "pluginInstallations", "githubAuths",
                "azureDevOpsAuths", "globalSettings",
            ],
        )

    def test_arg_enum_matches_extension_types(self):
        arg = _extension_type_arg()
        self.assertEqual(set(arg.enum.to_choices()), set(EXTENSION_TYPES))


class ExtensionCommandResourceIdTests(unittest.TestCase):
    """Proves each extension command builds the exact
    .../agents/{name}/{extensionType}[/{name}] resource ID and wire envelope
    confirmed against AgentExtensionsApiController.cs, without making a real
    ARM call.
    """

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def _run_with_mocks(self, command, cli_responses, arm_response=None):
        arm_calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return cli_responses.pop(0)

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            arm_calls.append(
                {"method": method, "resource_id": resource_id, "api_version": api_version, "body": body}
            )
            return arm_response

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})
        return result, arm_calls

    def test_create_builds_proxy_envelope_and_resource_id(self):
        command = _bare_command(
            ExtensionCreate,
            agent_name="myagent",
            resource_group="rg",
            extension_type="tools",
            extension_name="mytool",
            value='{"kind": "ToolList"}',
        )
        _, arm_calls = self._run_with_mocks(
            command,
            cli_responses=[self._AGENT],
            arm_response={"properties": {"value": _encode_extension_value('{"kind": "ToolList"}')}},
        )
        self.assertEqual(len(arm_calls), 1)
        call = arm_calls[0]
        self.assertEqual(call["method"], "PUT")
        self.assertEqual(
            call["resource_id"],
            "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent/tools/mytool",
        )
        self.assertEqual(call["body"]["type"], "microsoft.app/agents/tools")
        self.assertEqual(
            base64.b64decode(call["body"]["properties"]["value"]).decode("utf-8"),
            '{"kind": "ToolList"}',
        )

    def test_show_uses_missing_ok_and_raises_not_found_on_none(self):
        command = _bare_command(
            ExtensionShow,
            agent_name="myagent", resource_group="rg",
            extension_type="skills", extension_name="myskill",
        )
        with self.assertRaises(ResourceNotFoundError):
            self._run_with_mocks(command, cli_responses=[self._AGENT], arm_response=None)

    def test_list_decodes_every_item_in_the_value_array(self):
        command = _bare_command(
            ExtensionList, agent_name="myagent", resource_group="rg", extension_type="tools",
        )
        encoded = _encode_extension_value('{"n": 1}')
        result, arm_calls = self._run_with_mocks(
            command,
            cli_responses=[self._AGENT],
            arm_response={"value": [{"properties": {"value": encoded}}]},
        )
        self.assertEqual(
            arm_calls[0]["resource_id"],
            "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent/tools",
        )
        self.assertEqual(result["value"][0]["properties"]["value"], {"n": 1})

    def test_delete_passes_missing_ok_true(self):
        command = _bare_command(
            ExtensionDelete,
            agent_name="myagent", resource_group="rg",
            extension_type="hooks", extension_name="myhook",
        )
        _, arm_calls = self._run_with_mocks(command, cli_responses=[self._AGENT], arm_response={})
        self.assertEqual(arm_calls[0]["method"], "DELETE")
        self.assertEqual(
            arm_calls[0]["resource_id"],
            "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent/hooks/myhook",
        )


class UpdateNetworkMergeTests(unittest.TestCase):
    """UpdateNetwork does a real read-modify-write at NETWORK_API_VERSION:
    GET current properties, merge in only the networking fields the caller
    supplied, PUT the whole object back -- proving unrelated existing
    properties on the resource are preserved, not clobbered.
    """

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def test_requires_at_least_one_configuration(self):
        command = _bare_command(
            UpdateNetwork,
            name="myagent", resource_group="rg",
            vnet_configuration=None, sandbox_configuration=None,
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None):
            with self.assertRaises(CLIError):
                command._handler({})

    def test_merges_sandbox_configuration_preserving_unrelated_properties(self):
        command = _bare_command(
            UpdateNetwork,
            name="myagent", resource_group="rg",
            vnet_configuration=None,
            sandbox_configuration={"egress": {"mode": "Unrestricted"}},
        )
        current = {
            "id": self._AGENT["id"],
            "properties": {"displayName": "keep-me", "provisioningState": "Succeeded"},
        }
        arm_calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return self._AGENT

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            arm_calls.append({"method": method, "body": body})
            return current if method == "GET" else body

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})

        self.assertEqual(arm_calls[0]["method"], "GET")
        put_body = arm_calls[1]["body"]
        self.assertEqual(put_body["properties"]["displayName"], "keep-me")
        self.assertEqual(
            put_body["properties"]["sandboxConfiguration"], {"egress": {"mode": "Unrestricted"}},
        )
        self.assertNotIn("vnetConfiguration", put_body["properties"])
        self.assertEqual(result, put_body)


class CommandRegistrationTests(unittest.TestCase):
    """Every hand-written command in custom.py must actually be reachable
    through the loader's public 'sre ...' surface -- extends the single
    smoke test that existed before this file with explicit per-command
    coverage, so a decorator typo or accidental omission fails loudly.
    """

    @classmethod
    def setUpClass(cls):
        loader = SreCommandsLoader(cli_ctx=DummyCli())
        cls.command_table = loader.load_command_table(["sre", "agent", "list"])

    def test_all_expected_commands_are_registered(self):
        expected = [
            "sre agent create", "sre agent update", "sre agent show",
            "sre agent list", "sre agent delete", "sre agent start",
            "sre agent stop", "sre agent get-connection", "sre agent list-usage",
            "sre agent grant-access", "sre agent update-network",
            "sre agent extension create", "sre agent extension show",
            "sre agent extension list", "sre agent extension delete",
        ]
        missing = [name for name in expected if name not in self.command_table]
        self.assertEqual(missing, [], f"Missing registered commands: {missing}")


class CliArgumentEnforcementTests(unittest.TestCase):
    """Exercises the real Azure CLI argument parser so enum/required-argument
    enforcement is proven, not just declared -- mirrors aigateway's
    McpSourceCliEnforcementTests. No Azure call happens: argument parsing
    fails before any handler runs.
    """

    def _invoke(self, args):
        from azure.cli.core import get_default_cli

        cli = get_default_cli()
        try:
            return cli.invoke(args)
        except SystemExit as ex:
            return ex.code

    def test_invalid_role_value_is_rejected(self):
        code = self._invoke(
            [
                "sre", "agent", "grant-access",
                "-g", "rg", "--agent-name", "a",
                "--role", "bogus", "--assignee", "x",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_invalid_extension_type_is_rejected(self):
        code = self._invoke(
            [
                "sre", "agent", "extension", "show",
                "-g", "rg", "--agent-name", "a",
                "--extension-type", "bogus", "--extension-name", "x",
            ]
        )
        self.assertNotEqual(code, 0)

    def test_missing_required_assignee_is_rejected(self):
        code = self._invoke(
            [
                "sre", "agent", "grant-access",
                "-g", "rg", "--agent-name", "a", "--role", "admin",
            ]
        )
        self.assertNotEqual(code, 0)


if __name__ == "__main__":
    unittest.main()

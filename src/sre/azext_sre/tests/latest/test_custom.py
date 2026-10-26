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
    Create,
    ConnectorCreate,
    ExtensionCreate,
    ExtensionDelete,
    ExtensionList,
    ExtensionShow,
    GrantAccess,
    UpdateNetwork,
    _annotate_connector_consent_status,
    _arg_value,
    _connector_consent_status,
    _decode_extension_envelope,
    _encode_extension_value,
    _extension_type_arg,
    _normalize_data_connector_type,
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
        with self.assertRaises(CLIError) as raised:
            _normalize_model_provider("Azure OpenAI")
        self.assertIn("--model-provider must be one of", str(raised.exception))

    def test_rejects_unknown_value(self):
        with self.assertRaises(CLIError):
            _normalize_model_provider("openai")


class DataConnectorTypeNormalizationTests(unittest.TestCase):
    """--data-connector-type accepts real API values case-insensitively and
    rejects anything outside the known set (same pattern as
    --model-provider -- see _DataConnectorTypeArgMixin docstring)."""

    def test_accepts_known_values_case_insensitively(self):
        self.assertEqual(_normalize_data_connector_type("kusto"), "Kusto")
        self.assertEqual(_normalize_data_connector_type("KUSTO"), "Kusto")
        self.assertEqual(_normalize_data_connector_type("Mcp"), "Mcp")
        self.assertEqual(_normalize_data_connector_type("mcp"), "Mcp")
        self.assertEqual(_normalize_data_connector_type("outlook"), "Outlook")
        self.assertEqual(_normalize_data_connector_type("TEAMS"), "Teams")

    def test_accepts_newly_confirmed_values_case_insensitively(self):
        # Confirmed via KnownDataConnectorTypes.cs and DataConnectorValidator.cs
        # in the control-plane source -- these were previously missing from
        # our enum even though the service has always accepted them.
        self.assertEqual(_normalize_data_connector_type("icm"), "Icm")
        self.assertEqual(_normalize_data_connector_type("ICM"), "Icm")
        self.assertEqual(_normalize_data_connector_type("kustoclient"), "KustoClient")
        self.assertEqual(_normalize_data_connector_type("KustoClient"), "KustoClient")
        self.assertEqual(_normalize_data_connector_type("dgrep"), "Dgrep")
        self.assertEqual(_normalize_data_connector_type("DGREP"), "Dgrep")

    def test_accepts_knowledge_item_types_case_insensitively(self):
        # These four are multiplexed over the same connectors route and
        # carry their payload in --extended-properties instead of
        # --data-source (DataConnectorValidator.KnowledgeConnectorTypeNames).
        self.assertEqual(_normalize_data_connector_type("knowledgetext"), "KnowledgeText")
        self.assertEqual(_normalize_data_connector_type("KnowledgeFile"), "KnowledgeFile")
        self.assertEqual(_normalize_data_connector_type("KNOWLEDGEWEBPAGE"), "KnowledgeWebPage")
        self.assertEqual(_normalize_data_connector_type("knowledgerepository"), "KnowledgeRepository")

    def test_none_passes_through_unchanged(self):
        self.assertIsNone(_normalize_data_connector_type(None))

    def test_rejects_unknown_value(self):
        with self.assertRaises(CLIError) as raised:
            _normalize_data_connector_type("pagerduty")
        self.assertIn(
            "--data-connector-type must be one of", str(raised.exception)
        )


class ConnectorConsentStatusTests(unittest.TestCase):
    """Consent surfacing (issue #10): confirmed via
    AAPT-SREAgent-ControlPlane's DataConnectorView.cs and
    McpEntraConnectorReference.cs that an EntraOAuth-backed Mcp connector's
    properties.extendedProperties always has authType=="EntraOAuth", plus
    an entraOAuth key that is null until browser OAuth consent completes."""

    def test_pending_consent_when_entra_oauth_is_null(self):
        self.assertEqual(
            _connector_consent_status({"authType": "EntraOAuth", "entraOAuth": None}),
            "PendingConsent",
        )

    def test_consented_when_entra_oauth_is_populated(self):
        self.assertEqual(
            _connector_consent_status(
                {"authType": "EntraOAuth", "entraOAuth": {"connectorName": "x"}}
            ),
            "Consented",
        )

    def test_auth_type_is_case_insensitive(self):
        self.assertEqual(
            _connector_consent_status({"authType": "entraoauth", "entraOAuth": None}),
            "PendingConsent",
        )

    def test_none_for_non_entra_connectors(self):
        self.assertIsNone(_connector_consent_status({"authType": "ApiKey"}))
        self.assertIsNone(_connector_consent_status({}))
        self.assertIsNone(_connector_consent_status(None))

    def test_annotate_adds_consent_status_from_flattened_extended_properties(self):
        connector = {
            "name": "my-mcp-connector",
            "extendedProperties": {"authType": "EntraOAuth", "entraOAuth": None},
        }
        annotated = _annotate_connector_consent_status(connector)
        self.assertEqual(annotated["consentStatus"], "PendingConsent")

    def test_annotate_falls_back_to_nested_properties_extended_properties(self):
        connector = {
            "name": "my-mcp-connector",
            "properties": {
                "extendedProperties": {"authType": "EntraOAuth", "entraOAuth": {"a": 1}}
            },
        }
        annotated = _annotate_connector_consent_status(connector)
        self.assertEqual(annotated["consentStatus"], "Consented")

    def test_annotate_no_ops_for_non_entra_connector(self):
        connector = {"name": "my-kusto-connector", "dataConnectorType": "Kusto"}
        annotated = _annotate_connector_consent_status(connector)
        self.assertNotIn("consentStatus", annotated)

    def test_annotate_passes_through_non_dict(self):
        self.assertEqual(_annotate_connector_consent_status("not a dict"), "not a dict")


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


class CommonPromptsShapeValidationTests(unittest.TestCase):
    """--extension-type commonPrompts' inner shape, CORRECTED after live
    verification against a real agent (2026-10-25): the per-resource wire
    shape is a single JSON object {"prompt": "..."} -- the ARM resource
    name (e.g. "default") is the prompt's identifier. An earlier reading
    of DebugApp/Client/ModelPromptsViewer.tsx's TS prop type
    (Array<{name, content}>) was wrong for this purpose -- that type
    describes an aggregated, multi-resource UI display value, not what a
    single PUT accepts; {"name":..., "content":...} silently round-trips
    back as {"prompt": ""} rather than being rejected, and a bare array is
    rejected with "invalid or unrecognized property" (confirmed the real
    data-plane requires the root to be a JSON object for every extension
    type, not just commonPrompts). Other extension types are intentionally
    NOT shape-checked yet -- their real payloads are still unconfirmed
    (issue #18)."""

    def test_accepts_well_formed_prompt_object(self):
        raw = json.dumps({"prompt": "Hello! This is a greeting."})
        encoded = _encode_extension_value(raw, "commonPrompts")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_array_value(self):
        raw = json.dumps([{"name": "greeting", "content": "Hello!"}])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "commonPrompts")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_object_missing_prompt_field(self):
        raw = json.dumps({"name": "greeting", "content": "Hello!"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "commonPrompts")
        self.assertIn("must include a string 'prompt' field", str(raised.exception))

    def test_rejects_non_string_prompt_field(self):
        raw = json.dumps({"prompt": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "commonPrompts")
        self.assertIn("must include a string 'prompt' field", str(raised.exception))

    def test_unconfirmed_extension_types_skip_shape_validation(self):
        # "tools" has no confirmed shape yet -- any JSON document is accepted
        # (baseline JSON-syntax check still applies, from the existing
        # ExtensionValueCodecTests coverage).
        raw = json.dumps({"anything": "goes"})
        encoded = _encode_extension_value(raw, "tools")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)


class GlobalSettingsShapeValidationTests(unittest.TestCase):
    """--extension-type globalSettings' inner shape is confirmed via a REAL
    end-to-end round-trip integration test in the control-plane repo (not a
    pass-through mock):
    Tests.Integration/Version20261101Preview/GlobalSettingsExtensionTests.cs,
    the "Configured" const -- base64-encoded, PUT, decoded server-side, and
    asserted byte-for-byte equal on GET/list. All fields are optional (the
    same test also exercises "{}" as valid)."""

    def test_accepts_empty_object(self):
        raw = json.dumps({})
        encoded = _encode_extension_value(raw, "globalSettings")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "toolPermissions": {"allow": ["ReadFile"], "ask": [], "deny": ["DeleteFile"]},
            "toolStatuses": [{"name": "PlotPieChart", "enabled": False}],
            "skillStatuses": [{"name": "redis", "enabled": False}],
            "customInstructions": "Investigate carefully",
            "approvalExpirationSetting": {"enabled": True, "approvalExpirationInMinutes": 60},
        })
        encoded = _encode_extension_value(raw, "globalSettings")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object_value(self):
        raw = json.dumps(["not", "an", "object"])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_non_list_tool_permissions_entry(self):
        raw = json.dumps({"toolPermissions": {"allow": "ReadFile"}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("toolPermissions.allow must be a JSON array of strings", str(raised.exception))

    def test_rejects_tool_statuses_item_missing_enabled(self):
        raw = json.dumps({"toolStatuses": [{"name": "PlotPieChart"}]})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("toolStatuses[0] must be an object with 'name' and 'enabled'", str(raised.exception))

    def test_rejects_non_bool_skill_status_enabled(self):
        raw = json.dumps({"skillStatuses": [{"name": "redis", "enabled": "false"}]})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("skillStatuses[0].name must be a string and .enabled must be a boolean", str(raised.exception))

    def test_rejects_non_string_custom_instructions(self):
        raw = json.dumps({"customInstructions": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("customInstructions must be a string", str(raised.exception))

    def test_rejects_non_numeric_approval_expiration_minutes(self):
        raw = json.dumps({"approvalExpirationSetting": {"approvalExpirationInMinutes": "60"}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("approvalExpirationInMinutes must be a number", str(raised.exception))


class PluginMarketplacesShapeValidationTests(unittest.TestCase):
    """--extension-type pluginMarketplaces' inner shape is confirmed via
    AAPT-SREAgent-ControlPlane's Agents.http worked example (a real
    base64-decoded payload) plus a live create round-trip against a real
    test agent: the service accepted the payload past its own validation
    (it later failed at Kubernetes provisioning in that environment, an
    infra limitation unrelated to the payload shape)."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "sourceType": "github",
            "sourceUrl": "owner/repo",
            "owner": {"name": "Test Owner"},
            "description": "Test marketplace",
        })
        encoded = _encode_extension_value(raw, "pluginMarketplaces")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object_value(self):
        raw = json.dumps(["not", "an", "object"])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginMarketplaces")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_non_string_source_type(self):
        raw = json.dumps({"sourceType": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginMarketplaces")
        self.assertIn("sourceType must be a string", str(raised.exception))

    def test_rejects_owner_without_string_name(self):
        raw = json.dumps({"owner": {"name": 123}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginMarketplaces")
        self.assertIn("owner must be a JSON object with a string 'name'", str(raised.exception))


class PluginInstallationsShapeValidationTests(unittest.TestCase):
    """--extension-type pluginInstallations' inner shape is confirmed via a
    REAL live create/show round-trip against a test agent: the service
    accepted this exact payload (sourced from Agents.http's worked example)
    and echoed it back enriched with server-side defaults (autoUpdate,
    mcpConnectorStatus, source.credentials/ref/sha/url)."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "marketplaceName": "test-marketplace",
            "pluginName": "azure-kubernetes",
            "source": {"type": "relative", "repo": "owner/repo"},
        })
        encoded = _encode_extension_value(raw, "pluginInstallations")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object_value(self):
        raw = json.dumps(["not", "an", "object"])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginInstallations")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_non_string_plugin_name(self):
        raw = json.dumps({"pluginName": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginInstallations")
        self.assertIn("pluginName must be a string", str(raised.exception))

    def test_rejects_non_object_source(self):
        raw = json.dumps({"source": "not-an-object"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginInstallations")
        self.assertIn("source must be a JSON object", str(raised.exception))

    def test_rejects_non_string_source_repo(self):
        raw = json.dumps({"source": {"repo": 123}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "pluginInstallations")
        self.assertIn("source.repo must be a string", str(raised.exception))


class IncidentFiltersShapeValidationTests(unittest.TestCase):
    """--extension-type incidentFilters' inner shape is confirmed via
    AAPT-SREAgent-ControlPlane's real E2E scenario fixtures
    (PagerDutySetupFixture.cs, IcmSetupFixture.cs), which round-trip this
    exact shape successfully against a real environment."""

    def test_accepts_the_real_confirmed_pagerduty_example_payload(self):
        raw = json.dumps({
            "incidentPlatform": "PagerDuty",
            "incidentTypes": [],
            "titleContains": "E2E test",
            "agentMode": "autonomous",
            "isEnabled": True,
        })
        encoded = _encode_extension_value(raw, "incidentFilters")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_accepts_the_real_confirmed_icm_example_payload_with_team_ids(self):
        raw = json.dumps({
            "incidentPlatform": "Icm",
            "incidentTypes": ["LiveSite"],
            "titleContains": "E2E test",
            "agentMode": "autonomous",
            "owningTeamIds": ["188963"],
            "handlingAgents": ["myagent"],
            "isEnabled": True,
        })
        encoded = _encode_extension_value(raw, "incidentFilters")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object_value(self):
        raw = json.dumps(["not", "an", "object"])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentFilters")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_non_bool_is_enabled(self):
        raw = json.dumps({"isEnabled": "true"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentFilters")
        self.assertIn("isEnabled must be a boolean", str(raised.exception))

    def test_rejects_non_list_incident_types(self):
        raw = json.dumps({"incidentTypes": "LiveSite"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentFilters")
        self.assertIn("incidentTypes must be a JSON array of strings", str(raised.exception))

    def test_rejects_non_list_handling_agents(self):
        raw = json.dumps({"handlingAgents": "myagent"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentFilters")
        self.assertIn("handlingAgents must be a JSON array of strings", str(raised.exception))


class IncidentHandlersShapeValidationTests(unittest.TestCase):
    """--extension-type incidentHandlers' inner shape is confirmed via
    AAPT-SREAgent-ControlPlane's real E2E scenario fixtures
    (PagerDutySetupFixture.cs's handlerConfig), round-tripped successfully
    against a real environment."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "id": "test-handler",
            "name": "",
            "description": "",
            "incidentFilterId": "test-filter",
            "incidentProcessingGuide": ["step one", "step two"],
            "tools": ["AcknowledgePagerDutyIncident", "ResolvePagerDutyIncident"],
            "incidents": [],
            "customInstructions": "",
        })
        encoded = _encode_extension_value(raw, "incidentHandlers")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object_value(self):
        raw = json.dumps(["not", "an", "object"])
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentHandlers")
        self.assertIn("must be a JSON object", str(raised.exception))

    def test_rejects_non_string_incident_filter_id(self):
        raw = json.dumps({"incidentFilterId": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentHandlers")
        self.assertIn("incidentFilterId must be a string", str(raised.exception))

    def test_rejects_non_list_tools(self):
        raw = json.dumps({"tools": "AcknowledgePagerDutyIncident"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentHandlers")
        self.assertIn("tools must be a JSON array of strings", str(raised.exception))

    def test_rejects_non_list_incident_processing_guide(self):
        raw = json.dumps({"incidentProcessingGuide": "step one"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "incidentHandlers")
        self.assertIn("incidentProcessingGuide must be a JSON array of strings", str(raised.exception))


class ToolsShapeValidationTests(unittest.TestCase):
    """--extension-type tools' inner shape is confirmed via sreagent-runtime
    (the real SRE Agent runtime/CLI source) -- Agent.Cli/Models/ToolSpecV2.cs
    + Kusto/Link/Python/HttpClientToolSpecV2.cs."""

    def test_accepts_a_real_kusto_tool_payload(self):
        raw = json.dumps({
            "type": "KustoTool",
            "connector": "my-kusto-connector",
            "toolMode": "Auto",
            "description": "Query the cluster",
            "database": "MyDatabase",
            "query": "MyTable | take 10",
            "parameters": [
                {"name": "limit", "type": "int", "description": "row limit", "required": False},
            ],
        })
        encoded = _encode_extension_value(raw, "tools")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_accepts_a_real_http_client_tool_payload(self):
        raw = json.dumps({
            "type": "HttpClientTool",
            "description": "Call an API",
            "url": "https://example.com/{{id}}",
            "method": "GET",
            "headers": [{"key": "Accept", "value": "application/json"}],
            "timeout_seconds": 30,
        })
        encoded = _encode_extension_value(raw, "tools")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_invalid_type(self):
        raw = json.dumps({"type": "NotARealTool"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "tools")
        self.assertIn("--value.type must be one of", str(raised.exception))

    def test_rejects_invalid_http_method(self):
        raw = json.dumps({"type": "HttpClientTool", "method": "FOO"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "tools")
        self.assertIn("--value.method must be one of", str(raised.exception))

    def test_rejects_kusto_tool_missing_query_type(self):
        raw = json.dumps({"type": "KustoTool", "query": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "tools")
        self.assertIn("--value.query must be a string", str(raised.exception))


class SkillsShapeValidationTests(unittest.TestCase):
    """--extension-type skills' inner shape is confirmed via sreagent-runtime
    Agent.Cli/Models/ExtendedSkillV2.cs's SkillSpecV2."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "description": "Investigates pod restarts",
            "tools": ["KustoClient", "AzureCLI"],
            "skillContent": "# Steps\n1. Check logs\n",
        })
        encoded = _encode_extension_value(raw, "skills")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_list_tools(self):
        raw = json.dumps({"tools": "KustoClient"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "skills")
        self.assertIn("--value.tools must be a JSON array of strings", str(raised.exception))


class HooksShapeValidationTests(unittest.TestCase):
    """--extension-type hooks' inner shape is confirmed via sreagent-runtime
    Agent.Cli/Models/HookV2.cs's HookSpecV2/HookDefinitionModel, which carry
    explicit JsonPropertyName wire-field attributes."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "eventType": "PostToolUse",
            "activationMode": "always",
            "description": "Blocks dangerous commands",
            "hook": {
                "type": "command",
                "command": "echo ok",
                "matcher": "Bash.*",
                "timeout": 30,
                "failMode": "Allow",
            },
        })
        encoded = _encode_extension_value(raw, "hooks")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_invalid_event_type(self):
        raw = json.dumps({"eventType": "NotAnEvent"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "hooks")
        self.assertIn("--value.eventType must be", str(raised.exception))

    def test_rejects_invalid_hook_type(self):
        raw = json.dumps({"hook": {"type": "notarealtype"}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "hooks")
        self.assertIn("--value.hook.type must be", str(raised.exception))


class ScheduledTasksShapeValidationTests(unittest.TestCase):
    """--extension-type scheduledTasks' inner shape is confirmed via
    sreagent-runtime Agent.Cli/Models/ScheduledTaskV2.cs's
    ScheduledTaskSpecV2, whose doc comment states these are exactly the
    fields the real v2 scheduledtasks API returns/accepts."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "description": "Nightly compliance scan",
            "cronExpression": "0 2 * * *",
            "agentPrompt": "Run the compliance scan",
            "maxExecutions": 10,
        })
        encoded = _encode_extension_value(raw, "scheduledTasks")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_number_max_executions(self):
        raw = json.dumps({"maxExecutions": "ten"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "scheduledTasks")
        self.assertIn("--value.maxExecutions must be a number", str(raised.exception))


class RepositoriesShapeValidationTests(unittest.TestCase):
    """--extension-type repositories' inner shape is confirmed via
    sreagent-runtime Agent.Cli/Models/RepositoryV2.cs's own
    RepositoryV2.Validate() method."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "url": "https://github.com/contoso/repo",
            "type": "GitHub",
            "branch": "main",
        })
        encoded = _encode_extension_value(raw, "repositories")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_missing_url(self):
        raw = json.dumps({"type": "GitHub"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "repositories")
        self.assertIn("--value.url is required", str(raised.exception))

    def test_rejects_invalid_type(self):
        raw = json.dumps({"url": "https://x", "type": "Bitbucket"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "repositories")
        self.assertIn("--value.type must be", str(raised.exception))

    def test_rejects_incomplete_feed_credential(self):
        raw = json.dumps({"url": "https://x", "feedCredentials": [{"orgName": "contoso"}]})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "repositories")
        self.assertIn("feedUrl is required", str(raised.exception))


class GitHubAuthsShapeValidationTests(unittest.TestCase):
    """--extension-type githubAuths' inner shape is confirmed via
    sreagent-runtime Agent.Cli/Models/GitHubAuthV2.cs's own
    GitHubAuthV2.Validate() method."""

    def test_accepts_a_real_pat_payload(self):
        raw = json.dumps({"authType": "Pat", "pat": "ghp_xxx"})
        encoded = _encode_extension_value(raw, "githubAuths")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_accepts_a_real_github_app_payload(self):
        raw = json.dumps({
            "authType": "GitHubApp",
            "clientId": "abc123",
            "privateKeySecretUri": "https://myvault.vault.azure.net/secrets/key",
        })
        encoded = _encode_extension_value(raw, "githubAuths")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_pat_type_missing_pat(self):
        raw = json.dumps({"authType": "Pat"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "githubAuths")
        self.assertIn("--value.pat is required", str(raised.exception))

    def test_rejects_invalid_auth_type(self):
        raw = json.dumps({"authType": "Basic"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "githubAuths")
        self.assertIn("--value.authType must be", str(raised.exception))


class AzureDevOpsAuthsShapeValidationTests(unittest.TestCase):
    """--extension-type azureDevOpsAuths' inner shape is confirmed via
    sreagent-runtime Agent.Cli/Models/AzureDevOpsAuthV2.cs's own
    AzureDevOpsAuthV2.Validate() method."""

    def test_accepts_a_real_managed_identity_payload(self):
        raw = json.dumps({"authType": "ManagedIdentity", "identity": "/subscriptions/x/.../mi"})
        encoded = _encode_extension_value(raw, "azureDevOpsAuths")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_managed_identity_missing_identity(self):
        raw = json.dumps({"authType": "ManagedIdentity"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "azureDevOpsAuths")
        self.assertIn("--value.identity is required", str(raised.exception))

    def test_rejects_partial_federated_fields(self):
        raw = json.dumps({
            "authType": "ManagedIdentity",
            "identity": "/subscriptions/x/.../mi",
            "federatedClientId": "abc",
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "azureDevOpsAuths")
        self.assertIn("must both be provided or both be omitted", str(raised.exception))


class HttpTriggersShapeValidationTests(unittest.TestCase):
    """--extension-type httpTriggers' inner shape is confirmed via
    sreagent-runtime Agent.Web/Controllers/v1/HttpTriggersController.cs's
    ARM-alias route, whose own code comment documents this exact shape
    (the control plane wraps every extension payload as
    { name, type, properties } and unwraps properties before forwarding)."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "name": "my-trigger",
            "description": "Runs on webhook",
            "agentPrompt": "Investigate the alert",
            "agentMode": "readonly",
        })
        encoded = _encode_extension_value(raw, "httpTriggers")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_invalid_agent_mode(self):
        raw = json.dumps({"agentMode": "yolo"})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "httpTriggers")
        self.assertIn("--value.agentMode must be", str(raised.exception))


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


class ArgSchemaHelpRegressionTests(unittest.TestCase):
    """Regression test for a real bug found during live verification:
    AAZBaseArg always initializes ._help as a dict (keyed by
    'short-summary'/'long-summary'/'name'/'populator-commands'), and
    to_cmd_arg() calls ._help.get('short-summary', None). Overwriting
    ._help with a plain string (instead of merging into the existing
    dict) made `az sre agent connector create -h` crash with
    "'str' object has no attribute 'get'". _ModelProviderArgMixin had the
    identical bug but it silently never fired (default_model.provider
    isn't reachable at schema-build time for agent create/update), which
    is why only the connector command surfaced it live. Both mixins are
    exercised here via the real to_cmd_arg() path, not just help-text
    presence, so this would have caught the crash before it reached a
    real agent.
    """

    def test_connector_create_help_does_not_crash(self):
        schema = ConnectorCreate._build_arguments_schema()
        cmd_arg = schema.data_connector_type.to_cmd_arg("data_connector_type")
        self.assertIn("Kusto", cmd_arg.type.settings.get("help"))

    def test_agent_create_help_does_not_crash(self):
        schema = Create._build_arguments_schema()
        cmd_arg = schema.default_model.provider.to_cmd_arg("provider")
        self.assertIn("Anthropic", cmd_arg.type.settings.get("help"))


if __name__ == "__main__":
    unittest.main()

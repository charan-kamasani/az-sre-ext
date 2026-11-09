"""Credential-free regression tests for the hand-written `az sre` command
layer (azext_sre/custom.py).

Style: offline, mocked, no live Azure calls, and asserting real business
logic (argument validation, wire-payload shape, role-name mapping) rather
than just "does it import". Tests that need a real
AAZCommand instance bypass __init__ and the framework's ctx-rebuilding
_handler() by constructing via object.__new__, pre-seeding .ctx/.cli_ctx, and
patch azure.cli.core.aaz.AAZCommand._handler to a no-op so our subclass's own
_handler() logic runs against the ctx we control instead of a freshly
rebuilt one.
"""

import base64
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from requests import HTTPError, Response

from azure.cli.core.aaz import AAZCommand, AAZUndefined
from azure.cli.core.azclierror import CLIError, ResourceNotFoundError
from azure.cli.core.mock import DummyCli
from azure.core.exceptions import ResourceExistsError

from azext_sre import SreCommandsLoader
from azext_sre.custom import (
    EXTENSION_TYPES,
    GITHUB_COPILOT_MCP_ENDPOINT,
    KNOWLEDGE_TYPES,
    MANAGED_RESOURCE_ROLES,
    Create,
    AgentSettingsShow,
    AgentSettingsUpdate,
    ConnectorCreate,
    ConnectorList,
    GrantAccess,
    RevokeAccess,
    ManagedResourceGrant,
    ManagedResourceRevoke,
    ManagedResourceList,
    AccessList,
    UpdateNetwork,
    RepoConnect,
    GetConnection,
    KnowledgeCreate,
    KnowledgeShow,
    KnowledgeList,
    KnowledgeDelete,
    ToolCreate,
    ToolShow,
    ToolList,
    ToolDelete,
    SkillCreate,
    SkillShow,
    SkillList,
    SkillDelete,
    SubagentCreate,
    SubagentShow,
    SubagentList,
    SubagentDelete,
    HookCreate,
    HookShow,
    HookList,
    HookDelete,
    InstructionsCreate,
    InstructionsShow,
    InstructionsList,
    InstructionsDelete,
    PluginMarketplaceCreate,
    PluginMarketplaceShow,
    PluginMarketplaceList,
    PluginMarketplaceDelete,
    PluginInstallCreate,
    PluginInstallShow,
    PluginInstallList,
    PluginInstallDelete,
    _warn_if_quickstart_plan,
    _data_plane_request,
    _resolve_agent_endpoint,
    EXTENSION_TYPE_CREATE_NOUN,
    ConnectorListSecret,
    IdentityAssign,
    IdentityRemove,
    IdentityShow,
    SupportedAgentModelList,
    _ConnectorConvenienceArgsMixin,
    _DataConnectorTypeArgMixin,
    _ConnectorExistenceGuardMixin,
    _DefaultSystemIdentityMixin,
    _GrantAccessToMeMixin,
    _annotate_connector_consent_status,
    _arg_value,
    _cli_invoke,
    _connector_consent_guidance,
    _connector_consent_status,
    _decode_extension_envelope,
    _detect_repo_provider,
    _encode_extension_value,
    _extension_resource_create,
    _extension_resource_show,
    _extension_resource_list,
    _github_device_flow,
    _github_token,
    _extension_resource_delete,
    _is_microsoft_first_party_tenant,
    _normalize_data_connector_type,
    _normalize_model_provider,
    _parse_skill_md,
    _resolve_agent_principal_id,
    _resolve_managed_resource_scope,
    _resolve_signed_in_tenant_id,
    _IcmIncidentPlatformGateMixin,
    _resolve_signed_in_user_object_id,
    MICROSOFT_FIRST_PARTY_TENANT_IDS,
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
        self.assertEqual(
            _normalize_model_provider("GitHubCopilot"), "GitHubCopilot"
        )
        self.assertEqual(
            _normalize_model_provider("githubcopilot"), "GitHubCopilot"
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

    def test_accepts_v1_backend_types_case_insensitively(self):
        # These 14 are in sreagent-runtime's real V1 allowlist
        # (Agent.Core/Configuration/DataConnectorTypes.cs) and were
        # confirmed live against a throwaway agent on 2026-11-02: all
        # succeed with just --data-source (genevametrics additionally
        # needs extended-properties.monitoringAccount). They were missing
        # from this CLI's stricter client-side check even though the
        # service has always accepted them.
        self.assertEqual(_normalize_data_connector_type("appinsights"), "AppInsights")
        self.assertEqual(_normalize_data_connector_type("LOGANALYTICS"), "LogAnalytics")
        self.assertEqual(_normalize_data_connector_type("KustoUser"), "KustoUser")
        self.assertEqual(_normalize_data_connector_type("kustodataindexer"), "KustoDataIndexer")
        self.assertEqual(_normalize_data_connector_type("TsgCrawler"), "TsgCrawler")
        self.assertEqual(_normalize_data_connector_type("ev2mcp"), "Ev2Mcp")
        self.assertEqual(_normalize_data_connector_type("GenevaMetrics"), "GenevaMetrics")
        self.assertEqual(_normalize_data_connector_type("s360"), "S360")
        self.assertEqual(_normalize_data_connector_type("ConnectorGateway"), "ConnectorGateway")
        self.assertEqual(_normalize_data_connector_type("documentation"), "Documentation")
        self.assertEqual(_normalize_data_connector_type("AzureDevOpsBuiltinMcp"), "AzureDevOpsBuiltinMcp")
        self.assertEqual(_normalize_data_connector_type("applicationinsights"), "ApplicationInsights")
        self.assertEqual(_normalize_data_connector_type("AzureMonitor"), "AzureMonitor")
        self.assertEqual(_normalize_data_connector_type("monitorclient"), "MonitorClient")

    def test_none_passes_through_unchanged(self):
        self.assertIsNone(_normalize_data_connector_type(None))

    def test_rejects_unknown_value(self):
        with self.assertRaises(CLIError) as raised:
            _normalize_data_connector_type("pagerduty")
        self.assertIn(
            "--data-connector-type must be one of", str(raised.exception)
        )

    def test_accepts_friendly_product_names_case_insensitively(self):
        # Friendly names confirmed against sreagent-runtime's own portal
        # i18n strings (SREAgentResources.ts), not invented -- see
        # DATA_CONNECTOR_TYPE_ALIASES docstring. Lets users type what the
        # product calls the connector instead of the raw wire enum casing.
        # "Azure Data Explorer" -> KustoClient matches the portal exactly:
        # the portal's own picker has no entry for plain "Kusto" at all,
        # and always persists that selection as dataConnectorType=KustoClient.
        self.assertEqual(_normalize_data_connector_type("Azure Data Explorer"), "KustoClient")
        self.assertEqual(_normalize_data_connector_type("AZURE DATA EXPLORER"), "KustoClient")
        self.assertEqual(_normalize_data_connector_type("Azure Data Explorer MCP"), "KustoClient")
        self.assertEqual(_normalize_data_connector_type("Azure Data Explorer Cluster"), "Kusto")
        self.assertEqual(_normalize_data_connector_type("Custom MCP"), "Mcp")
        self.assertEqual(_normalize_data_connector_type("User Provided Connector"), "Mcp")
        self.assertEqual(_normalize_data_connector_type("Office 365 Outlook"), "Outlook")
        self.assertEqual(_normalize_data_connector_type("Microsoft Teams"), "Teams")
        self.assertEqual(_normalize_data_connector_type("Microsoft IcM"), "Icm")
        self.assertEqual(_normalize_data_connector_type("Microsoft DGrep"), "Dgrep")
        # Corrected Title-based names, added 2026-11-04 after the full
        # portal catalog export clarified these are the real card Titles
        # (previously only the subtitle-based aliases above existed).
        self.assertEqual(_normalize_data_connector_type("MCP server"), "Mcp")
        self.assertEqual(_normalize_data_connector_type("IcM connector"), "Icm")


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

    def test_annotate_warns_with_portal_link_when_pending_consent(self):
        connector = {
            "id": "/subscriptions/sub1/resourceGroups/rg1/providers/"
            "Microsoft.App/agents/myagent/connectors/conn-mcp",
            "name": "conn-mcp",
            "extendedProperties": {"authType": "EntraOAuth", "entraOAuth": None},
        }
        with patch("azext_sre.custom.logger") as mock_logger:
            _annotate_connector_consent_status(connector)
            mock_logger.warning.assert_called_once()
            message = mock_logger.warning.call_args[0][0]
        self.assertIn("conn-mcp", message)
        self.assertIn(
            "https://portal.azure.com/#@/resource/subscriptions/sub1/"
            "resourceGroups/rg1/providers/Microsoft.App/agents/myagent/"
            "connectors/conn-mcp/overview",
            message,
        )

    def test_annotate_does_not_warn_when_consented(self):
        connector = {
            "name": "conn-mcp",
            "extendedProperties": {"authType": "EntraOAuth", "entraOAuth": {"a": 1}},
        }
        with patch("azext_sre.custom.logger") as mock_logger:
            _annotate_connector_consent_status(connector)
            mock_logger.warning.assert_not_called()

    def test_annotate_does_not_warn_for_non_entra_connector(self):
        connector = {"name": "my-kusto-connector", "dataConnectorType": "Kusto"}
        with patch("azext_sre.custom.logger") as mock_logger:
            _annotate_connector_consent_status(connector)
            mock_logger.warning.assert_not_called()

    def test_guidance_falls_back_to_generic_portal_text_without_id(self):
        connector = {
            "name": "conn-mcp",
            "extendedProperties": {"authType": "EntraOAuth", "entraOAuth": None},
        }
        message = _connector_consent_guidance(connector)
        self.assertIn("the connector's blade in the Azure portal", message)
        self.assertIn("conn-mcp", message)


class ArgValueTests(unittest.TestCase):
    def test_undefined_becomes_none(self):
        from azure.cli.core.aaz import AAZUndefined

        self.assertIsNone(_arg_value(AAZUndefined))

    def test_plain_values_pass_through(self):
        self.assertEqual(_arg_value("foo"), "foo")
        self.assertEqual(_arg_value({"a": "b"}), {"a": "b"})
        self.assertIsNone(_arg_value(None))


class CliInvokeTests(unittest.TestCase):
    """`_cli_invoke` runs another `az` command in-process; it is the shared
    helper behind 19+ call sites (tenant/user resolution, PAT token fetch,
    identity lookups, etc.), so every exception path it can take must
    surface a clear CLIError rather than an arbitrary raw exception.
    """

    @staticmethod
    def _fake_cli(invoke_side_effect=None, exit_code=0, result="ok"):
        fake_cli = SimpleNamespace(out_file=None, result=SimpleNamespace(result=result))

        def _invoke(_args, out_file=None):  # pylint: disable=unused-argument
            if invoke_side_effect is not None:
                raise invoke_side_effect
            return exit_code

        fake_cli.invoke = _invoke
        return fake_cli

    def test_success_returns_result(self):
        with patch("azure.cli.core.get_default_cli", return_value=self._fake_cli(result={"a": 1})):
            self.assertEqual(_cli_invoke(None, "account", "show"), {"a": 1})

    def test_sre_call_forwards_callers_subscription(self):
        seen = []
        fake_cli = self._fake_cli()
        fake_cli.invoke = lambda args, out_file=None: seen.append(args) or 0
        cli_ctx = SimpleNamespace(data={"subscription_id": "sub-1"})
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            _cli_invoke(cli_ctx, "sre", "connector", "list", "-g", "rg")
            _cli_invoke(cli_ctx, "account", "show")
            _cli_invoke(cli_ctx, "sre", "agent", "show", "--subscription", "other")
        self.assertEqual(seen[0][-2:], ["--subscription", "sub-1"])
        self.assertNotIn("--subscription", seen[1])
        self.assertEqual(seen[2].count("--subscription"), 1)

    def test_resource_not_found_error_wrapped_as_clierror(self):
        fake_cli = self._fake_cli(invoke_side_effect=ResourceNotFoundError("no such thing"))
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            with self.assertRaises(CLIError):
                _cli_invoke(None, "account", "show")

    def test_resource_not_found_error_suppressed_when_allow_missing(self):
        fake_cli = self._fake_cli(invoke_side_effect=ResourceNotFoundError("no such thing"))
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            self.assertIsNone(_cli_invoke(None, "account", "show", allow_missing=True))

    def test_arbitrary_exception_wrapped_as_clierror_not_leaked_raw(self):
        """A non-ResourceNotFoundError/SystemExit exception (e.g. an auth
        failure escaping cli.invoke() before its own error handling
        engages) must still come out as a clear CLIError, not propagate
        as its original, unrelated-looking exception type.
        """
        fake_cli = self._fake_cli(invoke_side_effect=RuntimeError("token provider exploded"))
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            with self.assertRaises(CLIError) as ctx:
                _cli_invoke(None, "account", "show")
        self.assertIn("token provider exploded", str(ctx.exception))

    def test_arbitrary_exception_suppressed_when_allow_missing(self):
        fake_cli = self._fake_cli(invoke_side_effect=RuntimeError("boom"))
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            self.assertIsNone(_cli_invoke(None, "account", "show", allow_missing=True))

    def test_nonzero_exit_code_wrapped_as_clierror(self):
        with patch("azure.cli.core.get_default_cli", return_value=self._fake_cli(exit_code=1)):
            with self.assertRaises(CLIError):
                _cli_invoke(None, "account", "show")


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


class AssigneeMeTests(unittest.TestCase):
    """--assignee-me on grant-access/revoke-access: resolves the signed-in
    user's object ID via 'az ad signed-in-user show' instead of requiring
    --assignee, mirroring --grant-access-to-me's resolution logic (shared
    via _resolve_signed_in_user_object_id so both paths agree on what "me"
    means).
    """

    def test_grant_access_assignee_me_resolves_signed_in_user(self):
        command = _bare_command(
            GrantAccess, name="myagent", resource_group="myrg", role="reader",
            assignee=None, assignee_me=True,
        )
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("ad", "signed-in-user", "show"):
                return {"id": "signed-in-object-id"}
            if args[:3] == ("sre", "agent", "show"):
                return {"id": "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"}
            return {"result": "assigned"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, {"result": "assigned"})
        self.assertEqual(
            calls[-1],
            (
                "role", "assignment", "create",
                "--role", "SRE Agent Reader",
                "--assignee", "signed-in-object-id",
                "--scope", "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent",
            ),
        )

    def test_revoke_access_assignee_me_resolves_signed_in_user(self):
        command = _bare_command(
            RevokeAccess, name="myagent", resource_group="myrg", role="author",
            assignee=None, assignee_me=True,
        )
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("ad", "signed-in-user", "show"):
                return {"id": "signed-in-object-id"}
            if args[:3] == ("sre", "agent", "show"):
                return {"id": "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"}
            return {"result": "revoked"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, {"result": "revoked"})
        self.assertEqual(
            calls[-1],
            (
                "role", "assignment", "delete",
                "--role", "SRE Agent Author",
                "--assignee", "signed-in-object-id",
                "--scope", "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent",
            ),
        )

    def test_both_assignee_and_assignee_me_rejected(self):
        command = _bare_command(
            GrantAccess, name="myagent", resource_group="myrg", role="reader",
            assignee="someone@example.com", assignee_me=True,
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None):
            with self.assertRaises(CLIError):
                command._handler({})

    def test_neither_assignee_nor_assignee_me_rejected(self):
        command = _bare_command(
            GrantAccess, name="myagent", resource_group="myrg", role="reader",
            assignee=None, assignee_me=False,
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None):
            with self.assertRaises(CLIError):
                command._handler({})

    def test_access_list_queries_role_assignments_on_agent_scope(self):
        """New: 'az sre access list' -- the gap found live-testing the CLI
        purely via --help (granting access had no documented way to verify
        who has it afterward)."""
        command = _bare_command(AccessList, name="myagent", resource_group="myrg")
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("sre", "agent", "show"):
                return {"id": "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"}
            return [{"roleDefinitionName": "SRE Agent Reader"}]

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, [{"roleDefinitionName": "SRE Agent Reader"}])
        self.assertEqual(
            calls[-1],
            (
                "role", "assignment", "list",
                "--scope", "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent",
            ),
        )

    def test_access_list_raises_when_agent_not_found(self):
        command = _bare_command(AccessList, name="ghost", resource_group="rg")

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return None

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            with self.assertRaises(ResourceNotFoundError):
                command._handler({})

    def test_resolve_signed_in_user_object_id_raises_when_missing(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {}):
            with self.assertRaises(CLIError):
                _resolve_signed_in_user_object_id(SimpleNamespace())


class ManagedResourceScopeResolutionTests(unittest.TestCase):
    """'sre managed-resource' is the mirror image of 'sre access': assignee
    = the agent's OWN identity (via 'sre identity show'), scope = an
    EXTERNAL subscription/resource-group/management-group -- confirmed from
    the portal's "Add management groups" dialog ("The agent will be granted
    Reader and Azure Monitor Monitoring Contributor roles..."). These tests
    cover the pure scope-string-building and principal-resolution helpers."""

    def test_raw_scope_passthrough(self):
        scope = _resolve_managed_resource_scope(
            SimpleNamespace(), "/subscriptions/x/resourceGroups/y", None, None, None
        )
        self.assertEqual(scope, "/subscriptions/x/resourceGroups/y")

    def test_management_group_scope(self):
        scope = _resolve_managed_resource_scope(SimpleNamespace(), None, None, None, "my-mg")
        self.assertEqual(scope, "/providers/Microsoft.Management/managementGroups/my-mg")

    def test_subscription_only_scope_resolves_subscription_id(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {"id": "sub-guid"}):
            scope = _resolve_managed_resource_scope(SimpleNamespace(), None, "my-sub", None, None)
        self.assertEqual(scope, "/subscriptions/sub-guid")

    def test_subscription_and_target_resource_group_scope(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {"id": "sub-guid"}):
            scope = _resolve_managed_resource_scope(SimpleNamespace(), None, "my-sub", "monitored-rg", None)
        self.assertEqual(scope, "/subscriptions/sub-guid/resourceGroups/monitored-rg")

    def test_target_resource_group_without_subscription_raises(self):
        with self.assertRaises(CLIError):
            _resolve_managed_resource_scope(SimpleNamespace(), None, None, "monitored-rg", None)

    def test_management_group_combined_with_subscription_raises(self):
        with self.assertRaises(CLIError):
            _resolve_managed_resource_scope(SimpleNamespace(), None, "my-sub", None, "my-mg")

    def test_scope_combined_with_convenience_flags_raises(self):
        with self.assertRaises(CLIError):
            _resolve_managed_resource_scope(SimpleNamespace(), "/subscriptions/x", "my-sub", None, None)

    def test_nothing_given_raises(self):
        with self.assertRaises(CLIError):
            _resolve_managed_resource_scope(SimpleNamespace(), None, None, None, None)

    def test_resolve_agent_principal_id_returns_principal(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {"principalId": "agent-principal"}):
            self.assertEqual(
                _resolve_agent_principal_id(SimpleNamespace(), "myagent", "myrg"), "agent-principal"
            )

    def test_resolve_agent_principal_id_raises_when_no_identity(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {}):
            with self.assertRaises(CLIError):
                _resolve_agent_principal_id(SimpleNamespace(), "myagent", "myrg")


class ManagedResourceCommandTests(unittest.TestCase):
    """End-to-end (mocked) tests for grant/revoke/list -- confirms both
    MANAGED_RESOURCE_ROLES are always applied together (the portal gives no
    role choice), and that the agent's own principalId is always the
    assignee while the external scope is whatever the caller targets."""

    def test_roles_are_reader_and_monitoring_contributor(self):
        self.assertEqual(MANAGED_RESOURCE_ROLES, ["Reader", "Monitoring Contributor"])

    def test_grant_creates_both_role_assignments_on_target_scope(self):
        command = _bare_command(
            ManagedResourceGrant, agent_name="myagent", resource_group="myrg",
            scope=None, target_subscription="my-sub", target_resource_group=None, management_group=None,
        )
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("sre", "identity", "show"):
                return {"principalId": "agent-principal-id"}
            if args[:2] == ("account", "show"):
                return {"id": "sub-guid"}
            return {"result": "created"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, [{"result": "created"}, {"result": "created"}])
        role_assignment_calls = [c for c in calls if c[:2] == ("role", "assignment")]
        self.assertEqual(len(role_assignment_calls), 2)
        self.assertEqual(
            role_assignment_calls[0],
            ("role", "assignment", "create", "--role", "Reader",
             "--assignee", "agent-principal-id", "--scope", "/subscriptions/sub-guid"),
        )
        self.assertEqual(
            role_assignment_calls[1],
            ("role", "assignment", "create", "--role", "Monitoring Contributor",
             "--assignee", "agent-principal-id", "--scope", "/subscriptions/sub-guid"),
        )

    def test_revoke_deletes_both_role_assignments_on_target_scope(self):
        command = _bare_command(
            ManagedResourceRevoke, agent_name="myagent", resource_group="myrg",
            scope="/providers/Microsoft.Management/managementGroups/my-mg",
            target_subscription=None, target_resource_group=None, management_group=None,
        )
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("sre", "identity", "show"):
                return {"principalId": "agent-principal-id"}
            return {"result": "deleted"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            command._handler({})

        role_assignment_calls = [c for c in calls if c[:2] == ("role", "assignment")]
        self.assertEqual(len(role_assignment_calls), 2)
        for call, role in zip(role_assignment_calls, MANAGED_RESOURCE_ROLES):
            self.assertEqual(
                call,
                ("role", "assignment", "delete", "--role", role, "--assignee", "agent-principal-id",
                 "--scope", "/providers/Microsoft.Management/managementGroups/my-mg"),
            )

    def test_list_queries_role_assignments_for_agent_principal(self):
        command = _bare_command(ManagedResourceList, agent_name="myagent", resource_group="myrg")
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            if args[:3] == ("sre", "identity", "show"):
                return {"principalId": "agent-principal-id"}
            return [{"roleDefinitionName": "Reader"}]

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, [{"roleDefinitionName": "Reader"}])
        self.assertEqual(
            calls[-1], ("role", "assignment", "list", "--assignee", "agent-principal-id", "--all"),
        )

    def test_grant_raises_when_agent_has_no_identity(self):
        command = _bare_command(
            ManagedResourceGrant, agent_name="myagent", resource_group="myrg",
            scope="/subscriptions/x", target_subscription=None, target_resource_group=None, management_group=None,
        )

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            if args[:3] == ("sre", "identity", "show"):
                return {}
            return {"result": "unused"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            with self.assertRaises(CLIError):
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
        raw = json.dumps({"toolPermissions": {"allow": "ReadFile", "ask": [], "deny": []}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        self.assertIn("toolPermissions.allow must be a JSON array of strings", str(raised.exception))

    def test_rejects_partial_tool_permissions_object(self):
        # Live-confirmed this session: the real API rejects a toolPermissions
        # object that's missing any of allow/ask/deny with a misleading
        # "contains an invalid or unrecognized property" 400 -- the actual
        # cause is a MISSING sibling property, not an unrecognized one.
        # Caught here client-side with an accurate message instead.
        raw = json.dumps({"toolPermissions": {"deny": ["restart*"]}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "globalSettings")
        message = str(raised.exception)
        self.assertIn("missing", message)
        self.assertIn("'allow'", message)
        self.assertIn("'ask'", message)

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


class ResponsePlanHandlerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.filters = {}
        self.handlers = {}
        self.handler_error = None
        self.handler_path = "/api/v2/extendedAgent/incidentHandlers"
        for replacement in (
            patch.object(AAZCommand, "_handler", lambda command, command_args: None),
            patch("azext_sre.custom._extension_resource_create", side_effect=self._arm_create),
            patch("azext_sre.custom._extension_resource_show", side_effect=self._arm_show),
            patch("azext_sre.custom._extension_resource_list", side_effect=self._arm_list),
            patch("azext_sre.custom._extension_resource_delete", side_effect=self._arm_delete),
            patch("azext_sre.custom._data_plane_request", side_effect=self._agent_request),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def _arm_create(self, cli_ctx, agent, group, extension_type, name, value, overwrite=False):
        if extension_type != "incidentFilters":
            raise ResourceNotFoundError("The ARM handler proxy is unavailable.")
        self.filters[name] = json.loads(value)
        return self._arm_show(cli_ctx, agent, group, extension_type, name)

    def _arm_show(self, cli_ctx, agent, group, extension_type, name):
        if extension_type != "incidentFilters":
            raise ResourceNotFoundError("The ARM handler proxy is unavailable.")
        return {"name": name, "properties": {"value": copy.deepcopy(self.filters[name])}}

    def _arm_list(self, cli_ctx, agent, group, extension_type):
        return {"value": [
            self._arm_show(cli_ctx, agent, group, extension_type, name) for name in self.filters
        ]}

    def _arm_delete(self, cli_ctx, agent, group, extension_type, name):
        if extension_type != "incidentFilters":
            raise ResourceNotFoundError("The ARM handler proxy is unavailable.")
        del self.filters[name]

    def _agent_request(self, cli_ctx, agent, group, method, path, body=None,
                       missing_ok=False, agent_url=None):
        if method == "GET" and path == self.handler_path:
            return copy.deepcopy(list(self.handlers.values()))
        if not path.startswith(self.handler_path + "/"):
            raise ResourceNotFoundError(path)
        name = path.rsplit("/", 1)[-1]
        if method == "PUT":
            if self.handler_error:
                raise self.handler_error
            self.handlers[name] = copy.deepcopy(body)
            return copy.deepcopy(self.handlers[name])
        if method == "DELETE":
            self.handlers.pop(name, None)
            return {}
        raise ResourceNotFoundError(path)

    def _command(self, command_cls, **overrides):
        values = dict(
            agent_name="agent", resource_group="rg", extension_name="plan", agent_url=None,
            platform=None, subagent=None, mode=None, disabled=None, priorities=None,
            title_contains=None, title_not_contains=None, incident_types=None,
            impacted_service=None, owning_teams=None, merge_enabled=None, merge_window_hours=None,
            instructions=None, processing_guide=None, overwrite=None,
        )
        return _bare_command(command_cls, **{**values, **overrides})._handler(None)

    def _create(self, **overrides):
        from azext_sre.custom import ResponsePlanCreate
        return self._command(
            ResponsePlanCreate, **{
                "platform": "AzMonitor", "subagent": "responder", "mode": "review",
                "disabled": True, "instructions": "Check logs", **overrides,
            })

    def test_create_persists_instructions_and_default_show_reads_the_linked_handler(self):
        from azext_sre.custom import ResponsePlanShow
        self._create(processing_guide=["Read metrics"])
        shown = self._command(ResponsePlanShow)
        self.assertEqual(shown["handlers"], [{
            "id": "plan", "incidentFilterId": "plan", "customInstructions": "Check logs",
            "incidentProcessingGuide": ["Read metrics"],
        }])
        self.assertFalse(shown["filter"]["properties"]["isEnabled"])

    def test_show_without_instructions_returns_an_empty_handler_list(self):
        from azext_sre.custom import ResponsePlanShow
        self._create(instructions=None)
        self.assertEqual(self._command(ResponsePlanShow)["handlers"], [])

    def test_update_preserves_existing_handler_identity_and_processing_guide(self):
        from azext_sre.custom import ResponsePlanUpdate
        self._create(instructions=None)
        self.handlers["custom-handler"] = {
            "id": "custom-handler", "incidentFilterId": "plan",
            "customInstructions": "Old instructions", "incidentProcessingGuide": ["Read metrics"],
        }
        self._command(ResponsePlanUpdate, instructions="Check dependencies")
        self.assertEqual(self.handlers, {"custom-handler": {
            "id": "custom-handler", "incidentFilterId": "plan",
            "customInstructions": "Check dependencies", "incidentProcessingGuide": ["Read metrics"],
        }})
        self.assertFalse(self.filters["plan"]["isEnabled"])

    def test_update_creates_instructions_for_a_plan_with_no_handler(self):
        from azext_sre.custom import ResponsePlanUpdate, ResponsePlanShow
        self._create(instructions=None)
        self._command(ResponsePlanUpdate, instructions="Check dependencies")
        self.assertEqual(
            self._command(ResponsePlanShow)["handlers"][0]["customInstructions"], "Check dependencies")

    def test_delete_removes_all_linked_handlers_without_touching_another_plan(self):
        from azext_sre.custom import ResponsePlanDelete
        self._create()
        self.handlers["extra"] = {"id": "extra", "incidentFilterId": "plan"}
        unrelated = {"id": "other", "incidentFilterId": "other-plan", "customInstructions": "Keep"}
        self.handlers["other"] = unrelated
        self._command(ResponsePlanDelete)
        self.assertEqual(self.handlers, {"other": unrelated})
        self.assertNotIn("plan", self.filters)

    def test_duplicate_handler_is_rejected_without_overwriting_its_instructions(self):
        from azext_sre.custom import _incident_handler_path, _incident_resource_create
        existing = {"id": "plan", "incidentFilterId": "other-plan", "customInstructions": "Keep"}
        self.handlers["plan"] = existing
        replacement = {"id": "plan", "incidentFilterId": "plan", "customInstructions": "Replace"}
        with self.assertRaises(ResourceExistsError):
            _incident_resource_create(
                None, "agent", "rg", "incidentHandlers", "plan", replacement,
                _incident_handler_path("plan"), replacement, False)
        self.assertEqual(self.handlers["plan"], existing)

    def test_create_reports_partial_failure_when_the_agent_rejects_instructions(self):
        response = Response()
        response.status_code = 403
        response._content = b"Forbidden"
        self.handler_error = HTTPError("Forbidden", response=response)
        with self.assertRaisesRegex(CLIError, "created, but its instructions were not saved"):
            self._create()
        self.assertIn("plan", self.filters)
        self.assertFalse(self.filters["plan"]["isEnabled"])
        self.assertEqual(self.handlers, {})

    def test_unexpected_handler_collection_is_an_error_not_missing_instructions(self):
        from azext_sre.custom import ResponsePlanShow
        self._create(instructions=None)
        for response in (None, {}, {"value": []}, [None]):
            with self.subTest(response=response), \
                 patch("azext_sre.custom._data_plane_request", return_value=response), \
                 self.assertRaisesRegex(CLIError, "unexpected incident-handler collection"):
                self._command(ResponsePlanShow)


class IncidentDataPlaneTests(unittest.TestCase):
    def _run(self, cls, result=None, **args):
        command = _bare_command(
            cls, agent_name="agent", resource_group="rg", extension_name="plan",
            **{"agent_url": None, **args},
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._data_plane_request", return_value=result) as request:
            output = command._handler({})
        return output, request

    def _arm(self, cls, **args):
        command = _bare_command(
            cls, agent_name="agent", resource_group="rg", extension_name="plan",
            **{"agent_url": None, **args},
        )
        return command

    def _http_error(self, status, text):
        response = Response()
        response.status_code = status
        response._content = text.encode()
        return HTTPError("failed", response=response)

    def _create(self, **kwargs):
        from azext_sre.custom import _incident_resource_create
        with patch("azext_sre.custom._data_plane_request", **kwargs.pop("dp", {})) as dp:
            return _incident_resource_create(
                None, "agent", "rg", "incidentFilters", "plan", {"a": 1},
                "/api/v2/incidentManagement/incidentFilters/plan", {"b": 2}, kwargs.pop("overwrite", False),
            ), dp

    def test_create_goes_through_arm_and_returns_data_plane_shape(self):
        envelope = {"name": "plan", "properties": {"value": {"handlingAgent": "responder"}}}
        with patch("azext_sre.custom._extension_resource_create", return_value=envelope):
            output, dp = self._create()
        self.assertEqual(output["name"], "plan")
        dp.assert_not_called()

    def test_duplicate_error_names_the_resource(self):
        with patch("azext_sre.custom._extension_resource_create",
                   side_effect=ResourceExistsError("exists")), \
             self.assertRaisesRegex(ResourceExistsError, "'plan'.*--overwrite"):
            self._create()

    def test_generic_arm_error_replays_on_data_plane_for_real_reason(self):
        generic = self._http_error(400, '{"error":{"message":"The extension configuration is invalid."}}')
        for dp_effect, expect in (
            (self._http_error(400, "Incident platform 'AzMonitor' does not match"), CLIError),
            (self._http_error(403, "Forbidden"), HTTPError),
        ):
            with self.subTest(status=dp_effect.response.status_code), \
                 patch("azext_sre.custom._extension_resource_create", side_effect=generic):
                with self.assertRaises(expect) as raised:
                    self._create(dp={"side_effect": dp_effect})
                if expect is CLIError:
                    self.assertIn("does not match", str(raised.exception))

    def test_other_arm_errors_are_not_replayed(self):
        with patch("azext_sre.custom._extension_resource_create",
                   side_effect=self._http_error(500, "boom")), \
             patch("azext_sre.custom._data_plane_request") as dp, \
             self.assertRaises(HTTPError):
            from azext_sre.custom import _incident_resource_create
            _incident_resource_create(None, "agent", "rg", "incidentFilters", "plan", {}, "/p", {}, True)
        dp.assert_not_called()

    def test_enable_disable_write_is_enabled_through_arm(self):
        from azext_sre.custom import ResponsePlanEnable, ResponsePlanDisable
        for cls, flag in ((ResponsePlanEnable, True), (ResponsePlanDisable, False)):
            with self.subTest(command=cls.__name__):
                command = _bare_command(cls, agent_name="a", resource_group="rg", extension_name="plan")
                existing = {"name": "plan", "properties": {"value": {
                    "handlingAgent": "s", "isEnabled": not flag, "handlingAgents": None}}}
                with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                     patch("azext_sre.custom._extension_resource_show", return_value=existing), \
                     patch("azext_sre.custom._incident_resource_create", return_value={"ok": 1}) as create, \
                     patch("azext_sre.custom._data_plane_request") as dp:
                    command._handler(None)
                dp.assert_not_called()
                value = create.call_args.args[5]
                self.assertEqual(value, {"handlingAgent": "s", "isEnabled": flag})
                self.assertTrue(create.call_args.args[8])

    def test_update_merges_only_passed_flags_through_arm(self):
        from azext_sre.custom import ResponsePlanUpdate
        values = dict(
            agent_name="a", resource_group="rg", extension_name="plan", platform=None,
            subagent=None, mode="review", priorities=["Sev0"], title_contains=None,
            title_not_contains=None, incident_types=None, impacted_service=None,
            owning_teams=None, merge_enabled=None, merge_window_hours=6,
            instructions=None, processing_guide=None)
        command = _bare_command(ResponsePlanUpdate, **values)
        existing = {"name": "plan", "properties": {"value": {
            "handlingAgent": "s", "priorities": ["Sev1"], "titleContains": "x", "handlingAgents": None}}}
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show", return_value=existing), \
             patch("azext_sre.custom._incident_resource_create", return_value={"ok": 1}) as create:
            command._handler(None)
        self.assertEqual(create.call_args.args[5], {
            "handlingAgent": "s", "priorities": ["Sev0"], "titleContains": "x",
            "agentMode": "review", "mergeWindowHours": 6})

    def test_update_requires_a_change_and_validates_mode(self):
        from azext_sre.custom import ResponsePlanUpdate
        base = dict(
            agent_name="a", resource_group="rg", extension_name="plan", platform=None,
            subagent=None, mode=None, priorities=None, title_contains=None,
            title_not_contains=None, incident_types=None, impacted_service=None,
            owning_teams=None, merge_enabled=None, merge_window_hours=None,
            instructions=None, processing_guide=None)
        for override in ({}, {"mode": "yolo"}, {"merge_window_hours": 0}):
            with self.subTest(override=override):
                command = _bare_command(ResponsePlanUpdate, **{**base, **override})
                with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                     self.assertRaises(CLIError):
                    command._handler(None)

    def test_list_table_format_mirrors_portal_columns(self):
        from azext_sre._transformers import response_plan_list_table_format
        rows = response_plan_list_table_format([{"name": "p", "properties": {
            "isEnabled": True, "incidentPlatform": "Icm", "handlingAgent": "s",
            "priorities": ["1", "2"], "agentMode": "review"}}, {"name": "q", "properties": {}}])
        self.assertEqual(dict(rows[0]), {
            "Name": "p", "Enabled": True, "Platform": "Icm", "Subagent": "s",
            "Priority": "1, 2", "Mode": "review"})
        self.assertEqual(rows[1]["Priority"], "All")

    def test_agent_url_reads_shared_agent_without_arm(self):
        from azext_sre.custom import ResponsePlanList
        command = _bare_command(
            ResponsePlanList, agent_name=None, resource_group=None,
            agent_url="https://a-b.c.eastus2.azuresre.ai/ignored",
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._data_plane_request", return_value={"value": [1]}) as request:
            command._handler({})
        self.assertEqual(request.call_args.kwargs["agent_url"], "https://a-b.c.eastus2.azuresre.ai")

    def test_quickstart_plan_warning(self):
        with self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
            _warn_if_quickstart_plan([{"name": "quickstart_response_plan"}], "agent")
        self.assertIn("quickstart response plan", logs.output[0])
        with patch("azext_sre.custom.logger") as log:
            _warn_if_quickstart_plan([{"name": "mine"}], "agent")
        log.warning.assert_not_called()

    def test_response_plan_creates_filter_and_linked_handler(self):
        from azext_sre.custom import ResponsePlanCreate
        command = _bare_command(
            ResponsePlanCreate, agent_name="a", resource_group="rg", extension_name="plan",
            platform="AzMonitor", subagent="responder", priorities=["Sev1"], title_contains=None,
            incident_types=None, impacted_service=None, owning_teams=None, merge_enabled=None, merge_window_hours=None,
            title_not_contains=None, mode="review", disabled=None,
            instructions="Check logs", processing_guide=None, overwrite=None)
        created = []

        def fake_create(cli_ctx, agent, rg, ext_type, name, value, path, body, overwrite):
            created.append((ext_type, value))
            return {"ok": ext_type}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._incident_resource_create", side_effect=fake_create), \
             patch("azext_sre.custom._extension_resource_list", return_value={"value": []}):
            result = command._handler(None)
        self.assertEqual(set(result), {"filter", "handler"})
        flt = created[0][1]
        self.assertEqual((flt["handlingAgent"], flt["agentMode"], flt["isEnabled"]), ("responder", "review", True))
        self.assertEqual(created[1][1]["incidentFilterId"], "plan")

    def test_response_plan_rejects_bad_mode(self):
        from azext_sre.custom import ResponsePlanCreate
        command = _bare_command(
            ResponsePlanCreate, agent_name="a", resource_group="rg", extension_name="plan",
            platform="AzMonitor", subagent="s", priorities=None, title_contains=None,
            incident_types=None, impacted_service=None, owning_teams=None, merge_enabled=None, merge_window_hours=None,
            title_not_contains=None, mode="yolo", disabled=None,
            instructions=None, processing_guide=None, overwrite=None)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             self.assertRaises(CLIError):
            command._handler(None)

    def test_agent_url_validation(self):
        for kwargs in (
            {"agent_url": "http://a.eastus2.azuresre.ai", "agent_name": None, "resource_group": None},
            {"agent_url": "https://evil.example.com", "agent_name": None, "resource_group": None},
            {"agent_url": "https://a.eastus2.azuresre.ai", "agent_name": "x", "resource_group": "rg"},
            {"agent_url": None, "agent_name": "x", "resource_group": None},
        ):
            from azext_sre.custom import ResponsePlanList
            command = _bare_command(ResponsePlanList, **kwargs)
            with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                 self.assertRaises(CLIError):
                command._handler({})

    def test_endpoint_resolution_and_missing_endpoint(self):
        with patch("azext_sre.custom._resolve_agent_resource_id", return_value="/agent"), \
             patch("azext_sre.custom._arm_request",
                   return_value={"properties": {"agentEndpoint": "https://agent.example"}}):
            self.assertEqual(_resolve_agent_endpoint(None, "agent", "rg"), "https://agent.example")
        with patch("azext_sre.custom._resolve_agent_resource_id", return_value="/agent"), \
             patch("azext_sre.custom._arm_request", return_value={"properties": {}}), \
             self.assertRaises(CLIError):
            _resolve_agent_endpoint(None, "agent", "rg")

    def test_request_uses_data_plane_token_and_json(self):
        response = Response()
        response.status_code = 200
        response._content = b'{"id":"plan"}'
        with patch("azext_sre.custom._resolve_agent_endpoint", return_value="https://agent.example/"), \
             patch("azext_sre.custom.send_raw_request", return_value=response) as request:
            result = _data_plane_request(None, "agent", "rg", "PUT", "/api/plan", body={"id": "plan"})
        self.assertEqual(result, {"id": "plan"})
        self.assertEqual(request.call_args.args, (None, "PUT", "https://agent.example/api/plan"))
        self.assertEqual(request.call_args.kwargs["resource"], "https://azuresre.dev")
        self.assertEqual(json.loads(request.call_args.kwargs["body"]), {"id": "plan"})

    def test_only_optional_404_is_suppressed(self):
        for code, missing_ok in ((404, True), (404, False), (403, True), (500, True)):
            response = Response()
            response.status_code = code
            error = HTTPError("request failed", response=response)
            with self.subTest(code=code, missing_ok=missing_ok), \
                 patch("azext_sre.custom._resolve_agent_endpoint", return_value="https://agent.example"), \
                 patch("azext_sre.custom.send_raw_request", side_effect=error):
                if code == 404 and missing_ok:
                    self.assertIsNone(_data_plane_request(None, "agent", "rg", "GET", "/api/plan",
                                                         missing_ok=True))
                else:
                    with self.assertRaises(HTTPError):
                        _data_plane_request(None, "agent", "rg", "GET", "/api/plan", missing_ok=missing_ok)


class ToolsShapeValidationTests(unittest.TestCase):
    """--extension-type tools' inner shape is confirmed via sreagent-runtime
    (the real SRE Agent runtime/CLI source) -- Agent.Cli/Models/ToolSpecV2.cs
    + Kusto/Link/Python/HttpClientToolSpecV2.cs."""

    def test_python_tool_alias_and_runtime_type_preserve_executable_configuration(self):
        for tool_type in ("PythonTool", "PythonFunctionTool"):
            with self.subTest(tool_type=tool_type):
                value = {
                    "type": tool_type, "description": "Read-only evidence",
                    "functionCode": "def main() -> dict:\n    return {'status': 200}\n",
                    "parameters": [], "timeoutSeconds": 30, "dependencies": [],
                    "authEnabled": False, "authScopes": [],
                }
                encoded = _encode_extension_value(json.dumps(value), "tools")
                decoded = json.loads(base64.b64decode(encoded))
                self.assertEqual(decoded, {**value, "type": "PythonFunctionTool"})

    def test_python_tool_types_reject_invalid_executable_and_authentication_fields(self):
        invalid = {
            "functionCode": 123, "dependencies": "requests",
            "authEnabled": "false", "authScopes": "https://example.com",
        }
        for tool_type in ("PythonTool", "PythonFunctionTool"):
            for field, value in invalid.items():
                with self.subTest(tool_type=tool_type, field=field), self.assertRaises(CLIError):
                    _encode_extension_value(json.dumps({
                        "type": tool_type, "functionCode": "def main(): pass", field: value,
                    }), "tools")

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


class SubagentsShapeValidationTests(unittest.TestCase):
    """--extension-type subagents' inner shape is confirmed via a LIVE
    benchmark test (2026-11-05) against a real SRE Agent, using the
    microsoft/sre-agent zava-aks-postgres lab's exact agents/*.json
    payloads -- PUT to the normal ARM-proxied .../subagents/{name} route
    succeeds with this shape (a prior session's conclusion that subagents
    were architecturally uncreatable via ARM was wrong -- see the comment
    above EXTENSION_API_VERSION for the full correction)."""

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "instructions": "You are the application evidence specialist.",
            "handoffDescription": "Use for read-only application evidence.",
            "tools": ["ReadFile"],
            "mcpTools": [],
            "commonTools": [],
            "allowedSkills": ["zava-application-evidence"],
            "allowParallelToolCalls": True,
        })
        encoded = _encode_extension_value(raw, "subagents")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_accepts_embedded_pretooluse_hook(self):
        raw = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": False,
            "hooks": {
                "PreToolUse": [{
                    "type": "command", "matcher": "(?s:.*)",
                    "timeout": 30, "failMode": "block", "script": "print('hi')",
                }],
            },
        })
        encoded = _encode_extension_value(raw, "subagents")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_non_object(self):
        with self.assertRaises(CLIError):
            _encode_extension_value(json.dumps(["not", "an", "object"]), "subagents")

    def test_instructions_is_type_checked_but_not_presence_required(self):
        # Matches every other field's convention (_require_str/_require_bool/
        # _require_str_list only type-check when the key is present) --
        # absence is allowed client-side; the server is the source of truth
        # for which fields are actually mandatory.
        raw = json.dumps({
            "handoffDescription": "y", "tools": [], "mcpTools": [],
            "commonTools": [], "allowedSkills": [], "allowParallelToolCalls": True,
        })
        encoded = _encode_extension_value(raw, "subagents")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

        bad = json.dumps({"instructions": 123})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(bad, "subagents")
        self.assertIn("--value.instructions", str(raised.exception))

    def test_rejects_non_list_tools(self):
        raw = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": "ReadFile", "mcpTools": [], "commonTools": [],
            "allowedSkills": [], "allowParallelToolCalls": True,
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.tools must be a JSON array of strings", str(raised.exception))

    def test_rejects_non_bool_allow_parallel_tool_calls(self):
        raw = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": "true",
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.allowParallelToolCalls", str(raised.exception))

    def test_rejects_hooks_not_object(self):
        raw = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": True, "hooks": ["not", "an", "object"],
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.hooks must be a JSON object", str(raised.exception))

    def test_hook_entry_script_is_type_checked_but_not_presence_required(self):
        raw = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": True,
            "hooks": {"PreToolUse": [{"type": "command", "matcher": "(?s:.*)", "failMode": "block"}]},
        })
        encoded = _encode_extension_value(raw, "subagents")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

        bad = json.dumps({"hooks": {"PreToolUse": [{"script": 123}]}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(bad, "subagents")
        self.assertIn("script", str(raised.exception))


class HooksShapeValidationTests(unittest.TestCase):
    """--extension-type hooks' inner shape is confirmed via sreagent-runtime
    Agent.Cli/Models/HookV2.cs's HookSpecV2/HookDefinitionModel, which carry
    explicit JsonPropertyName wire-field attributes. eventType's full set of
    4 values (Start/PreToolUse/PostToolUse/Stop) is confirmed via the public
    docs (sre.azure.com/docs/capabilities/agent-hooks) -- the portal UI only
    exposes PostToolUse/Stop today, but the REST API v2 this CLI calls
    supports all four, so client-side validation must not be narrower than
    the real API."""

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

    def test_accepts_start_and_pretooluse_event_types(self):
        for event_type in ("Start", "PreToolUse"):
            raw = json.dumps({"eventType": event_type})
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

    def test_accepts_allow_and_block_fail_modes(self):
        # Live-probed against a real agent: failMode governs what happens
        # if the hook itself errors/times out (not its allow/deny
        # decision). Only "Allow"/"Block" (case-insensitive) are accepted.
        for fail_mode in ("Allow", "allow", "Block", "block"):
            raw = json.dumps({"hook": {"type": "command", "command": "exit 1", "failMode": fail_mode}})
            encoded = _encode_extension_value(raw, "hooks")
            self.assertEqual(base64.b64decode(encoded).decode("utf-8"), raw)

    def test_rejects_invalid_fail_mode(self):
        # "Deny"/"fail"/"continue" look plausible but are rejected by the
        # real API with a generic "extension configuration is invalid"
        # error -- confirmed via live probing against a real agent.
        raw = json.dumps({"hook": {"type": "command", "command": "exit 1", "failMode": "Deny"}})
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "hooks")
        self.assertIn("--value.hook.failMode must be", str(raised.exception))


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


class RepoProviderDetectionTests(unittest.TestCase):
    """_detect_repo_provider maps a repo's URL host to the provider enum
    the 'repositories' extension type expects."""

    def test_detects_github(self):
        self.assertEqual(_detect_repo_provider("https://github.com/org/repo"), "GitHub")

    def test_detects_azure_devops_dev_azure_com(self):
        self.assertEqual(
            _detect_repo_provider("https://dev.azure.com/org/project/_git/repo"), "AzureDevOps",
        )

    def test_detects_azure_devops_visualstudio_com(self):
        self.assertEqual(
            _detect_repo_provider("https://org.visualstudio.com/project/_git/repo"), "AzureDevOps",
        )

    def test_rejects_unknown_host(self):
        with self.assertRaises(CLIError) as raised:
            _detect_repo_provider("https://gitlab.com/org/repo")
        self.assertIn("--provider", str(raised.exception))


class RepoConnectTests(unittest.TestCase):
    """RepoConnect is a one-command golden path: it must fetch a token itself
    (never ask the user to paste one) and issue the same two
    _extension_resource_create() calls a user would otherwise build by hand
    (one for the auth extension, one for the repository extension).
    """

    def _run_github(self, repo_url="https://github.com/org/repo", **extra_args):
        args = {
            "agent_name": "myagent", "resource_group": "rg", "repo_url": repo_url,
            "provider": None, "display_name": None, "branch": None,
            "github_account": None, "github_token": None, "devops_organization": None,
            "devops_auth_type": "pat", "devops_identity": None,
            "devops_federated_client_id": None, "devops_federated_tenant_id": None,
        }
        args.update(extra_args)
        command = _bare_command(RepoConnect, **args)
        calls = []

        def fake_extension_resource_create(
            cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False
        ):
            calls.append((extension_type, extension_name, raw_value, overwrite))
            return {"properties": {"value": "stub"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create), \
             patch("azext_sre.custom._github_token", lambda account=None, explicit_token=None: "gh-token-123"):
            result = command._handler({})
        return result, calls

    def test_github_flow_never_asks_for_a_pat_and_wires_both_extensions(self):
        _, calls = self._run_github()
        self.assertEqual(len(calls), 2)

        ext_type, ext_name, raw_value, overwrite = calls[0]
        self.assertEqual(ext_type, "githubAuths")
        self.assertEqual(ext_name, "github_com")
        self.assertTrue(overwrite)
        self.assertEqual(json.loads(raw_value), {"authType": "Pat", "pat": "gh-token-123"})

        ext_type, ext_name, raw_value, overwrite = calls[1]
        self.assertEqual(ext_type, "repositories")
        self.assertEqual(ext_name, "repo")  # default display name from URL tail
        repo_value = json.loads(raw_value)
        self.assertEqual(repo_value["url"], "https://github.com/org/repo")
        self.assertEqual(repo_value["type"], "GitHub")
        self.assertEqual(repo_value["description"], "repo")

    def test_display_name_and_branch_are_passed_through(self):
        _, calls = self._run_github(display_name="my-repo", branch="main")
        repo_value = json.loads(calls[1][2])
        self.assertEqual(repo_value["description"], "my-repo")
        self.assertEqual(repo_value["branch"], "main")

    def _run_devops(self, **extra_args):
        args = {
            "agent_name": "myagent", "resource_group": "rg",
            "repo_url": "https://dev.azure.com/contoso/project/_git/repo",
            "provider": None, "display_name": None, "branch": None,
            "github_account": None, "github_token": None, "devops_organization": None,
            "devops_auth_type": "pat", "devops_identity": None,
            "devops_federated_client_id": None, "devops_federated_tenant_id": None,
        }
        args.update(extra_args)
        command = _bare_command(RepoConnect, **args)
        calls = []

        def fake_extension_resource_create(
            cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False
        ):
            calls.append((extension_type, extension_name, raw_value, overwrite))
            return {"properties": {"value": "stub"}}

        return command, calls, fake_extension_resource_create

    def test_azure_devops_flow_mints_its_own_pat(self):
        command, calls, fake_extension_resource_create = self._run_devops()
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create), \
             patch("azext_sre.custom._devops_pat_token", lambda cli_ctx, org, name: "ado-pat-xyz"):
            command._handler({})

        ext_type, ext_name, raw_value, _overwrite = calls[0]
        self.assertEqual(json.loads(raw_value), {"authType": "Pat", "pat": "ado-pat-xyz"})
        self.assertEqual(ext_type, "azureDevOpsAuths")
        self.assertEqual(ext_name, "contoso")  # auth extension-name is the org, not a fixed string
        repo_value = json.loads(calls[1][2])
        self.assertEqual(repo_value["type"], "AzureDevOps")

    def test_azure_devops_managed_identity_skips_pat_minting_entirely(self):
        command, calls, fake_extension_resource_create = self._run_devops(
            devops_auth_type="managed-identity",
            devops_identity="/subscriptions/x/.../userAssignedIdentities/mi",
        )

        def fail_if_called(*args, **kwargs):
            raise AssertionError("_devops_pat_token must not be called for managed-identity auth")

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create), \
             patch("azext_sre.custom._devops_pat_token", fail_if_called):
            command._handler({})

        auth_value = json.loads(calls[0][2])
        self.assertEqual(
            auth_value,
            {"authType": "ManagedIdentity", "identity": "/subscriptions/x/.../userAssignedIdentities/mi"},
        )

    def test_azure_devops_managed_identity_requires_identity(self):
        command, _calls, fake_extension_resource_create = self._run_devops(devops_auth_type="managed-identity")
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create):
            with self.assertRaises(CLIError) as raised:
                command._handler({})
        self.assertIn("--devops-identity is required", str(raised.exception))

    def test_azure_devops_managed_identity_federated_fields_both_or_neither(self):
        command, _calls, fake_extension_resource_create = self._run_devops(
            devops_auth_type="managed-identity",
            devops_identity="/subscriptions/x/.../mi",
            devops_federated_client_id="client-id-only",
        )
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create):
            with self.assertRaises(CLIError) as raised:
                command._handler({})
        self.assertIn("must both be provided or both be omitted", str(raised.exception))

    def test_pat_policy_violation_suggests_managed_identity(self):
        command, _calls, fake_extension_resource_create = self._run_devops()

        def fake_pat_token(cli_ctx, org, name):
            raise CLIError(
                "'sre repo connect' failed: Bad Request("
                '{"message":"DisablePatCreationPolicyViolation"})'
            )

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create), \
             patch("azext_sre.custom._devops_pat_token", fake_pat_token):
            with self.assertRaises(CLIError) as raised:
                command._handler({})
        self.assertIn("--devops-auth-type managed-identity", str(raised.exception))

    def test_azure_devops_pat_is_redacted_in_the_returned_result(self):
        """Live-confirmed on a real Azure DevOps org: extension creation
        redacts a freshly-minted PAT server-side for githubAuths (comes back
        as "******"), but NOT for azureDevOpsAuths -- the real PAT is
        echoed back verbatim. RepoConnect must redact it client-side
        regardless, so this command never prints a live secret.
        """
        command, _calls, _fake_extension_resource_create = self._run_devops()

        def fake_extension_resource_create_with_real_pat(
            cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False
        ):
            if extension_type == "azureDevOpsAuths":
                return {"properties": {"value": {"authType": "Pat", "pat": "ado-pat-xyz"}}}
            return {"properties": {"value": "stub"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create_with_real_pat), \
             patch("azext_sre.custom._devops_pat_token", lambda cli_ctx, org, name: "ado-pat-xyz"):
            result = command._handler({})

        self.assertEqual(result["auth"]["properties"]["value"]["pat"], "******")

    def test_github_pat_stays_redacted_in_the_returned_result(self):
        command = _bare_command(
            RepoConnect, agent_name="myagent", resource_group="rg",
            repo_url="https://github.com/org/repo", provider=None, display_name=None,
            branch=None, github_account=None, github_token=None, devops_organization=None,
            devops_auth_type="pat", devops_identity=None,
            devops_federated_client_id=None, devops_federated_tenant_id=None,
        )

        def fake_extension_resource_create_with_real_pat(
            cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False
        ):
            if extension_type == "githubAuths":
                return {"properties": {"value": {"authType": "Pat", "pat": "******"}}}
            return {"properties": {"value": "stub"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_extension_resource_create_with_real_pat), \
             patch("azext_sre.custom._github_token", lambda account=None, explicit_token=None: "gh-token-123"):
            result = command._handler({})

        self.assertEqual(result["auth"]["properties"]["value"]["pat"], "******")


class GithubTokenResolutionTests(unittest.TestCase):
    """_github_token's two-layer resolution (explicit/env -> native OAuth
    Device Flow) must try each layer in order and stop at the first one
    that yields a token. The earlier 'gh' CLI reuse tier was dropped per
    Paul/Preeti's feedback that a dual-mode token source (gh vs. device
    flow) would add environment-dependent ambiguity with no real benefit,
    since the device flow alone already removes the hard 'gh' dependency."""

    def setUp(self):
        self._env_backup = {k: os.environ.get(k) for k in ("GITHUB_TOKEN", "GH_TOKEN")}
        os.environ.pop("GITHUB_TOKEN", None)
        os.environ.pop("GH_TOKEN", None)

    def tearDown(self):
        for key, value in self._env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_explicit_token_wins_over_everything_else(self):
        with patch("azext_sre.custom._github_device_flow") as fake_device_flow:
            token = _github_token(explicit_token="explicit-123")
        self.assertEqual(token, "explicit-123")
        fake_device_flow.assert_not_called()

    def test_github_token_env_var_is_used_when_no_explicit_token(self):
        os.environ["GITHUB_TOKEN"] = "env-token-456"
        with patch("azext_sre.custom._github_device_flow") as fake_device_flow:
            token = _github_token()
        self.assertEqual(token, "env-token-456")
        fake_device_flow.assert_not_called()

    def test_gh_token_env_var_is_used_as_a_fallback_name(self):
        os.environ["GH_TOKEN"] = "gh-env-789"
        with patch("azext_sre.custom._github_device_flow") as fake_device_flow:
            token = _github_token()
        self.assertEqual(token, "gh-env-789")
        fake_device_flow.assert_not_called()

    def test_falls_back_to_device_flow_when_no_explicit_or_env_token(self):
        with patch("azext_sre.custom._github_device_flow", return_value="device-flow-token") as fake_device_flow:
            token = _github_token()
        self.assertEqual(token, "device-flow-token")
        fake_device_flow.assert_called_once()


class GithubDeviceFlowTests(unittest.TestCase):
    """_github_device_flow implements RFC 8628 against GitHub's two public
    endpoints -- no 'gh' CLI, no client secret."""

    def test_happy_path_polls_until_authorized_and_returns_the_token(self):
        code_response = SimpleNamespace(
            json=lambda: {
                "device_code": "devcode-abc",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "interval": 0,
                "expires_in": 900,
            },
            raise_for_status=lambda: None,
        )
        token_responses = iter([
            SimpleNamespace(json=lambda: {"error": "authorization_pending"}, raise_for_status=lambda: None),
            SimpleNamespace(json=lambda: {"access_token": "real-device-flow-token"}, raise_for_status=lambda: None),
        ])

        def fake_post(url, **kwargs):
            if url.endswith("/login/device/code"):
                return code_response
            return next(token_responses)

        with patch("requests.post", side_effect=fake_post), \
             patch("time.sleep"), \
             patch("azure.cli.core.util.open_page_in_browser"):
            token = _github_device_flow()
        self.assertEqual(token, "real-device-flow-token")

    def test_denied_authorization_raises_a_clear_error(self):
        code_response = SimpleNamespace(
            json=lambda: {
                "device_code": "devcode-abc",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "interval": 0,
                "expires_in": 900,
            },
            raise_for_status=lambda: None,
        )
        denied_response = SimpleNamespace(
            json=lambda: {"error": "access_denied", "error_description": "The user denied the request"},
            raise_for_status=lambda: None,
        )

        def fake_post(url, **kwargs):
            if url.endswith("/login/device/code"):
                return code_response
            return denied_response

        with patch("requests.post", side_effect=fake_post), \
             patch("time.sleep"), \
             patch("azure.cli.core.util.open_page_in_browser"), \
             self.assertRaises(CLIError) as raised:
            _github_device_flow()
        self.assertIn("denied", str(raised.exception))


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


class ExtensionTenantGateTests(unittest.TestCase):
    """The service rejects every agent extension call from a non-internal
    tenant. The CLI should say that plainly."""

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def test_3p_agent_skips_arm_and_caches_the_detection(self):
        from azext_sre import custom

        status = {"features": {"isFirstParty": False, "scheduledTasks": True}}
        with tempfile.TemporaryDirectory() as tmp, \
             patch.dict("os.environ", {"AZSRE_EXTENSION_ROUTE": ""}), \
             patch("azext_sre.custom._feature_cache_path", return_value=os.path.join(tmp, "f.json")), \
             patch.dict(custom._FEATURES_MEMORY, clear=True), \
             patch("azext_sre.custom._arm_request") as arm, \
             patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._data_plane_request", side_effect=[status, {"value": []}, {"value": []}]) as dp:
            _extension_resource_list(None, "myagent", "rg", "tools")
            custom._FEATURES_MEMORY.clear()
            _extension_resource_list(None, "myagent", "rg", "tools")
            arm.assert_not_called()
            paths = [c[0][4] for c in dp.call_args_list]
            self.assertEqual(paths, ["/api/v1/feature/status", "/api/v2/extendedAgent/tools", "/api/v2/extendedAgent/tools"])

    def test_1p_agent_keeps_the_arm_route(self):
        from azext_sre import custom

        with patch.dict("os.environ", {"AZSRE_EXTENSION_ROUTE": ""}), \
             patch("azext_sre.custom._feature_cache_key", return_value="k"), \
             patch.dict(custom._FEATURES_MEMORY, {"k": {"isFirstParty": True}}, clear=True), \
             patch("azext_sre.custom._arm_request", return_value={"value": []}) as arm, \
             patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._data_plane_request") as dp:
            _extension_resource_list(None, "myagent", "rg", "tools")
            arm.assert_called()
            dp.assert_not_called()

    def test_unknown_features_fall_back_to_the_arm_error(self):
        from azext_sre import custom

        with patch.dict("os.environ", {"AZSRE_EXTENSION_ROUTE": ""}), \
             patch("azext_sre.custom._feature_cache_key", return_value="k"), \
             patch.dict(custom._FEATURES_MEMORY, {"k": {}}, clear=True), \
             patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", return_value={"value": []}) as dp:
            _extension_resource_list(None, "myagent", "rg", "tools")
            self.assertEqual(dp.call_args[0][4], "/api/v2/extendedAgent/tools")

    def test_disabled_feature_blocks_create_with_a_clear_message(self):
        from azext_sre import custom

        with patch.dict("os.environ", {"AZSRE_EXTENSION_ROUTE": ""}), \
             patch("azext_sre.custom._feature_cache_key", return_value="k"), \
             patch.dict(custom._FEATURES_MEMORY, {"k": {"isFirstParty": False, "httpTriggers": False}}, clear=True), \
             patch("azext_sre.custom._data_plane_request") as dp:
            with self.assertRaises(CLIError) as ctx:
                _extension_resource_create(None, "myagent", "rg", "httpTriggers", "t", "{}")
            self.assertIn("HTTP triggers enabled", str(ctx.exception))
            dp.assert_not_called()

    def _gate_error(self):
        response = Response()
        response.status_code = 400
        response._content = (
            b'{"error":{"message":"Agent Extensions are not available for this tenant. '
            b'This feature is restricted to internal tenants only."}}'
        )
        return HTTPError("400 Client Error", response=response)

    def test_each_extension_operation_explains_the_tenant_gate(self):
        calls = (
            (_extension_resource_create, ("subagents", "t", '{"url": "https://github.com/a/b"}'), {"overwrite": True}),
            (_extension_resource_show, ("subagents", "t"), {}),
            (_extension_resource_list, ("subagents",), {}),
            (_extension_resource_delete, ("subagents", "t"), {}),
        )
        for func, args, kwargs in calls:
            with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                 patch("azext_sre.custom._arm_request", side_effect=self._gate_error()):
                with self.assertRaises(CLIError) as ctx:
                    func(None, "myagent", "rg", *args, **kwargs)
            self.assertIn("This tenant can't use 'subagents' yet", str(ctx.exception))

    def test_tools_fall_back_to_the_agent_api(self):
        envelope = {"name": "t", "type": "ExtendedAgentTool", "properties": {"type": "LinkTool"}}
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", return_value={"value": [envelope]}) as dp:
            result = _extension_resource_list(None, "myagent", "rg", "tools")
        self.assertEqual(dp.call_args[0][3:5], ("GET", "/api/v2/extendedAgent/tools"))
        self.assertEqual(result["value"][0]["properties"]["value"], {"type": "LinkTool"})

    def test_instructions_and_scheduled_tasks_use_their_own_routes(self):
        for extension_type, path in (("commonPrompts", "/api/v2/extendedAgent/commonprompts"),
                                     ("scheduledTasks", "/api/v2/extendedAgent/scheduledtasks")):
            with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                 patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
                 patch("azext_sre.custom._data_plane_request", return_value={"value": []}) as dp:
                _extension_resource_list(None, "myagent", "rg", extension_type)
            self.assertEqual(dp.call_args[0][4], path)

    def test_repo_connect_calls_use_the_portal_routes(self):
        cases = (
            ("githubAuths", "github_com", '{"authType": "Pat", "pat": "p"}',
             "/api/v2/github/domains/github_com", {"authType": "Pat", "pat": "p"}),
            ("azureDevOpsAuths", "contoso", '{"authType": "Pat", "pat": "p"}',
             "/api/v2/azuredevops/orgs/contoso", {"authType": "Pat", "pat": "p"}),
            ("repositories", "r", '{"url": "https://github.com/a/r", "type": "GitHub"}',
             "/api/v2/repos/r", {"name": "r", "type": "CodeRepo",
                                  "properties": {"url": "https://github.com/a/r", "type": "GitHub"}}),
        )
        for extension_type, name, value, path, body in cases:
            with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                 patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
                 patch("azext_sre.custom._data_plane_request", return_value={"success": True}) as dp:
                _extension_resource_create(None, "myagent", "rg", extension_type, name, value, overwrite=True)
            self.assertEqual(dp.call_args[0][3:5], ("PUT", path))
            self.assertEqual(dp.call_args.kwargs["body"], body)

    def test_auth_secret_is_not_echoed_back(self):
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", return_value={"success": True}):
            result = _extension_resource_create(
                None, "myagent", "rg", "githubAuths", "github_com",
                '{"authType": "Pat", "pat": "secret"}', overwrite=True)
        self.assertNotIn("secret", json.dumps(result))

    def test_triggers_plugins_and_settings_use_their_own_routes(self):
        cases = (
            ("httpTriggers", "/api/v2/extendedAgent/httpTriggers/t", "HttpTrigger"),
            ("pluginMarketplaces", "/api/v2/extendedAgent/pluginMarketplaces/t", "Marketplace"),
            ("pluginInstallations", "/api/v2/extendedAgent/pluginInstallations/t", "PluginInstallation"),
            ("globalSettings", "/api/v2/extendedAgent/globalSettings/t", "GlobalSettings"),
        )
        for extension_type, path, envelope_type in cases:
            with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                 patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
                 patch("azext_sre.custom._encode_extension_value"), \
                 patch("azext_sre.custom._data_plane_request", return_value={}) as dp:
                _extension_resource_create(None, "myagent", "rg", extension_type, "t", "{}", overwrite=True)
            self.assertEqual(dp.call_args[0][3:5], ("PUT", path))
            self.assertEqual(dp.call_args.kwargs["body"]["type"], envelope_type)

    def test_global_settings_cannot_be_listed_or_deleted_directly(self):
        for func, args in ((_extension_resource_list, ()), (_extension_resource_delete, ("default",))):
            with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                 patch("azext_sre.custom._arm_request", side_effect=self._gate_error()):
                with self.assertRaises(CLIError):
                    func(None, "myagent", "rg", "globalSettings", *args)

    def test_auth_and_repo_read_and_delete_use_the_portal_routes(self):
        listing = {"values": [{"name": "github_com", "authType": "Pat"}]}
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", return_value=listing) as dp:
            shown = _extension_resource_show(None, "myagent", "rg", "githubAuths", "github_com")
            self.assertEqual(shown["properties"]["value"]["authType"], "Pat")
            self.assertEqual(dp.call_args[0][3:5], ("GET", "/api/v2/github/domains"))
            _extension_resource_delete(None, "myagent", "rg", "azureDevOpsAuths", "my org")
            self.assertEqual(dp.call_args[0][3:5], ("DELETE", "/api/v2/azuredevops/orgs?org=my%20org"))
            _extension_resource_delete(None, "myagent", "rg", "repositories", "r")
            self.assertEqual(dp.call_args[0][3:5], ("DELETE", "/api/v2/repos/r"))

    def test_response_plan_filters_use_the_portal_route(self):
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", return_value={}) as dp:
            _extension_resource_create(None, "myagent", "rg", "incidentFilters", "p", '{"incidentPlatform": "PagerDuty"}', overwrite=True)
            self.assertEqual(dp.call_args[0][3:5], ("PUT", "/api/v2/incidentManagement/incidentFilters/p"))
            self.assertEqual(dp.call_args.kwargs["body"]["type"], "IncidentFilter")

    def test_direct_create_sends_portal_envelope(self):
        spec = '{"type": "LinkTool", "description": "d"}'
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=self._gate_error()), \
             patch("azext_sre.custom._data_plane_request", side_effect=[None, {}]) as dp:
            _extension_resource_create(None, "myagent", "rg", "tools", "t", spec)
        body = dp.call_args_list[1].kwargs["body"]
        self.assertEqual(body, {"name": "t", "type": "ExtendedAgentTool",
                                "properties": {"type": "LinkTool", "description": "d"}})

    def test_other_errors_pass_through(self):
        response = Response()
        response.status_code = 500
        response._content = b'{"error":{"message":"boom"}}'
        error = HTTPError("500 Server Error", response=response)
        with patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
             patch("azext_sre.custom._arm_request", side_effect=error):
            with self.assertRaises(HTTPError):
                _extension_resource_list(None, "myagent", "rg", "tools")


class ExtensionCommandResourceIdTests(unittest.TestCase):
    """Proves each shared _extension_resource_*() helper builds the exact
    .../agents/{name}/{extensionType}[/{name}] resource ID and wire envelope
    confirmed against AgentExtensionsApiController.cs, without making a real
    ARM call. These helpers back every noun-specific facade (tool/skill/
    hook/instructions/workflow/plugin/repo connect/agent settings).
    """

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def _run_with_mocks(self, func, *args, cli_responses=None, arm_response=None, **kwargs):
        cli_responses = list(cli_responses or [])
        arm_calls = []

        def fake_cli_invoke(cli_ctx, *a, allow_missing=False):
            return cli_responses.pop(0)

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            arm_calls.append(
                {"method": method, "resource_id": resource_id, "api_version": api_version, "body": body}
            )
            return arm_response

        with patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = func(*args, **kwargs)
        return result, arm_calls

    def test_create_builds_proxy_envelope_and_resource_id(self):
        _, arm_calls = self._run_with_mocks(
            _extension_resource_create,
            None, "myagent", "rg", "tools", "mytool", '{"kind": "ToolList"}',
            overwrite=True,
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

    def test_create_without_overwrite_blocks_when_already_exists(self):
        with self.assertRaises(ResourceExistsError) as raised:
            self._run_with_mocks(
                _extension_resource_create,
                None, "myagent", "rg", "tools", "mytool", '{"kind": "ToolList"}',
                overwrite=False,
                cli_responses=[self._AGENT],
                arm_response={"properties": {"value": _encode_extension_value('{"kind": "ToolList"}')}},
            )
        self.assertIn("--overwrite", str(raised.exception))

    def test_create_without_overwrite_proceeds_when_missing(self):
        arm_calls = []
        responses = [None, {"properties": {"value": _encode_extension_value('{"kind": "ToolList"}')}}]

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            arm_calls.append(method)
            return responses.pop(0)

        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *a, allow_missing=False: self._AGENT), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            _extension_resource_create(
                None, "myagent", "rg", "tools", "mytool", '{"kind": "ToolList"}', overwrite=False,
            )
        self.assertEqual(arm_calls, ["GET", "PUT"])

    def test_show_uses_missing_ok_and_raises_not_found_on_none(self):
        with self.assertRaises(ResourceNotFoundError):
            self._run_with_mocks(
                _extension_resource_show,
                None, "myagent", "rg", "skills", "myskill",
                cli_responses=[self._AGENT], arm_response=None,
            )

    def test_list_decodes_every_item_in_the_value_array(self):
        encoded = _encode_extension_value('{"n": 1}')
        result, arm_calls = self._run_with_mocks(
            _extension_resource_list,
            None, "myagent", "rg", "tools",
            cli_responses=[self._AGENT],
            arm_response={"value": [{"properties": {"value": encoded}}]},
        )
        self.assertEqual(
            arm_calls[0]["resource_id"],
            "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent/tools",
        )
        self.assertEqual(result["value"][0]["properties"]["value"], {"n": 1})

    def test_delete_passes_missing_ok_true(self):
        _, arm_calls = self._run_with_mocks(
            _extension_resource_delete,
            None, "myagent", "rg", "hooks", "myhook",
            cli_responses=[self._AGENT], arm_response={},
        )
        self.assertEqual(arm_calls[0]["method"], "DELETE")
        self.assertEqual(
            arm_calls[0]["resource_id"],
            "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent/hooks/myhook",
        )


class PinnedExtensionFacadeTests(unittest.TestCase):
    """'sre tool'/'sre skill'/'sre hook'/'sre instructions'/
    'sre plugin marketplace'/'sre plugin install' are thin noun-specific
    front doors, modeled on the portal's own Extensions nav (Tools/Skills/
    Hooks/Custom instructions/Plugins), that must call the shared
    _extension_resource_create/show/list/delete() helpers with the
    extension type pinned to the right value -- never reimplement the ARM
    call themselves.
    """

    def _assert_forwards(self, command_cls, extension_type, expected_call,
                          args_kwargs, fake_result=None):
        calls = {"create": [], "show": [], "list": [], "delete": []}

        def make_fake(name, *, needs_name=True):
            def fake(cli_ctx, agent_name, resource_group, ext_type, *rest, **kwargs):
                calls[name].append((agent_name, resource_group, ext_type, *rest, kwargs))
                return fake_result
            return fake

        command = _bare_command(command_cls, **args_kwargs)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", make_fake("create")), \
             patch("azext_sre.custom._extension_resource_show", make_fake("show")), \
             patch("azext_sre.custom._extension_resource_list", make_fake("list")), \
             patch("azext_sre.custom._extension_resource_delete", make_fake("delete")):
            result = command._handler({})

        verb, call_args = expected_call
        self.assertEqual(len(calls[verb]), 1)
        actual = calls[verb][0]
        self.assertEqual(actual[0], "myagent")
        self.assertEqual(actual[1], "rg")
        self.assertEqual(actual[2], extension_type)
        self.assertEqual(actual[3:], call_args)
        self.assertEqual(sum(len(v) for v in calls.values()), 1)
        self.assertEqual(result, fake_result)

    def test_tool_create_pins_extension_type_tools(self):
        self._assert_forwards(
            ToolCreate, "tools",
            ("create", ("mytool", '{"toolType": "LinkTool"}', {"overwrite": True})),
            {
                "agent_name": "myagent", "resource_group": "rg",
                "extension_name": "mytool", "value": '{"toolType": "LinkTool"}',
                "overwrite": True,
            },
        )

    def test_tool_create_omits_overwrite_flag_when_falsy(self):
        self._assert_forwards(
            ToolCreate, "tools",
            ("create", ("mytool", '{"toolType": "LinkTool"}', {"overwrite": False})),
            {
                "agent_name": "myagent", "resource_group": "rg",
                "extension_name": "mytool", "value": '{"toolType": "LinkTool"}',
                "overwrite": None,
            },
        )

    def test_skill_show_pins_extension_type_skills(self):
        self._assert_forwards(
            SkillShow, "skills",
            ("show", ("myskill", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "myskill"},
            fake_result={"properties": {"value": {}}},
        )

    def test_subagent_show_pins_extension_type_subagents(self):
        self._assert_forwards(
            SubagentShow, "subagents",
            ("show", ("app-investigator", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "app-investigator"},
            fake_result={"properties": {"value": {}}},
        )

    def test_subagent_list_pins_extension_type_subagents(self):
        self._assert_forwards(
            SubagentList, "subagents",
            ("list", ({},)),
            {"agent_name": "myagent", "resource_group": "rg"},
            fake_result={"value": []},
        )

    def test_subagent_delete_pins_extension_type_subagents(self):
        self._assert_forwards(
            SubagentDelete, "subagents",
            ("delete", ("app-investigator", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "app-investigator"},
        )

    def test_hook_list_pins_extension_type_hooks(self):
        self._assert_forwards(
            HookList, "hooks",
            ("list", ({},)),
            {"agent_name": "myagent", "resource_group": "rg"},
            fake_result={"value": []},
        )

    def test_instructions_delete_pins_extension_type_common_prompts(self):
        self._assert_forwards(
            InstructionsDelete, "commonPrompts",
            ("delete", ("default", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "default"},
        )

    def test_plugin_marketplace_create_pins_extension_type(self):
        self._assert_forwards(
            PluginMarketplaceCreate, "pluginMarketplaces",
            ("create", ("mp", '{"sourceType": "github"}', {"overwrite": False})),
            {
                "agent_name": "myagent", "resource_group": "rg",
                "extension_name": "mp", "value": '{"sourceType": "github"}',
                "overwrite": None,
            },
        )

    def test_plugin_install_show_pins_extension_type(self):
        self._assert_forwards(
            PluginInstallShow, "pluginInstallations",
            ("show", ("myplugin", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "myplugin"},
            fake_result={"properties": {"value": {}}},
        )


class AgentSettingsTests(unittest.TestCase):
    """'sre agent settings' is the one noun exposed directly for the
    'globalSettings' extension type -- a true ARM singleton (always name
    'default'), confirmed via GlobalSettingsExtensionTests.cs. Unlike the
    other noun facades, it does not self-invoke anything -- it calls the
    shared _extension_resource_show/create() helpers directly.
    """

    def test_show_returns_settings_when_present(self):
        command = _bare_command(
            AgentSettingsShow, agent_name="myagent", resource_group="rg",
        )
        calls = []

        def fake_show(cli_ctx, agent_name, resource_group, extension_type, extension_name):
            calls.append((agent_name, resource_group, extension_type, extension_name))
            return {"properties": {"value": {"customInstructions": "be terse"}}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show", fake_show):
            result = command._handler({})

        self.assertEqual(calls, [("myagent", "rg", "globalSettings", "default")])
        self.assertEqual(result, {"properties": {"value": {"customInstructions": "be terse"}}})

    def test_show_falls_back_to_friendly_defaults_when_not_found(self):
        command = _bare_command(
            AgentSettingsShow, agent_name="myagent", resource_group="rg",
        )

        def fake_show(cli_ctx, agent_name, resource_group, extension_type, extension_name):
            raise ResourceNotFoundError("not found")

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show", fake_show):
            result = command._handler({})

        self.assertEqual(result, {"toolPermissions": {}, "toolStatuses": [], "skillStatuses": []})

    def test_update_always_overwrites_the_singleton(self):
        command = _bare_command(
            AgentSettingsUpdate, agent_name="myagent", resource_group="rg",
            value='{"customInstructions": "be terse"}',
        )
        calls = []

        def fake_create(cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False):
            calls.append((agent_name, resource_group, extension_type, extension_name, raw_value, overwrite))
            return {"properties": {"value": {"customInstructions": "be terse"}}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_create):
            result = command._handler({})

        self.assertEqual(
            calls,
            [("myagent", "rg", "globalSettings", "default", '{"customInstructions": "be terse"}', True)],
        )
        self.assertEqual(result, {"properties": {"value": {"customInstructions": "be terse"}}})


class KnowledgeFacadeTests(unittest.TestCase):
    """'sre knowledge' matches the portal's Context > Knowledge sources page
    (Add file / Add web page). Under the hood these are ordinary
    'sre connector' resources whose dataConnectorType is one of the
    Knowledge* values -- these tests assert the facade forwards to
    'sre connector ...' with the right type, and that 'list' filters out
    non-knowledge connectors (Kusto/Mcp/etc.) configured on the same agent.
    """

    def _run(self, command_cls, fake_result=None, **args_kwargs):
        calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            calls.append(args)
            return fake_result

        command = _bare_command(command_cls, **args_kwargs)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})
        return result, calls

    def test_create_file_forwards_data_connector_type_and_file_path(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as handle:
            handle.write("# notes")
            path = handle.name
        try:
            _, calls = self._run(
                KnowledgeCreate,
                agent_name="myagent", resource_group="rg", name="notes",
                type="file", file_path=path, url=None, data_source=None, overwrite=None,
            )
        finally:
            os.unlink(path)
        self.assertEqual(len(calls), 1)
        self.assertEqual(
            calls[0],
            (
                "sre", "connector", "create",
                "--agent-name", "myagent", "--resource-group", "rg",
                "--name", "notes", "--data-connector-type", "KnowledgeFile",
                "--file-path", path,
            ),
        )

    def test_create_file_without_file_path_raises(self):
        with self.assertRaises(CLIError) as raised:
            self._run(
                KnowledgeCreate,
                agent_name="myagent", resource_group="rg", name="notes",
                type="file", file_path=None, url=None, data_source=None, overwrite=None,
            )
        self.assertIn("--file-path", str(raised.exception))

    def test_create_webpage_forwards_extended_properties_only(self):
        # NOTE: must NOT also send --data-source -- live-confirmed to cause
        # a service-side 500 for KnowledgeWebPage when both are present.
        _, calls = self._run(
            KnowledgeCreate,
            agent_name="myagent", resource_group="rg", name="docs",
            type="webpage", file_path=None, url="https://example.com", data_source=None,
            overwrite=True,
        )
        self.assertEqual(
            calls[0],
            (
                "sre", "connector", "create",
                "--agent-name", "myagent", "--resource-group", "rg",
                "--name", "docs", "--data-connector-type", "KnowledgeWebPage",
                "--extended-properties", '{"url": "https://example.com"}',
                "--overwrite",
            ),
        )

    def test_create_webpage_without_url_or_data_source_raises(self):
        with self.assertRaises(CLIError) as raised:
            self._run(
                KnowledgeCreate,
                agent_name="myagent", resource_group="rg", name="docs",
                type="webpage", file_path=None, url=None, data_source=None, overwrite=None,
            )
        self.assertIn("--url", str(raised.exception))

    def test_show_forwards_to_connector_show(self):
        _, calls = self._run(
            KnowledgeShow, agent_name="myagent", resource_group="rg", name="docs",
            fake_result={"properties": {"dataConnectorType": "KnowledgeWebPage"}},
        )
        self.assertEqual(
            calls[0],
            ("sre", "connector", "show", "--agent-name", "myagent", "--resource-group", "rg", "--name", "docs"),
        )

    def test_delete_forwards_to_connector_delete(self):
        _, calls = self._run(
            KnowledgeDelete, agent_name="myagent", resource_group="rg", name="docs",
        )
        self.assertEqual(
            calls[0],
            ("sre", "connector", "delete", "--agent-name", "myagent", "--resource-group", "rg", "--name", "docs", "--yes"),
        )

    def test_list_filters_to_knowledge_connector_types_only(self):
        result, calls = self._run(
            KnowledgeList, agent_name="myagent", resource_group="rg",
            fake_result=[
                {"name": "kusto1", "properties": {"dataConnectorType": "Kusto"}},
                {"name": "file1", "properties": {"dataConnectorType": "KnowledgeFile"}},
                {"name": "web1", "properties": {"dataConnectorType": "KnowledgeWebPage"}},
            ],
        )
        self.assertEqual(
            calls[0],
            ("sre", "connector", "list", "--agent-name", "myagent", "--resource-group", "rg"),
        )
        self.assertEqual([item["name"] for item in result], ["file1", "web1"])

    def test_knowledge_types_cover_all_four_portal_concepts(self):
        self.assertEqual(
            set(KNOWLEDGE_TYPES.values()),
            {"KnowledgeFile", "KnowledgeText", "KnowledgeWebPage", "KnowledgeRepository"},
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
        # Result is trimmed to the networking-relevant fields, not the
        # entire parent agent object the PUT actually returns (usability
        # fix -- every other extension command returns only its own scoped
        # sub-resource).
        self.assertEqual(result["id"], self._AGENT["id"])
        self.assertEqual(result["provisioningState"], "Succeeded")
        self.assertEqual(result["sandboxConfiguration"], {"egress": {"mode": "Unrestricted"}})
        self.assertNotIn("displayName", result)


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
            "sre agent stop", "sre endpoint show", "sre usage list",
            "sre access grant", "sre access revoke", "sre network update",
            "sre connector create", "sre connector show", "sre connector list",
            "sre connector update", "sre connector delete", "sre connector list-secret",
            "sre identity assign", "sre identity remove", "sre identity show",
            "sre agent list-models",
            "sre managed-resource grant", "sre managed-resource revoke", "sre managed-resource list",
            "sre agent settings show", "sre agent settings update",
            "sre repo connect",
            "sre tool create", "sre tool show", "sre tool list", "sre tool delete",
            "sre skill create", "sre skill show", "sre skill list", "sre skill delete",
            "sre subagent create", "sre subagent show", "sre subagent list", "sre subagent delete",
            "sre hook create", "sre hook show", "sre hook list", "sre hook delete",
            "sre instructions create", "sre instructions show",
            "sre instructions list", "sre instructions delete",
            "sre plugin marketplace create", "sre plugin marketplace show",
            "sre plugin marketplace list", "sre plugin marketplace delete",
            "sre plugin install create", "sre plugin install show",
            "sre plugin install list", "sre plugin install delete",
            "sre knowledge create", "sre knowledge show",
            "sre knowledge list", "sre knowledge delete",
        ]
        missing = [name for name in expected if name not in self.command_table]
        self.assertEqual(missing, [], f"Missing registered commands: {missing}")

    def test_retired_duplicate_commands_are_not_registered(self):
        """Manager feedback explicitly called these out as confusing
        duplicates of the real top-level nouns ('sre connector', the new
        'sre identity', and the new 'sre connector list-secret') -- they
        must stay gone, not silently reappear if commands.py's generated-
        recipe auto-discovery is ever refactored. 'sre extension ...' was
        removed outright in a later round (manager feedback: confusing
        generic ARM-proxy surface with no portal equivalent) -- its
        internal logic now lives in plain _extension_resource_*() helper
        functions shared by every noun-specific facade, not a public
        command."""
        retired = [
            "sre agent connector create", "sre agent connector show",
            "sre agent connector list", "sre agent connector update",
            "sre agent connector delete", "sre agent connector list-secret",
            "sre agent identity assign", "sre agent identity remove",
            "sre agent identity show",
            "sre agent list-connectors-with-secret",
            "sre extension create", "sre extension show",
            "sre extension list", "sre extension delete",
        ]
        still_present = [name for name in retired if name in self.command_table]
        self.assertEqual(still_present, [], f"Retired duplicate commands still registered: {still_present}")


class CliArgumentEnforcementTests(unittest.TestCase):
    """Exercises the real Azure CLI argument parser so enum/required-argument
    enforcement is proven, not just declared. No Azure call happens: argument parsing
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


class ArgHelpLengthBudgetTests(unittest.TestCase):
    """Keep per-argument help short, like built-in az commands."""

    MAX_CHARS = 400

    def test_argument_help_within_budget(self):
        from azext_sre import custom
        too_long = []
        for name, cls in vars(custom).items():
            if not (isinstance(cls, type) and hasattr(cls, "_build_arguments_schema")
                    and getattr(cls, "AZ_NAME", None)):
                continue
            try:
                schema = cls._build_arguments_schema()
            except Exception:  # pylint: disable=broad-except
                continue
            for arg_name, arg in schema._fields.items():
                text = (getattr(arg, "_help", None) or {}).get("short-summary") or ""
                if len(text) > self.MAX_CHARS:
                    too_long.append((cls.AZ_NAME, arg_name, len(text)))
        self.assertEqual(too_long, [])


class _NoOpPreOperationsBase:
    """Stand-in base class for isolating _ConnectorConvenienceArgsMixin.
    _DataConnectorTypeArgMixin.pre_operations() calls .to_serialized_data()
    on data_connector_type, which only exists on a real AAZ value -- not on
    the plain Python strings these tests use. Chaining onto this no-op base
    instead of the full ConnectorCreate MRO lets the mixin's own logic be
    tested directly without needing a fully-built AAZ schema/ctx.
    """

    def pre_operations(self):
        pass


class _TestConnectorConvenience(_ConnectorConvenienceArgsMixin, _NoOpPreOperationsBase):
    pass


class GenevaMetricsTenantGateTests(unittest.TestCase):
    """GenevaMetrics is Microsoft-internal only (Paul's 2026-11-02 Teams
    feedback). _DataConnectorTypeArgMixin.pre_operations() now resolves the
    signed-in tenant via 'az account show' and rejects the request
    client-side with a clear message unless the tenant is one of the 13
    Microsoft first-party tenant IDs -- matching the real SRE Agent portal's
    own ConnectorPicker.tsx/FirstPartyHelper.ts gate 1:1, confirmed
    2026-11-02 (see _is_microsoft_first_party_tenant docstring). One CLI,
    no separate 1p/3p build."""

    MICROSOFT_CORP_TENANT_ID = "72f988bf-86f1-41af-91ab-2d7cd011db47"
    MICROSOFT_AME_TENANT_ID = "33e01921-4d64-4f8c-a055-5bdaffd5e33d"

    class _TestDataConnectorType(_DataConnectorTypeArgMixin, _NoOpPreOperationsBase):
        pass

    @staticmethod
    def _value(serialized):
        """Stand-in for a real AAZ value: has_value() just needs it to not
        be None/AAZUndefined, and pre_operations() calls .to_serialized_data()
        on it (mirrors ConnectorConvenienceArgsTests' approach one level up)."""
        return SimpleNamespace(to_serialized_data=lambda: serialized)

    class _TestIcmPlatformGate(_IcmIncidentPlatformGateMixin, _NoOpPreOperationsBase):
        pass

    def test_agent_icm_platform_blocked_outside_microsoft_tenants(self):
        config = SimpleNamespace(type="Icm")
        for tenant, blocked in (
                ("e0a62563-74af-4081-8ae3-fb94b692e394", True),
                (self.MICROSOFT_CORP_TENANT_ID, False),
                (self.MICROSOFT_AME_TENANT_ID, False)):
            with self.subTest(tenant=tenant), patch(
                    "azext_sre.custom._resolve_signed_in_tenant_id", lambda cli_ctx, t=tenant: t):
                command = _bare_command(self._TestIcmPlatformGate, incident_management_configuration=config)
                if blocked:
                    with self.assertRaises(CLIError):
                        command.pre_operations()
                else:
                    command.pre_operations()

    def test_agent_non_icm_platform_is_never_blocked(self):
        command = _bare_command(
            self._TestIcmPlatformGate,
            incident_management_configuration=SimpleNamespace(type="PagerDuty"))
        with patch("azext_sre.custom._resolve_signed_in_tenant_id", lambda cli_ctx: "e0a62563-74af-4081-8ae3-fb94b692e394"):
            command.pre_operations()

    def test_resolve_signed_in_tenant_id_returns_tenant(self):
        with patch(
            "azext_sre.custom._cli_invoke",
            lambda cli_ctx, *args, **kwargs: {"tenantId": self.MICROSOFT_CORP_TENANT_ID},
        ):
            self.assertEqual(
                _resolve_signed_in_tenant_id(SimpleNamespace()), self.MICROSOFT_CORP_TENANT_ID
            )

    def test_resolve_signed_in_tenant_id_raises_when_missing(self):
        with patch("azext_sre.custom._cli_invoke", lambda cli_ctx, *args, **kwargs: {}):
            with self.assertRaises(CLIError):
                _resolve_signed_in_tenant_id(SimpleNamespace())

    def test_is_microsoft_first_party_tenant_covers_all_13_known_ids(self):
        self.assertEqual(len(MICROSOFT_FIRST_PARTY_TENANT_IDS), 13)
        for tenant_id in MICROSOFT_FIRST_PARTY_TENANT_IDS:
            self.assertTrue(_is_microsoft_first_party_tenant(tenant_id))
            # Case-insensitive, matching the portal's own AntUxStringComparison.IgnoreCase.
            self.assertTrue(_is_microsoft_first_party_tenant(tenant_id.upper()))

    def test_is_microsoft_first_party_tenant_rejects_unknown_and_none(self):
        self.assertFalse(_is_microsoft_first_party_tenant("some-other-tenant-id"))
        self.assertFalse(_is_microsoft_first_party_tenant(None))

    def test_connector_create_allows_geneva_metrics_in_corp_tenant(self):
        command = _bare_command(
            self._TestDataConnectorType, data_connector_type=self._value("genevametrics")
        )
        with patch(
            "azext_sre.custom._resolve_signed_in_tenant_id",
            lambda cli_ctx: self.MICROSOFT_CORP_TENANT_ID,
        ):
            command.pre_operations()
        self.assertEqual(command.ctx.args.data_connector_type, "GenevaMetrics")

    def test_connector_create_allows_geneva_metrics_in_ame_tenant(self):
        # Confirms the gate isn't hardcoded to a single tenant -- AME is a
        # distinct first-party tenant in the portal's own allowlist.
        command = _bare_command(
            self._TestDataConnectorType, data_connector_type=self._value("GenevaMetrics")
        )
        with patch(
            "azext_sre.custom._resolve_signed_in_tenant_id",
            lambda cli_ctx: self.MICROSOFT_AME_TENANT_ID,
        ):
            command.pre_operations()
        self.assertEqual(command.ctx.args.data_connector_type, "GenevaMetrics")

    def test_connector_create_rejects_geneva_metrics_outside_microsoft_tenants(self):
        command = _bare_command(
            self._TestDataConnectorType, data_connector_type=self._value("GenevaMetrics")
        )
        with patch(
            "azext_sre.custom._resolve_signed_in_tenant_id",
            lambda cli_ctx: "some-other-tenant-id",
        ):
            with self.assertRaises(CLIError):
                command.pre_operations()

    def test_connector_create_other_types_do_not_check_tenant(self):
        command = _bare_command(
            self._TestDataConnectorType, data_connector_type=self._value("kusto")
        )
        with patch(
            "azext_sre.custom._resolve_signed_in_tenant_id",
            lambda cli_ctx: (_ for _ in ()).throw(AssertionError("should not be called")),
        ):
            command.pre_operations()
        self.assertEqual(command.ctx.args.data_connector_type, "Kusto")

    def _create_with_features(self, connector_type, features):
        command = _bare_command(
            self._TestDataConnectorType, data_connector_type=self._value(connector_type)
        )
        with patch("azext_sre.custom._agent_features", return_value=features):
            command.pre_operations()
        return command

    def test_internal_only_connectors_blocked_when_the_agent_is_not_first_party(self):
        for connector_type in ("GenevaMetrics", "S360", "dgrep"):
            with self.assertRaises(CLIError):
                self._create_with_features(connector_type, {"isFirstParty": False})

    def test_internal_only_connectors_allowed_when_the_agent_is_first_party(self):
        command = self._create_with_features("s360", {"isFirstParty": True})
        self.assertEqual(command.ctx.args.data_connector_type, "S360")

    def test_icm_connector_blocked_only_when_the_agent_says_it_is_not_first_party(self):
        with self.assertRaises(CLIError):
            self._create_with_features("icm", {"isFirstParty": False})
        command = self._create_with_features("icm", {})
        self.assertEqual(command.ctx.args.data_connector_type, "Icm")

    def test_require_first_party_blocks_only_agents_that_say_they_are_not(self):
        from azext_sre.custom import _require_first_party

        with patch("azext_sre.custom._agent_features", return_value={"isFirstParty": False}):
            with self.assertRaises(CLIError):
                _require_first_party(None, "a", "rg", "Something internal")
        with patch("azext_sre.custom._agent_features", return_value={}):
            _require_first_party(None, "a", "rg", "Something internal")


class ConnectorConvenienceArgsTests(unittest.TestCase):
    """--file-path/--mcp-endpoint/--github on 'connector create' build the
    real nested extended-properties/data-source shapes confirmed live this
    session, instead of requiring callers to hand-base64-encode files or
    discover the dual data-source+extended-properties requirement for Mcp
    connectors the hard way."""

    def _run(self, **extra_args):
        args = {
            "data_connector_type": None, "file_path": None,
            "mcp_endpoint": None, "github": None,
            "data_source": None, "extended_properties": None,
        }
        args.update(extra_args)
        command = _bare_command(_TestConnectorConvenience, **args)
        command.pre_operations()
        return command.ctx.args

    def test_github_flag_fills_canonical_endpoint(self):
        args = self._run(data_connector_type="Mcp", github=True)
        self.assertEqual(args.data_source, GITHUB_COPILOT_MCP_ENDPOINT)
        self.assertEqual(
            args.extended_properties,
            {"transport": "Http", "endpoint": GITHUB_COPILOT_MCP_ENDPOINT},
        )

    def test_mcp_endpoint_builds_both_data_source_and_extended_properties(self):
        args = self._run(data_connector_type="Mcp", mcp_endpoint="https://example.com/mcp")
        self.assertEqual(args.data_source, "https://example.com/mcp")
        self.assertEqual(
            args.extended_properties,
            {"transport": "Http", "endpoint": "https://example.com/mcp"},
        )

    def test_mcp_endpoint_merges_with_caller_supplied_extended_properties(self):
        # Regression test: --mcp-endpoint must merge into, not clobber, any
        # --extended-properties the caller already supplied (e.g. {"headers":
        # {...}} for an MCP server's auth headers, matching the portal's
        # "Configure connector" custom headers field). Found live: a prior
        # version of this mixin unconditionally overwrote extended_properties,
        # silently dropping caller-supplied headers.
        args = self._run(
            data_connector_type="Mcp",
            mcp_endpoint="https://example.com/mcp",
            extended_properties={"headers": {"X-Api-Key": "secret"}},
        )
        self.assertEqual(args.data_source, "https://example.com/mcp")
        self.assertEqual(
            args.extended_properties,
            {
                "headers": {"X-Api-Key": "secret"},
                "transport": "Http",
                "endpoint": "https://example.com/mcp",
            },
        )

    def test_github_flag_rejects_non_mcp_type(self):
        with self.assertRaises(CLIError) as raised:
            self._run(data_connector_type="Kusto", github=True)
        self.assertIn("Mcp", str(raised.exception))

    def test_bearer_token_builds_auth_type_and_token(self):
        args = self._run(
            data_connector_type="Mcp",
            mcp_endpoint="https://example.com/mcp",
            bearer_token="secret-pat",
        )
        self.assertEqual(
            args.extended_properties,
            {
                "transport": "Http",
                "endpoint": "https://example.com/mcp",
                "authType": "BearerToken",
                "bearerToken": "secret-pat",
            },
        )

    def test_bearer_token_rejects_non_mcp_type(self):
        with self.assertRaises(CLIError) as raised:
            self._run(data_connector_type="Kusto", bearer_token="secret-pat")
        self.assertIn("Mcp", str(raised.exception))

    def test_managed_identity_auth_defaults_arm_scope(self):
        args = self._run(data_connector_type="Mcp", managed_identity_auth=True)
        self.assertEqual(
            args.extended_properties,
            {"authType": "AzureARM", "armScope": "https://management.azure.com/.default"},
        )

    def test_mi_token_scope_implies_managed_identity_auth(self):
        # --mi-token-scope alone (without --managed-identity-auth true) still
        # triggers the AzureARM auth type, matching the help text's "implied
        # by --mi-token-scope if that is passed alone".
        args = self._run(
            data_connector_type="Mcp",
            mi_token_scope="api://myserver/.default",
        )
        self.assertEqual(
            args.extended_properties,
            {"authType": "AzureARM", "armScope": "api://myserver/.default"},
        )

    def test_oauth_dcr_builds_spec_oauth_with_scopes_and_client_name(self):
        args = self._run(
            data_connector_type="Mcp",
            oauth_dcr=True,
            oauth_scopes="scope1,scope2",
            oauth_client_name="my-client",
        )
        self.assertEqual(
            args.extended_properties,
            {
                "authType": "SpecOAuth",
                "scopes": "scope1,scope2",
                "dcrClientName": "my-client",
            },
        )

    def test_oauth_scopes_without_oauth_dcr_is_rejected(self):
        with self.assertRaises(CLIError) as raised:
            self._run(data_connector_type="Mcp", oauth_scopes="scope1")
        self.assertIn("--oauth-dcr", str(raised.exception))

    def test_auth_flags_are_mutually_exclusive(self):
        with self.assertRaises(CLIError) as raised:
            self._run(
                data_connector_type="Mcp",
                bearer_token="secret-pat",
                oauth_dcr=True,
            )
        self.assertIn("Only one of", str(raised.exception))

    def test_auth_flags_merge_with_github_endpoint(self):
        # Combining --github with an explicit auth flag is a real use case
        # (e.g. a custom MCP server reached through the GitHub Copilot MCP
        # endpoint, but guarded by the caller's own bearer token) -- both
        # must merge into the same extended-properties dict, not clobber.
        args = self._run(data_connector_type="Mcp", github=True, bearer_token="secret-pat")
        self.assertEqual(
            args.extended_properties,
            {
                "transport": "Http",
                "endpoint": GITHUB_COPILOT_MCP_ENDPOINT,
                "authType": "BearerToken",
                "bearerToken": "secret-pat",
            },
        )

    def test_file_path_base64_encodes_knowledge_file(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as handle:
            handle.write(b"hello world")
            path = handle.name
        try:
            args = self._run(data_connector_type="KnowledgeFile", file_path=path)
            self.assertEqual(
                args.extended_properties,
                {"fileContent": base64.b64encode(b"hello world").decode("ascii"),
                 "fileName": os.path.basename(path)},
            )
        finally:
            os.remove(path)

    def test_file_path_reads_knowledge_text_as_utf8(self):
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as handle:
            handle.write("some knowledge text")
            path = handle.name
        try:
            args = self._run(data_connector_type="KnowledgeText", file_path=path)
            self.assertEqual(args.extended_properties, {"content": "some knowledge text"})
        finally:
            os.remove(path)

    def test_file_path_rejects_unsupported_connector_type(self):
        import tempfile

        with tempfile.NamedTemporaryFile(delete=False) as handle:
            path = handle.name
        try:
            with self.assertRaises(CLIError) as raised:
                self._run(data_connector_type="Kusto", file_path=path)
            self.assertIn("--file-path", str(raised.exception))
        finally:
            os.remove(path)

    def test_file_path_rejects_missing_file(self):
        with self.assertRaises(CLIError) as raised:
            self._run(data_connector_type="KnowledgeFile", file_path="C:\\does\\not\\exist.bin")
        self.assertIn("does not exist", str(raised.exception))

    def test_connector_create_schema_exposes_new_args(self):
        schema = ConnectorCreate._build_arguments_schema()
        self.assertIsNotNone(schema.file_path)
        self.assertIsNotNone(schema.mcp_endpoint)
        self.assertIsNotNone(schema.github)
        self.assertIsNotNone(schema.bearer_token)
        self.assertIsNotNone(schema.managed_identity_auth)
        self.assertIsNotNone(schema.mi_token_scope)
        self.assertIsNotNone(schema.oauth_dcr)
        self.assertIsNotNone(schema.oauth_scopes)
        self.assertIsNotNone(schema.oauth_client_name)


class _StubOutputBase:
    """Stand-in base providing a canned _output() result, so
    _ConnectorConvenienceArgsMixin._output()'s empty-extendedProperties
    warning can be tested without a real AAZ response object."""

    def __init__(self, result):
        self._result = result

    def _output(self, *args, **kwargs):
        return self._result


class _TestConnectorConvenienceOutput(_ConnectorConvenienceArgsMixin, _StubOutputBase):
    pass


class ConnectorCreateEmptyExtendedPropertiesWarningTests(unittest.TestCase):
    """Confirmed live (via --debug on a direct, unmodified 'connector
    create --data-connector-type KnowledgeFile --file-path ...'): the PUT
    request body correctly contains extendedProperties.fileContent/
    fileName, but the service's 200 response (and a later 'connector
    show') echoes back extendedProperties: {"fileContent": null,
    "fileName": null} -- a service-side gap, not a CLI bug. _output()
    should warn about this (without raising), so users don't assume their
    file silently never got sent."""

    def test_warns_when_file_path_used_and_response_extended_properties_empty(self):
        command = _TestConnectorConvenienceOutput(
            {"properties": {"extendedProperties": {"fileContent": None, "fileName": None}}}
        )
        command._file_path_used = True
        with patch("azext_sre.custom.logger") as mock_logger:
            result = command._output()
            mock_logger.warning.assert_called_once()
            self.assertIn("known service-side gap", mock_logger.warning.call_args[0][0])
        self.assertEqual(result["properties"]["extendedProperties"], {"fileContent": None, "fileName": None})

    def test_no_warning_when_response_extended_properties_populated(self):
        command = _TestConnectorConvenienceOutput(
            {"properties": {"extendedProperties": {"fileContent": "abc", "fileName": "f.txt"}}}
        )
        command._file_path_used = True
        with patch("azext_sre.custom.logger") as mock_logger:
            command._output()
            mock_logger.warning.assert_not_called()

    def test_no_warning_when_file_path_was_not_used(self):
        command = _TestConnectorConvenienceOutput(
            {"properties": {"extendedProperties": {}}}
        )
        with patch("azext_sre.custom.logger") as mock_logger:
            command._output()
            mock_logger.warning.assert_not_called()


class ConnectorListSecretAliasTests(unittest.TestCase):
    """The generated ListSecret recipe only exposed --connector-name (no
    -n/--name alias), unlike every other 'sre connector ...' command --
    _ConnectorNameAliasMixin patches that in for consistency."""

    def test_connector_name_has_short_and_long_name_aliases(self):
        schema = ConnectorListSecret._build_arguments_schema()
        cmd_arg = schema.connector_name.to_cmd_arg("connector_name")
        self.assertEqual(cmd_arg.options_list, ["-n", "--name", "--connector-name"])


class IdentityAndSupportedAgentModelRegistrationTests(unittest.TestCase):
    """'sre identity'/'sre agent list-models' are thin re-registrations
    of generated recipes (promoted out of the retired 'sre agent identity'
    subgroup / 'sre supported-agent-model list' folded into 'sre agent') --
    just confirms their schemas build without error under the new names."""

    def test_identity_assign_schema_builds(self):
        schema = IdentityAssign._build_arguments_schema()
        self.assertIsNotNone(schema.agent_name)

    def test_identity_remove_schema_builds(self):
        schema = IdentityRemove._build_arguments_schema()
        self.assertIsNotNone(schema.agent_name)

    def test_identity_show_schema_builds(self):
        schema = IdentityShow._build_arguments_schema()
        self.assertIsNotNone(schema.agent_name)

    def test_supported_agent_model_list_schema_builds(self):
        schema = SupportedAgentModelList._build_arguments_schema()
        self.assertIsNotNone(schema.location)


class SkillCreateFilePathTests(unittest.TestCase):
    """'sre skill create --file-path' parses a SKILL.md-style file (the
    portal's own Skill builder file template: '---'-delimited frontmatter
    with 'description:', followed by a markdown body) into the real
    {"description", "tools", "skillContent"} wire shape, instead of
    requiring a hand-built --value JSON string."""

    def _write(self, text):
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        )
        self.addCleanup(lambda: os.remove(handle.name))
        handle.write(text)
        handle.close()
        return handle.name

    def test_parses_frontmatter_description_and_body(self):
        path = self._write(
            "---\nname: my-skill\ndescription: Summarizes incidents\n---\n"
            "# My skill\n\nDo the thing.\n"
        )
        description, content = _parse_skill_md(path)
        self.assertEqual(description, "Summarizes incidents")
        self.assertEqual(content, "# My skill\n\nDo the thing.")

    def test_plain_file_with_no_frontmatter_is_treated_as_body_only(self):
        path = self._write("# Just a body\n\nNo frontmatter here.\n")
        description, content = _parse_skill_md(path)
        self.assertIsNone(description)
        self.assertEqual(content, "# Just a body\n\nNo frontmatter here.\n")

    def test_missing_file_raises(self):
        with self.assertRaises(CLIError):
            _parse_skill_md("does-not-exist-123.md")

    def test_prepare_value_builds_expected_json_with_tools(self):
        path = self._write("---\ndescription: Desc\n---\nBody text\n")
        command = _bare_command(
            SkillCreate, file_path=path, value=None, description=None,
            tools=["kusto-query", "log-search"],
        )
        command._prepare_value()
        self.assertEqual(
            json.loads(command.ctx.args.value),
            {"description": "Desc", "tools": ["kusto-query", "log-search"], "skillContent": "Body text"},
        )

    def test_prepare_value_explicit_description_overrides_frontmatter(self):
        path = self._write("---\ndescription: From frontmatter\n---\nBody\n")
        command = _bare_command(
            SkillCreate, file_path=path, value=None, description="From flag", tools=None,
        )
        command._prepare_value()
        self.assertEqual(json.loads(command.ctx.args.value)["description"], "From flag")

    def test_prepare_value_no_description_anywhere_raises(self):
        path = self._write("Body with no frontmatter at all\n")
        command = _bare_command(SkillCreate, file_path=path, value=None, description=None, tools=None)
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_both_file_path_and_value_raises(self):
        path = self._write("---\ndescription: D\n---\nBody\n")
        command = _bare_command(
            SkillCreate, file_path=path, value='{"description": "x"}', description=None, tools=None,
        )
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_neither_file_path_nor_value_raises(self):
        command = _bare_command(SkillCreate, file_path=None, value=None, description=None, tools=None)
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_noop_when_only_value_given(self):
        command = _bare_command(
            SkillCreate, file_path=None, value='{"description": "x"}', description=None, tools=None,
        )
        command._prepare_value()
        self.assertEqual(command.ctx.args.value, '{"description": "x"}')


class SubagentCreatePreToolUseScriptFileTests(unittest.TestCase):
    """'sre subagent create --pre-tool-use-script-file' merges a hook
    script into --value.hooks.PreToolUse (the portal's "Manage Hooks"
    button inside the subagent-creation dialog -- live-confirmed to be
    just a field on the same subagent PUT body, no separate resource)."""

    def _write(self, text):
        handle = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False, encoding="utf-8"
        )
        self.addCleanup(lambda: os.remove(handle.name))
        handle.write(text)
        handle.close()
        return handle.name

    def test_merges_script_into_hooks_pretooluse(self):
        path = self._write("print('evidence only')\n")
        value = json.dumps({
            "instructions": "x", "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": True,
        })
        command = _bare_command(SubagentCreate, value=value, pre_tool_use_script_file=path)
        command._prepare_value()
        parsed = json.loads(command.ctx.args.value)
        self.assertEqual(
            parsed["hooks"]["PreToolUse"],
            [{
                "type": "command", "matcher": "(?s:.*)", "timeout": 30,
                "failMode": "block", "script": "print('evidence only')\n",
            }],
        )
        self.assertEqual(parsed["instructions"], "x")

    def test_missing_script_file_raises(self):
        value = json.dumps({"instructions": "x"})
        command = _bare_command(
            SubagentCreate, value=value, pre_tool_use_script_file="does-not-exist-999.py",
        )
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_non_object_value_raises(self):
        path = self._write("print('x')\n")
        command = _bare_command(SubagentCreate, value="[1, 2, 3]", pre_tool_use_script_file=path)
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_noop_when_no_script_file_given(self):
        value = json.dumps({"instructions": "x"})
        command = _bare_command(SubagentCreate, value=value, pre_tool_use_script_file=None)
        command._prepare_value()
        self.assertEqual(command.ctx.args.value, value)


class _NoOpPostOperationsBase:
    """Stand-in base for isolating _GrantAccessToMeMixin the same way
    _NoOpPreOperationsBase isolates the connector mixin above."""

    def post_operations(self):
        pass


class _TestGrantAccessToMe(_GrantAccessToMeMixin, _NoOpPostOperationsBase):
    pass


class GrantAccessToMeTests(unittest.TestCase):
    """--grant-access-to-me on 'agent create' collapses the
    create -> `az ad signed-in-user show` -> grant-access dance the user
    found confusing into a single flag."""

    def _run(self, calls, signed_in_user=None, **extra_args):
        args = {
            "agent_name": "myagent", "resource_group": "rg",
            "grant_access_to_me": None,
        }
        args.update(extra_args)
        command = _bare_command(_TestGrantAccessToMe, **args)

        def fake_cli_invoke(cli_ctx, *cmd_args, allow_missing=False):
            calls.append(cmd_args)
            if cmd_args[:3] == ("ad", "signed-in-user", "show"):
                return signed_in_user if signed_in_user is not None else {"id": "user-object-id"}
            return {"properties": {"value": "stub"}}

        with patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            command.post_operations()
        return calls

    def test_no_flag_does_nothing(self):
        calls = self._run([])
        self.assertEqual(calls, [])

    def test_resolves_signed_in_user_and_calls_grant_access(self):
        calls = self._run([], grant_access_to_me="admin")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][:3], ("ad", "signed-in-user", "show"))
        grant_call = calls[1]
        self.assertEqual(grant_call[:3], ("sre", "access", "grant"))
        self.assertIn("myagent", grant_call)
        self.assertIn("rg", grant_call)
        self.assertIn("admin", grant_call)
        self.assertIn("user-object-id", grant_call)

    def test_raises_if_signed_in_user_cannot_be_resolved(self):
        with self.assertRaises(CLIError) as raised:
            self._run([], grant_access_to_me="reader", signed_in_user={})
        self.assertIn("signed-in user", str(raised.exception))

    def test_agent_create_schema_exposes_grant_access_to_me(self):
        schema = Create._build_arguments_schema()
        self.assertIsNotNone(schema.grant_access_to_me)


class _TestGrantAccessToMePreOps(_GrantAccessToMeMixin, _NoOpPreOperationsBase):
    pass


class GrantAccessToMeNoWaitGuardTests(unittest.TestCase):
    """Real bug found live: --grant-access-to-me silently did nothing when
    combined with --no-wait, because AAZCommand's no-wait code path
    (build_lro_poller) advances the pre_operations -> yield PUT ->
    post_operations generator exactly one step and never reaches
    post_operations() -- where the grant actually runs. pre_operations()
    must reject the combination up front instead of silently dropping it.
    """

    def _run(self, grant_access_to_me, no_wait):
        command = _bare_command(
            _TestGrantAccessToMePreOps,
            agent_name="myagent", resource_group="rg",
            grant_access_to_me=grant_access_to_me, no_wait=no_wait,
        )
        command.pre_operations()

    def test_rejects_grant_access_to_me_with_no_wait(self):
        with self.assertRaises(CLIError) as raised:
            self._run(grant_access_to_me="admin", no_wait=True)
        self.assertIn("--no-wait", str(raised.exception))

    def test_allows_grant_access_to_me_without_no_wait(self):
        self._run(grant_access_to_me="admin", no_wait=False)  # should not raise

    def test_allows_no_wait_without_grant_access_to_me(self):
        self._run(grant_access_to_me=None, no_wait=True)  # should not raise


class _TestDefaultSystemIdentity(_DefaultSystemIdentityMixin, _NoOpPreOperationsBase):
    pass


class DefaultSystemIdentityTests(unittest.TestCase):
    """Real bug found live: 'az sre agent create' with no identity flag at
    all reached ARM and failed with (ManagedIdentityRequired) "At least one
    managed identity (SystemAssigned or UserAssigned) must be assigned to
    the agent." _DefaultSystemIdentityMixin used to default to just
    --mi-system-assigned client-side; a real portal screenshot plus the
    portal's own ARM template (SreAgentTemplateResource.ts:
    'createUserIdentity ?? true', identity.type "SystemAssigned,
    UserAssigned") proved the portal actually auto-creates a NEW
    user-assigned identity too and enables both types. This mixin now
    reproduces that -- auto-creating the identity resource via
    _create_user_assigned_identity() (mocked out below, real ARM call
    tested live) -- while still honoring an explicit --mi-system-assigned/
    --mi-user-assigned if the caller gave one."""

    def _run(self, **extra_args):
        args = {
            "mi_system_assigned": AAZUndefined,
            "mi_user_assigned": AAZUndefined,
            "agent_name": "myagent",
            "resource_group": "myrg",
            "location": "eastus2",
        }
        args.update(extra_args)
        command = _bare_command(_TestDefaultSystemIdentity, **args)
        command.ctx.subscription_id = "sub123"
        with patch(
            "azext_sre.custom._create_user_assigned_identity",
            return_value="/subscriptions/sub123/resourceGroups/myrg/providers/"
            "Microsoft.ManagedIdentity/userAssignedIdentities/myagent-identity-abc123",
        ) as mock_create:
            command.pre_operations()
        command._mock_create_identity = mock_create
        return command.ctx.args

    def test_defaults_to_system_assigned_when_neither_given(self):
        args = self._run()
        self.assertEqual(args.mi_system_assigned, "True")

    def test_defaults_also_creates_and_attaches_a_new_user_assigned_identity(self):
        args = self._run()
        self.assertEqual(
            args.mi_user_assigned,
            [
                "/subscriptions/sub123/resourceGroups/myrg/providers/"
                "Microsoft.ManagedIdentity/userAssignedIdentities/myagent-identity-abc123"
            ],
        )

    def test_leaves_explicit_system_assigned_alone(self):
        args = self._run(mi_system_assigned="some-explicit-value")
        self.assertEqual(args.mi_system_assigned, "some-explicit-value")

    def test_leaves_explicit_user_assigned_alone_and_skips_default(self):
        args = self._run(mi_user_assigned=["/subscriptions/.../userAssignedIdentities/x"])
        self.assertEqual(args.mi_system_assigned, AAZUndefined)

    def test_empty_user_assigned_list_still_triggers_default(self):
        args = self._run(mi_user_assigned=[])
        self.assertEqual(args.mi_system_assigned, "True")

    def test_agent_create_includes_the_default_identity_mixin(self):
        self.assertTrue(issubclass(Create, _DefaultSystemIdentityMixin))


class ConnectionShowDefaultAudienceTests(unittest.TestCase):
    """Real bug found live: 'az sre endpoint show' (no --data-plane-audience
    override) rendered 'dataPlaneAudience' in its JSON output as
    '{"isDefault": true}' instead of the actual URL string. Root cause: an
    unset AAZStrArg with a declared `default=` resolves through
    `_arg_value()` to a `knack.validators.DefaultStr` (a str subclass used
    internally to flag "still at its default value"); az's own command
    output formatter introspects that subclass via vars() instead of
    treating it as a plain string, because it isn't an *exact* `str`.
    `GetConnection._handler` now coerces it with `str(...)` before putting
    it in the output dict (the on-disk connections file was never affected,
    since stdlib json.dump() already handles str subclasses correctly)."""

    def _run(self, **extra_args):
        args = {
            "name": "myagent", "resource_group": "rg",
            "data_plane_audience": "https://azuresre.dev",
        }
        args.update(extra_args)
        command = _bare_command(GetConnection, **args)

        def fake_cli_invoke(cli_ctx, *cmd_args, allow_missing=False):
            return {"properties": {"agentEndpoint": "https://myagent--abc.def.eastus2.azuresre.ai"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             tempfile.TemporaryDirectory() as tmp_dir, \
             patch("azext_sre.custom._CONNECTIONS_FILE", os.path.join(tmp_dir, "sreAgentConnections.json")):
            result = command._handler({})
        return result

    def test_default_audience_is_a_plain_str_not_a_default_str_subclass(self):
        from knack.validators import DefaultStr

        default_audience = DefaultStr("https://azuresre.dev")
        self.assertIsInstance(default_audience, str)
        result = self._run(data_plane_audience=default_audience)
        self.assertEqual(result["dataPlaneAudience"], "https://azuresre.dev")
        # pylint: disable=unidiomatic-typecheck
        self.assertEqual(type(result["dataPlaneAudience"]), str)
        self.assertNotIsInstance(result["dataPlaneAudience"], DefaultStr)

    def test_explicit_audience_passes_through_unchanged(self):
        result = self._run(data_plane_audience="https://custom.audience.example")
        self.assertEqual(result["dataPlaneAudience"], "https://custom.audience.example")


class _NoOpPreOpBase2:
    def pre_operations(self):
        pass


class _TestConnectorExistenceGuard(_ConnectorExistenceGuardMixin, _NoOpPreOpBase2):
    pass


class ConnectorExistenceGuardTests(unittest.TestCase):
    """'connector create' must not silently overwrite an existing connector
    of the same name (the generated PUT has no If-Match support) -- a
    GET-before-PUT guard, pointing the
    caller at 'connector update' instead."""

    def _run(self, show_result):
        command = _bare_command(
            _TestConnectorExistenceGuard,
            agent_name="myagent", resource_group="rg", connector_name="myconn",
        )
        with patch(
            "azext_sre.custom._resolve_agent_resource_id",
            lambda cli_ctx, agent_name, resource_group: (
                "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
            ),
        ), patch(
            "azext_sre.custom._arm_request",
            lambda cli_ctx, method, resource_id, api_version, body=None, missing_ok=False: show_result,
        ):
            command.pre_operations()

    def test_blocks_when_connector_already_exists(self):
        with self.assertRaises(ResourceExistsError) as raised:
            self._run(show_result={"name": "myconn"})
        self.assertIn("connector update", str(raised.exception))

    def test_proceeds_when_connector_does_not_exist(self):
        self._run(show_result=None)  # must not raise


class ConnectorListOutputTests(unittest.TestCase):
    """ConnectorList._output must unpack the (value, next_link) tuple the
    paginated generated List returns -- the earlier version compared the
    tuple itself against dict (isinstance(result, dict)), which was always
    False, so consent-status annotation silently never ran on 'connector
    list' even though it worked on 'connector show'."""

    def _run(self, super_output):
        command = object.__new__(ConnectorList)
        base_cls = ConnectorList.__mro__[1]  # the generated _GeneratedConnectorList
        with patch.object(base_cls, "_output", lambda self, *a, **k: super_output):
            return command._output()

    def test_annotates_every_item_and_unpacks_tuple(self):
        connector = {"properties": {"extendedProperties": {"authType": "EntraOAuth", "entraOAuth": None}}}
        value, next_link = self._run(([connector], None))
        self.assertEqual(value[0]["consentStatus"], "PendingConsent")
        self.assertIsNone(next_link)

    def test_warns_on_empty_final_page(self):
        with patch("azext_sre.custom.logger") as mock_logger:
            value, next_link = self._run(([], None))
            mock_logger.warning.assert_called_once()
        self.assertEqual(value, [])
        self.assertIsNone(next_link)

    def test_does_not_warn_when_more_pages_remain(self):
        with patch("azext_sre.custom.logger") as mock_logger:
            self._run(([], "https://next-page"))
            mock_logger.warning.assert_not_called()


class SupportedAgentModelListTests(unittest.TestCase):
    """'sre agent list-models' does its own raw ARM GET (not the generated
    AAZ-schema-deserializing call) because the real API's wire field names
    ('providerName'/'modelName') don't match the generated schema's declared
    attribute names ('provider'/'model') -- confirmed live via --debug,
    which showed the generated path silently producing null 'provider'/
    'name' values on every item. Flattens 'properties.providerName'/
    'properties.modelName' to top-level 'provider'/'name' so a row can be
    passed straight into --default-model "{provider:...,name:...}"
    (usability finding, live-graded)."""

    def _run(self, pages):
        command = object.__new__(SupportedAgentModelList)
        command.ctx = SimpleNamespace(
            args=SimpleNamespace(location="eastus2"), subscription_id="sub123",
        )
        command.cli_ctx = SimpleNamespace()
        calls = []

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            calls.append(resource_id)
            return pages.pop(0)

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})
        return result, calls

    def test_flattens_provider_name_and_model_name_to_top_level(self):
        raw_item = {
            "id": "...",
            "name": "Anthropic-Automatic",
            "properties": {
                "providerName": "Anthropic",
                "modelName": "Automatic",
                "default": True,
                "providerDisplayName": "Anthropic",
                "modelDisplayName": "Automatic",
            },
        }
        result, calls = self._run([{"value": [raw_item]}])
        self.assertEqual(result[0]["provider"], "Anthropic")
        self.assertEqual(result[0]["name"], "Automatic")
        self.assertTrue(result[0]["default"])
        self.assertIn("/locations/eastus2/supportedAgentModels", calls[0])

    def test_passes_through_non_dict_items(self):
        result, _ = self._run([{"value": ["not-a-dict"]}])
        self.assertEqual(result, ["not-a-dict"])

    def test_follows_next_link_across_pages(self):
        page1 = {"value": [{"properties": {"providerName": "P1", "modelName": "M1"}}], "nextLink": "https://next"}
        page2 = {"value": [{"properties": {"providerName": "P2", "modelName": "M2"}}]}
        result, calls = self._run([page1, page2])
        self.assertEqual([r["provider"] for r in result], ["P1", "P2"])
        self.assertEqual(calls[1], "https://next")

    def test_empty_value_returns_empty_list(self):
        result, _ = self._run([{}])
        self.assertEqual(result, [])


class TableTransformerTests(unittest.TestCase):
    """Real UX gap found live via a '-o table' screenshot: 'access list' and
    'managed-resource list' both return raw 'az role assignment list'
    output (a dozen-plus flat top-level fields), which az's default
    '-o table' auto-generator renders as one column per field -- confirmed
    to wrap into an unreadable wall of text at a normal terminal width.
    Both commands now register a curated table_transformer
    (_transformers.py) via commands.py's TABLE_TRANSFORMERS map."""

    _ROLE_ASSIGNMENT = {
        "createdBy": "admin-id", "createdOn": "2026-11-03T18:10:42.126877+00:00",
        "id": "/subscriptions/sub/.../roleAssignments/abc",
        "name": "abc", "principalId": "user-id",
        "principalName": "someone@example.com", "principalType": "User",
        "resourceGroup": "myrg",
        "roleDefinitionId": "/subscriptions/sub/.../roleDefinitions/def",
        "roleDefinitionName": "SRE Agent Administrator",
        "scope": "/subscriptions/sub/resourceGroups/myrg/providers/Microsoft.App/agents/myagent",
        "type": "Microsoft.Authorization/roleAssignments",
        "updatedBy": "admin-id", "updatedOn": "2026-11-03T18:10:42.126877+00:00",
    }

    def test_access_list_format_curates_expected_columns(self):
        from azext_sre._transformers import access_list_table_format

        rows = access_list_table_format([self._ROLE_ASSIGNMENT])
        self.assertEqual(
            list(rows[0].items()),
            [
                ("Principal", "someone@example.com"),
                ("Type", "User"),
                ("Role", "SRE Agent Administrator"),
                ("GrantedOn", "2026-11-03T18:10:42Z"),
            ],
        )

    def test_managed_resource_list_format_curates_expected_columns(self):
        from azext_sre._transformers import managed_resource_list_table_format

        rows = managed_resource_list_table_format([self._ROLE_ASSIGNMENT])
        self.assertEqual(
            list(rows[0].items()),
            [
                ("Scope", "/subscriptions/sub/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"),
                ("Role", "SRE Agent Administrator"),
                ("PrincipalType", "User"),
                ("GrantedOn", "2026-11-03T18:10:42Z"),
            ],
        )

    def test_handles_missing_fields_and_multiple_rows_without_raising(self):
        from azext_sre._transformers import access_list_table_format

        rows = access_list_table_format([{}, self._ROLE_ASSIGNMENT])
        self.assertEqual(len(rows), 2)
        self.assertIsNone(rows[0]["GrantedOn"])

    def test_table_transformers_registered_for_both_commands(self):
        from azext_sre._transformers import TABLE_TRANSFORMERS

        self.assertIn("sre access list", TABLE_TRANSFORMERS)
        self.assertIn("sre managed-resource list", TABLE_TRANSFORMERS)

    def test_command_table_wires_transformer_for_access_list(self):
        loader = SreCommandsLoader(cli_ctx=DummyCli())
        command_table = loader.load_command_table(["sre", "access", "list"])
        self.assertIsNotNone(command_table["sre access list"].table_transformer)
        self.assertIsNone(command_table["sre access grant"].table_transformer)


class ConnectorTableTransformerTests(unittest.TestCase):
    """Real UX gap: a connector's properties.dataConnectorType is an
    internal wire value (e.g. 'KustoClient') that never appears anywhere
    in the portal UI, which only shows the display name (e.g. 'Azure Data
    Explorer') -- confirmed a source of user confusion. 'sre connector
    list'/'show' -o table now resolve it to the portal name via
    CONNECTOR_TYPE_PORTAL_NAMES; -o json/yaml are untouched (still return
    the raw wire value), since scripts rely on that exact value."""

    _KUSTOCLIENT_CONNECTOR = {
        "id": "/subscriptions/sub/.../connectors/azure-data-explorer",
        "name": "azure-data-explorer",
        "resourceGroup": "myrg",
        "type": "Microsoft.App/agents/connectors",
        "properties": {"dataConnectorType": "KustoClient", "identity": "", "provisioningState": "Succeeded"},
    }

    _UNMAPPED_TYPE_CONNECTOR = {
        "name": "runbook",
        "properties": {"dataConnectorType": "KnowledgeFile", "provisioningState": "Succeeded"},
    }

    def test_connector_list_format_resolves_portal_name(self):
        from azext_sre._transformers import connector_list_table_format

        rows = connector_list_table_format([self._KUSTOCLIENT_CONNECTOR])
        self.assertEqual(
            list(rows[0].items()),
            [
                ("Name", "azure-data-explorer"),
                ("Type", "Azure Data Explorer"),
                ("ProvisioningState", "Succeeded"),
                ("ConsentStatus", None),
            ],
        )

    def test_connector_show_format_resolves_portal_name(self):
        from azext_sre._transformers import connector_show_table_format

        row = connector_show_table_format(self._KUSTOCLIENT_CONNECTOR)
        self.assertEqual(row["Type"], "Azure Data Explorer")
        self.assertEqual(row["Name"], "azure-data-explorer")

    def test_connector_format_falls_back_to_wire_value_when_no_portal_name(self):
        from azext_sre._transformers import connector_list_table_format

        rows = connector_list_table_format([self._UNMAPPED_TYPE_CONNECTOR])
        # KnowledgeFile has no confirmed portal display name -- must show
        # the raw wire value as-is, not guess or blank it out.
        self.assertEqual(rows[0]["Type"], "KnowledgeFile")

    def test_connector_format_resolves_corrected_title_based_names(self):
        # Icm/Dgrep/Mcp were previously mapped to subtitle-based names
        # ("Microsoft IcM"/"Microsoft DGrep"/"Custom MCP"); the full portal
        # catalog export confirmed the real card Title is different --
        # these must resolve to the corrected Title-based names.
        from azext_sre._transformers import connector_list_table_format

        cases = {
            "Icm": "IcM connector",
            "Dgrep": "DGrep",
            "Mcp": "MCP server",
        }
        for wire_value, expected_name in cases.items():
            connector = {"name": "x", "properties": {"dataConnectorType": wire_value}}
            rows = connector_list_table_format([connector])
            self.assertEqual(rows[0]["Type"], expected_name, wire_value)

    def test_connector_format_resolves_new_high_confidence_portal_names(self):
        # KustoUser/KustoDataIndexer/AzureDevOpsBuiltinMcp: high-confidence
        # correlations from the full portal catalog export (not
        # create-and-inspect confirmed), added 2026-11-04.
        from azext_sre._transformers import connector_list_table_format

        cases = {
            "KustoUser": "Database query connector (user)",
            "KustoDataIndexer": "Database indexing connector",
            "AzureDevOpsBuiltinMcp": "Azure DevOps AI Search",
        }
        for wire_value, expected_name in cases.items():
            connector = {"name": "x", "properties": {"dataConnectorType": wire_value}}
            rows = connector_list_table_format([connector])
            self.assertEqual(rows[0]["Type"], expected_name, wire_value)

    def test_connector_format_includes_consent_status_when_present(self):
        from azext_sre._transformers import connector_list_table_format

        connector = dict(self._KUSTOCLIENT_CONNECTOR)
        connector["consentStatus"] = "PendingConsent"
        rows = connector_list_table_format([connector])
        self.assertEqual(rows[0]["ConsentStatus"], "PendingConsent")

    def test_table_transformers_registered_for_connector_list_and_show(self):
        from azext_sre._transformers import TABLE_TRANSFORMERS

        self.assertIn("sre connector list", TABLE_TRANSFORMERS)
        self.assertIn("sre connector show", TABLE_TRANSFORMERS)

    def test_command_table_wires_transformer_for_connector_list_and_show(self):
        loader = SreCommandsLoader(cli_ctx=DummyCli())
        command_table = loader.load_command_table(["sre", "connector", "list"])
        self.assertIsNotNone(command_table["sre connector list"].table_transformer)
        self.assertIsNotNone(command_table["sre connector show"].table_transformer)
        self.assertIsNone(command_table["sre connector create"].table_transformer)


def setUpModule():
    # Keep route detection off by default so tests never touch the network or the real cache.
    os.environ["AZSRE_EXTENSION_ROUTE"] = "arm"


if __name__ == "__main__":
    unittest.main()

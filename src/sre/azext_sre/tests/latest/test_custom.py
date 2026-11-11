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
import io
import copy
import json
import os
import tempfile
import types
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

from requests import HTTPError, Response

from azure.cli.core import get_default_cli
from azure.cli.core.aaz import AAZCommand, AAZUndefined
from azure.cli.core.azclierror import CLIError, InvalidArgumentValueError, ResourceNotFoundError
from azure.cli.core.extension import DevExtension
from azure.cli.core.mock import DummyCli
from azure.core.exceptions import ResourceExistsError

from azext_sre import SreCommandsLoader
from azext_sre.custom import (
    EXTENSION_TYPES,
    EXTENSION_VALUE_VALIDATORS,
    GITHUB_COPILOT_MCP_ENDPOINT,
    KNOWLEDGE_TYPES,
    MANAGED_RESOURCE_ROLES,
    PORTAL_CONNECTOR_NAMES,
    Create,
    AgentSettingsShow,
    AgentSettingsUpdate,
    ConnectorCreate,
    ConnectorUpdate,
    ConnectorList,
    _ConnectorPartnerTypeMixin,
    GrantAccess,
    RevokeAccess,
    ManagedResourceGrant,
    ManagedResourceRevoke,
    ManagedResourceList,
    AccessList,
    UpdateNetwork,
    ShowNetwork,
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
    _devops_organization_from_url,
    _devops_pat_token,
    _direct_extension_create,
    _revoke_devops_pat,
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
    _show_internal_features,
    _listed_connector_types,
    _ExperimentalSettingsOnCreateMixin,
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


class VersionTests(unittest.TestCase):
    """'sre version' reports package metadata and the pinned API versions
    without any Azure call."""

    def test_reports_extension_and_api_versions(self):
        from importlib import metadata
        from azext_sre import custom
        command = _bare_command(custom.Version)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                patch.object(metadata, "version", return_value="9.9.9") as version, \
                patch("azext_sre.custom._arm_request") as arm:
            result = command._handler(None)
        version.assert_called_once_with("sre")
        arm.assert_not_called()
        self.assertEqual(result, {
            "extensionName": "sre",
            "extensionVersion": "9.9.9",
            "apiVersions": {
                "agents": custom.API_VERSION,
                "networking": custom.NETWORK_API_VERSION,
                "extensions": custom.EXTENSION_API_VERSION,
            },
        })

    def test_missing_package_metadata_is_a_clear_error(self):
        from importlib import metadata
        from azext_sre import custom
        with patch.object(metadata, "version", side_effect=metadata.PackageNotFoundError("sre")):
            with self.assertRaisesRegex(CLIError, "Reinstall the extension"):
                custom._version_info()


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

    def test_managed_connectors_point_to_the_portal(self):
        # The service now creates Outlook and Teams as managed connectors, like Gmail.
        for value, card in (
                ("outlook", "Office 365 Outlook"),
                ("Office 365 Outlook", "Office 365 Outlook"),
                ("TEAMS", "Microsoft Teams"),
                ("Microsoft Teams", "Microsoft Teams"),
                ("gmail", "Gmail"),
                ("Viva Engage", "Yammer")):
            with self.subTest(value=value):
                with self.assertRaises(CLIError) as raised:
                    _normalize_data_connector_type(value)
                self.assertIn(f"Set up {card} in the portal", str(raised.exception))

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


class HttpTraceSuppressionTests(unittest.TestCase):
    def _logged_body(self, secret):
        import logging
        from azext_sre import custom
        from azure.cli.core import util

        request = SimpleNamespace(url="https://x", method="PUT", headers={}, body=secret)
        logger = logging.getLogger("cli.azure.cli.core.util")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            with custom._no_http_trace():
                util._log_request(request)
            inside = [r.getMessage() for r in records]
            records.clear()
            util._log_request(request)
            after = [r.getMessage() for r in records]
            return inside, after
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

    def test_body_not_logged_inside_and_logged_after(self):
        inside, after = self._logged_body("ghp_secret")
        self.assertFalse(any("ghp_secret" in m for m in inside))
        self.assertTrue(any("ghp_secret" in m for m in after))

    def test_retried_request_body_not_logged(self):
        import logging
        from unittest.mock import MagicMock
        from azext_sre import custom
        from azure.cli.core.sdk.policies import SafeNetworkTraceLoggingPolicy
        from azure.core.pipeline import Pipeline
        from azure.core.pipeline.policies import RetryPolicy
        from azure.core.pipeline.transport import HttpTransport
        from azure.core.rest import HttpRequest

        statuses = [503, 200]

        class _Transport(HttpTransport):
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def open(self):
                pass

            def close(self):
                pass

            def send(self, request, **kwargs):
                response = MagicMock(status_code=statuses.pop(0), headers={"Retry-After": "0"},
                                     request=request)
                response.text.return_value = "body"
                return response

        logger = logging.getLogger("cli.azure.cli.core.sdk.policies")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        logger.addHandler(handler)
        previous = logger.level
        logger.setLevel(logging.DEBUG)
        try:
            pipeline = Pipeline(_Transport(), [RetryPolicy(retry_backoff_factor=0),
                                               SafeNetworkTraceLoggingPolicy()])
            request = HttpRequest("PUT", "https://x", content="ghp_secret")

            class _Send:
                def __call__(self, **kwargs):
                    return pipeline.run(request, **kwargs)

            class _SecretSend(custom._SecretHttpOperationMixin, _Send):
                pass

            _Send()(logging_enable=False)
            self.assertTrue(any("ghp_secret" in r.getMessage() for r in records))
            records.clear()
            statuses[:] = [503, 200]
            _SecretSend()()
            self.assertEqual(logger.level, logging.DEBUG)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)
        self.assertEqual(statuses, [])
        self.assertFalse(any("ghp_secret" in r.getMessage() for r in records))

    def test_levels_restored_when_the_call_raises(self):
        import logging
        from azext_sre import custom

        http_loggers = [logging.getLogger(name) for name in (
            "cli.azure.cli.core.util", "cli.azure.cli.core.sdk.policies")]
        for http_logger in http_loggers:
            self.addCleanup(http_logger.setLevel, http_logger.level)
            http_logger.setLevel(logging.INFO)
        with self.assertRaises(RuntimeError):
            with custom._no_http_trace():
                raise RuntimeError("request failed")
        self.assertEqual([http_logger.level for http_logger in http_loggers], [logging.INFO] * 2)

    def test_warns_only_when_secret_is_typed(self):
        from azext_sre import custom

        cases = [
            (["az", "--github-token", "ghp_x"], True),
            (["az", "--github-token=ghp_x"], True),
            (["az", "--github-token", "@token.txt"], False),
            (["az", "--github-token=@token.txt"], False),
            (["az", "--other", "x"], False),
        ]
        for argv, should_warn in cases:
            with self.subTest(argv=argv), patch.object(custom.sys, "argv", argv), \
                    patch.object(custom.logger, "warning") as warning:
                custom._warn_if_secret_typed("--github-token", "use GITHUB_TOKEN")
            self.assertEqual(warning.called, should_warn)
            if should_warn:
                self.assertNotIn("ghp_x", str(warning.call_args))


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
            _cli_invoke(cli_ctx, "ad", "signed-in-user", "show")
            _cli_invoke(cli_ctx, "sre", "agent", "show", "--subscription", "other")
        self.assertEqual(seen[0][-2:], ["--subscription", "sub-1"])
        self.assertNotIn("--subscription", seen[1])
        self.assertEqual(seen[2].count("--subscription"), 1)

    def test_nested_non_sre_commands_that_take_subscription_get_it(self):
        seen = []
        fake_cli = self._fake_cli()
        fake_cli.invoke = lambda args, out_file=None: seen.append(args) or 0
        cli_ctx = SimpleNamespace(data={"subscription_id": "sub-1"})
        commands = [
            ("role", "assignment", "list", "--assignee", "p", "--all"),
            ("role", "assignment", "create", "--role", "r", "--assignee", "p", "--scope", "s"),
            ("role", "assignment", "delete", "--role", "r", "--assignee", "p", "--scope", "s"),
            ("account", "show"),
            ("account", "get-access-token", "--resource", "x"),
        ]
        with patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            for command in commands:
                _cli_invoke(cli_ctx, *command)
        for args in seen:
            self.assertEqual(args[-2:], ["--subscription", "sub-1"], args)

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


def _fake_jwt(claims):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


_AGENT_ID = "/subscriptions/x/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"


class _GraphFreeNestedCli:
    """Fake nested `az` for the access commands. Fails the test on anything
    that would reach Microsoft Graph: any 'ad ...' command, a 'role
    assignment' call with --assignee (unless allowed), or a list call that
    fills in principal names (unless --show-names)."""

    def __init__(self, test, claims=None, token=None, user_type="user", tenant="tenant-1",
                 assignments=(), allow_names=False, allow_assignee=False):
        self.test = test
        self.token = token if token is not None else _fake_jwt(
            claims if claims is not None else {"oid": "my-oid", "tid": tenant})
        self.user_type = user_type
        self.tenant = tenant
        self.assignments = [dict(a) for a in assignments]
        self.allow_names = allow_names
        self.allow_assignee = allow_assignee
        self.calls = []

    @property
    def role_calls(self):
        return [call for call in self.calls if call[:2] == ("role", "assignment")]

    def __call__(self, cli_ctx, *args, allow_missing=False):
        self.calls.append(args)
        test = self.test
        test.assertNotEqual(args[:1], ("ad",), f"Microsoft Graph command: {args}")
        if args[:2] == ("account", "get-access-token"):
            return {"accessToken": self.token, "tokenType": "Bearer"}
        if args[:2] == ("account", "show"):
            return {"tenantId": self.tenant, "user": {"name": "me", "type": self.user_type}}
        if args[:3] == ("sre", "agent", "show"):
            return {"id": _AGENT_ID}
        test.assertEqual(args[:2], ("role", "assignment"), f"Unexpected command: {args}")
        if "--assignee" in args:
            test.assertTrue(self.allow_assignee, f"--assignee resolves through Microsoft Graph: {args}")
        options = dict(zip(args[3::2], args[4::2]))
        principal = options.get("--assignee-object-id") or options.get("--assignee")
        action = args[2]
        if action == "list":
            if not self.allow_names:
                test.assertEqual(options.get("--fill-principal-name"), "false", f"Graph names: {args}")
            return [
                dict(a) for a in self.assignments
                if a["scope"] == options["--scope"]
                and (principal is None or a["principalId"] == principal)
                and ("--role" not in options or a["roleDefinitionName"] == options["--role"])
            ]
        if action == "create":
            assignment = {
                "id": f"assignment-{len(self.assignments) + 1}",
                "principalId": principal,
                "principalType": options.get("--assignee-principal-type"),
                "roleDefinitionName": options["--role"],
                "scope": options["--scope"],
            }
            self.assignments.append(assignment)
            return dict(assignment)
        test.assertEqual(action, "delete")
        before = len(self.assignments)
        self.assignments = [
            a for a in self.assignments
            if (a["principalId"], a["roleDefinitionName"], a["scope"])
            != (principal, options["--role"], options["--scope"])
        ]
        if len(self.assignments) == before:
            raise CLIError("No matched assignments were found to delete")
        return None


class AssigneeMeTests(unittest.TestCase):
    """--assignee-me on access grant/revoke reads the signed-in account's
    object ID from its Azure Resource Manager token and its principal type
    from 'az account show' -- no Microsoft Graph, which Conditional Access
    token protection blocks for Azure CLI on macOS."""

    def _run(self, command_cls, fake, **args):
        command = _bare_command(command_cls, name="myagent", resource_group="myrg",
                                assignee=None, assignee_me=True, **args)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake):
            return command._handler({})

    def test_grant_access_assignee_me_resolves_signed_in_user(self):
        fake = _GraphFreeNestedCli(self)
        result = self._run(GrantAccess, fake, role="reader")

        self.assertEqual(result["principalId"], "my-oid")
        self.assertEqual(fake.role_calls, [
            ("role", "assignment", "list", "--assignee-object-id", "my-oid",
             "--role", "SRE Agent Reader", "--scope", _AGENT_ID, "--fill-principal-name", "false"),
            ("role", "assignment", "create", "--role", "SRE Agent Reader",
             "--assignee-object-id", "my-oid", "--assignee-principal-type", "User",
             "--scope", _AGENT_ID),
        ])

    def test_grant_access_assignee_me_service_principal_login(self):
        fake = _GraphFreeNestedCli(self, claims={"oid": "sp-oid", "tid": "tenant-1"},
                                   user_type="servicePrincipal")
        result = self._run(GrantAccess, fake, role="admin")

        self.assertEqual((result["principalId"], result["principalType"]), ("sp-oid", "ServicePrincipal"))
        self.assertEqual([a["principalType"] for a in fake.assignments], ["ServicePrincipal"])

    def test_grant_access_assignee_me_returns_existing_assignment_without_create(self):
        existing = {"id": "existing", "principalId": "my-oid", "principalType": "User",
                    "roleDefinitionName": "SRE Agent Reader", "scope": _AGENT_ID}
        fake = _GraphFreeNestedCli(self, assignments=[existing])
        result = self._run(GrantAccess, fake, role="reader")

        self.assertEqual(result, existing)
        self.assertEqual([call[2] for call in fake.role_calls], ["list"])

    def test_revoke_access_assignee_me_resolves_signed_in_user(self):
        mine = {"id": "a1", "principalId": "my-oid", "principalType": "User",
                "roleDefinitionName": "SRE Agent Author", "scope": _AGENT_ID}
        other = dict(mine, id="a2", principalId="someone-else")
        fake = _GraphFreeNestedCli(self, assignments=[mine, other])
        self._run(RevokeAccess, fake, role="author")

        self.assertEqual(fake.role_calls, [
            ("role", "assignment", "delete", "--role", "SRE Agent Author",
             "--assignee-object-id", "my-oid", "--scope", _AGENT_ID),
        ])
        self.assertEqual(fake.assignments, [other])

    def test_unreadable_token_is_a_clear_error_and_no_role_change(self):
        cases = {
            "not a JWT": "not-a-jwt",
            "bad payload": "header.!!!.signature",
            "payload not an object": _fake_jwt(["oid"]),
            "no oid claim": _fake_jwt({"tid": "tenant-1"}),
            "empty oid": _fake_jwt({"oid": " ", "tid": "tenant-1"}),
        }
        for label, token in cases.items():
            for command_cls in (GrantAccess, RevokeAccess):
                with self.subTest(label, command=command_cls.__name__):
                    fake = _GraphFreeNestedCli(self, token=token)
                    with self.assertRaises(CLIError) as raised:
                        self._run(command_cls, fake, role="reader")
                    message = str(raised.exception)
                    self.assertIn("Could not read your object ID", message)
                    self.assertNotIn(token, message)
                    self.assertEqual(fake.role_calls, [])

    def test_unsupported_account_type_is_rejected(self):
        fake = _GraphFreeNestedCli(self, user_type="")
        with self.assertRaises(CLIError) as raised:
            self._run(GrantAccess, fake, role="reader")
        self.assertIn("Unsupported signed-in account type", str(raised.exception))
        self.assertEqual(fake.role_calls, [])

    def test_token_from_another_tenant_is_rejected(self):
        fake = _GraphFreeNestedCli(self, claims={"oid": "my-oid", "tid": "tenant-2"}, tenant="tenant-1")
        with self.assertRaises(CLIError) as raised:
            self._run(GrantAccess, fake, role="reader")
        self.assertIn("tenant-2", str(raised.exception))
        self.assertEqual(fake.role_calls, [])

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
        """Default 'access list' returns object IDs without Microsoft Graph."""
        assignment = {"id": "a1", "principalId": "my-oid", "principalType": "User",
                      "roleDefinitionName": "SRE Agent Reader", "scope": _AGENT_ID}
        fake = _GraphFreeNestedCli(self, assignments=[assignment])
        command = _bare_command(AccessList, name="myagent", resource_group="myrg", show_names=False)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake):
            result = command._handler({})

        self.assertEqual(result, [assignment])
        self.assertEqual(fake.role_calls, [
            ("role", "assignment", "list", "--scope", _AGENT_ID, "--fill-principal-name", "false"),
        ])

    def test_access_list_show_names_lets_azure_cli_fill_names(self):
        fake = _GraphFreeNestedCli(self, allow_names=True)
        command = _bare_command(AccessList, name="myagent", resource_group="myrg", show_names=True)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake):
            command._handler({})

        self.assertEqual(fake.role_calls, [("role", "assignment", "list", "--scope", _AGENT_ID)])

    def test_access_list_raises_when_agent_not_found(self):
        command = _bare_command(AccessList, name="ghost", resource_group="rg", show_names=False)

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return None

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            with self.assertRaises(ResourceNotFoundError):
                command._handler({})


class AssigneeMeSubscriptionTenantTests(unittest.TestCase):
    """Regression: 'az ad signed-in-user show' ignored --subscription and
    used the default subscription's tenant, so with a login spanning several
    tenants --assignee-me picked the wrong object ID (PrincipalNotFound).
    Uses the real _cli_invoke so its --subscription forwarding is exercised."""

    TOKENS = {
        "sub-default": _fake_jwt({"oid": "oid-default", "tid": "tenant-default"}),
        "sub-other": _fake_jwt({"oid": "oid-other", "tid": "tenant-other"}),
    }
    TENANTS = {"sub-default": "tenant-default", "sub-other": "tenant-other"}

    def _grant(self, subscription):
        seen = []
        fake_cli = SimpleNamespace(out_file=None, result=None)

        def invoke(args, out_file=None):  # pylint: disable=unused-argument
            seen.append(list(args))
            self.assertNotEqual(args[0], "ad")
            self.assertNotIn("--assignee", args)
            sub = args[args.index("--subscription") + 1] if "--subscription" in args else "sub-default"
            if args[:2] == ["account", "get-access-token"]:
                result = {"accessToken": self.TOKENS[sub]}
            elif args[:2] == ["account", "show"]:
                result = {"id": sub, "tenantId": self.TENANTS[sub], "user": {"type": "user"}}
            elif args[:3] == ["sre", "agent", "show"]:
                result = {"id": f"/subscriptions/{sub}/resourceGroups/myrg/providers/Microsoft.App/agents/myagent"}
            elif args[:3] == ["role", "assignment", "list"]:
                self.assertIn("--fill-principal-name", args)
                result = []
            else:
                self.assertEqual(args[:3], ["role", "assignment", "create"])
                result = {"principalId": args[args.index("--assignee-object-id") + 1]}
            fake_cli.result = SimpleNamespace(result=result)
            return 0

        fake_cli.invoke = invoke
        command = _bare_command(GrantAccess, name="myagent", resource_group="myrg", role="reader",
                                assignee=None, assignee_me=True)
        command.cli_ctx = SimpleNamespace(data={"subscription_id": subscription} if subscription else {})
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azure.cli.core.get_default_cli", return_value=fake_cli):
            return command._handler({}), seen

    def test_assignee_me_uses_the_requested_subscriptions_tenant(self):
        result, seen = self._grant("sub-other")

        self.assertEqual(result["principalId"], "oid-other")
        for args in seen:
            self.assertEqual(args[-2:], ["--subscription", "sub-other"], args)
        self.assertNotIn("oid-default", [arg for args in seen for arg in args])

    def test_assignee_me_without_subscription_uses_the_default(self):
        result, _ = self._grant(None)
        self.assertEqual(result["principalId"], "oid-default")


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
            if args[:3] == ("role", "assignment", "list"):
                return []
            return {"result": "created"}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            result = command._handler({})

        self.assertEqual(result, [{"result": "created"}, {"result": "created"}])
        role_assignment_calls = [c for c in calls if c[:2] == ("role", "assignment")]
        expected = []
        for role in ("Reader", "Monitoring Contributor"):
            expected += [
                ("role", "assignment", "list", "--assignee-object-id", "agent-principal-id",
                 "--role", role, "--scope", "/subscriptions/sub-guid", "--fill-principal-name", "false"),
                ("role", "assignment", "create", "--role", role,
                 "--assignee-object-id", "agent-principal-id", "--assignee-principal-type", "ServicePrincipal",
                 "--scope", "/subscriptions/sub-guid"),
            ]
        self.assertEqual(role_assignment_calls, expected)

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
                ("role", "assignment", "delete", "--role", role, "--assignee-object-id", "agent-principal-id",
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
            calls[-1], ("role", "assignment", "list", "--assignee-object-id", "agent-principal-id", "--all",
                        "--fill-principal-name", "false"),
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
        self.filter_error = None
        self.handler_error = None
        self.handler_path = "/api/v2/extendedAgent/incidentHandlers"
        self.filter_path = "/api/v2/incidentManagement/incidentFilters"
        self.agent_filter_deletes = []
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
        if self.filter_error:
            raise self.filter_error
        self.filters[name] = json.loads(value)
        return self._arm_show(cli_ctx, agent, group, extension_type, name)

    def _arm_show(self, cli_ctx, agent, group, extension_type, name):
        if extension_type != "incidentFilters":
            raise ResourceNotFoundError("The ARM handler proxy is unavailable.")
        if name not in self.filters:
            raise ResourceNotFoundError(f"Extension '{name}' not found.")
        return {"name": name, "properties": {"value": copy.deepcopy(self.filters[name])}}

    def _arm_list(self, cli_ctx, agent, group, extension_type):
        return {"value": [
            self._arm_show(cli_ctx, agent, group, extension_type, name) for name in self.filters
        ]}

    def _arm_delete(self, cli_ctx, agent, group, extension_type, name):
        if extension_type != "incidentFilters":
            raise ResourceNotFoundError("The ARM handler proxy is unavailable.")
        # ARM answers {} whether or not the plan exists.
        self.filters.pop(name, None)
        return {}

    def _agent_request(self, cli_ctx, agent, group, method, path, body=None,
                       missing_ok=False, agent_url=None):
        if method == "GET" and path == self.handler_path:
            return copy.deepcopy(list(self.handlers.values()))
        if method == "DELETE" and path.startswith(self.filter_path + "/"):
            self.agent_filter_deletes.append(path.rsplit("/", 1)[-1])
            self.filters.pop(path.rsplit("/", 1)[-1], None)
            return {}
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

    @staticmethod
    def _forbidden(code=None):
        response = Response()
        response.status_code = 403
        response._content = (json.dumps({"error": {"code": code, "message": "Denied"}}).encode()
                             if code else b"Forbidden")
        return HTTPError("Forbidden", response=response)

    def test_azure_monitor_criteria_are_sent_and_merged_on_update(self):
        from azext_sre.custom import ResponsePlanUpdate
        self._create(alert_id="/subscriptions/s/alertRules/r", target_resource_type="Microsoft.App/containerApps")
        self.assertEqual(self.filters["plan"]["alertId"], "/subscriptions/s/alertRules/r")
        self.assertEqual(self.filters["plan"]["azMonitorFilterSettings"],
                         {"targetResourceType": "Microsoft.App/containerApps"})
        self._command(ResponsePlanUpdate, target_resource="ca-api")
        self.assertEqual(self.filters["plan"]["azMonitorFilterSettings"],
                         {"targetResourceType": "Microsoft.App/containerApps", "targetResource": "ca-api"})

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

    def test_instructions_only_update_succeeds_without_writing_the_filter(self):
        from azext_sre.custom import ResponsePlanUpdate
        self._create(instructions=None)
        self.filter_error = self._forbidden()
        result = self._command(ResponsePlanUpdate, instructions="Check dependencies")
        self.assertEqual(self.handlers["plan"]["customInstructions"], "Check dependencies")
        self.assertEqual(result["filter"]["properties"], self.filters["plan"])

    def test_instructions_only_update_of_a_missing_plan_saves_nothing(self):
        from azext_sre.custom import ResponsePlanUpdate
        with self.assertRaises(ResourceNotFoundError):
            self._command(ResponsePlanUpdate, instructions="Check dependencies")
        self.assertEqual(self.handlers, {})

    def test_update_leaves_the_filter_unchanged_when_reading_instructions_fails(self):
        from azext_sre.custom import ResponsePlanUpdate
        self._create(instructions=None)
        saved_filter = copy.deepcopy(self.filters["plan"])
        with patch("azext_sre.custom._data_plane_request", side_effect=self._forbidden()), \
             self.assertRaises(HTTPError):
            self._command(ResponsePlanUpdate, mode="autonomous", instructions="Check dependencies")
        self.assertEqual(self.filters["plan"], saved_filter)

    def test_failed_instruction_save_reports_only_filter_changes_that_were_saved(self):
        from azext_sre.custom import ResponsePlanUpdate
        self._create(instructions=None)
        self.handler_error = self._forbidden()
        with self.subTest("mixed update"), \
             self.assertRaisesRegex(CLIError, r"\(agentMode, priorities\) were saved"):
            self._command(
                ResponsePlanUpdate, mode="autonomous", priorities=["Sev0"], instructions="Check dependencies")
        self.assertEqual(self.filters["plan"]["agentMode"], "autonomous")
        with self.subTest("instructions only"), self.assertRaises(HTTPError):
            self._command(ResponsePlanUpdate, instructions="Check dependencies")

    def test_show_skips_instructions_when_the_agent_has_no_handler_route(self):
        from azext_sre.custom import ResponsePlanShow, DataPlaneRouteUnavailableError
        self._create()
        with patch("azext_sre.custom._data_plane_request",
                   side_effect=DataPlaneRouteUnavailableError("web page")):
            shown = self._command(ResponsePlanShow)
        self.assertEqual(shown["handlers"], [])
        self.assertIn("plan", self.filters)

    def test_delete_does_not_fall_back_on_other_arm_errors(self):
        from azext_sre.custom import ResponsePlanDelete
        self._create(instructions=None)
        server_error = self._forbidden()
        server_error.response.status_code = 500
        for error in (server_error, self._forbidden(), self._forbidden("RequestDisallowedByPolicy")):
            with self.subTest(status=error.response.status_code, body=error.response.text), \
                 patch("azext_sre.custom._extension_resource_delete", side_effect=error), \
                 self.assertRaises(HTTPError):
                self._command(ResponsePlanDelete)
        self.assertEqual(self.agent_filter_deletes, [])
        self.assertIn("plan", self.filters)

    def test_icm_plan_requires_an_incident_type_and_sends_the_portal_field(self):
        with patch("azext_sre.custom._require_first_party"):
            with self.assertRaisesRegex(CLIError, "--incident-type is required"):
                self._create(platform="Icm")
            self.assertEqual(self.filters, {})
            self._create(platform="Icm", incident_types=["LiveSite"])
        self.assertEqual(self.filters["plan"]["incidentTypes"], ["LiveSite"])
        self.assertEqual(self.filters["plan"]["incidentType"], "LiveSite")

    def test_delete_removes_all_linked_handlers_without_touching_another_plan(self):
        from azext_sre.custom import ResponsePlanDelete
        self._create()
        self.handlers["extra"] = {"id": "extra", "incidentFilterId": "plan"}
        unrelated = {"id": "other", "incidentFilterId": "other-plan", "customInstructions": "Keep"}
        self.handlers["other"] = unrelated
        self.assertIsNone(self._command(ResponsePlanDelete))
        self.assertEqual(self.handlers, {"other": unrelated})
        self.assertNotIn("plan", self.filters)

    def test_delete_of_a_missing_plan_is_not_found(self):
        from azext_sre.custom import ResponsePlanDelete
        with self.assertRaises(ResourceNotFoundError):
            self._command(ResponsePlanDelete)

    def test_delete_removes_instructions_whose_filter_is_already_gone(self):
        from azext_sre.custom import ResponsePlanDelete
        self.handlers["plan"] = {"id": "plan", "incidentFilterId": "plan", "customInstructions": "Check logs"}
        self._command(ResponsePlanDelete)
        self.assertEqual(self.handlers, {})

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
        self.handler_error = self._forbidden()
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

    def test_max_investigation_attempts_is_sent_and_validated(self):
        from azext_sre.custom import ResponsePlanCreate, ResponsePlanUpdate
        base = dict(
            agent_name="a", resource_group="rg", extension_name="plan", platform="AzMonitor",
            subagent="meta_agent", priorities=None, title_contains=None, title_not_contains=None,
            incident_types=None, impacted_service=None, owning_teams=None, merge_enabled=None,
            merge_window_hours=None, mode="autonomous", disabled=None, instructions=None,
            processing_guide=None, overwrite=None)
        command = _bare_command(ResponsePlanCreate, **base, max_investigation_attempts=2)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._incident_resource_create", return_value={}) as create, \
             patch("azext_sre.custom._extension_resource_list", return_value={"value": []}):
            command._handler(None)
        flt = create.call_args.args[5]
        self.assertEqual((flt["handlingAgent"], flt["maxAutomatedInvestigationAttempts"]), ("meta_agent", 2))

        existing = {"name": "plan", "properties": {"value": {"handlingAgent": "s"}}}
        command = _bare_command(ResponsePlanUpdate, **{**base, "platform": None, "subagent": None,
                                                       "mode": None}, max_investigation_attempts=5)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show", return_value=existing), \
             patch("azext_sre.custom._incident_resource_create", return_value={}) as create:
            command._handler(None)
        self.assertEqual(create.call_args.args[5], {"handlingAgent": "s", "maxAutomatedInvestigationAttempts": 5})

        for cls in (ResponsePlanCreate, ResponsePlanUpdate):
            with self.subTest(cls=cls.__name__):
                command = _bare_command(cls, **base, max_investigation_attempts=0)
                with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                     patch("azext_sre.custom._incident_resource_create") as create, \
                     self.assertRaises(CLIError):
                    command._handler(None)
                create.assert_not_called()

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

    def test_agent_url_validates_the_host_the_token_is_sent_to(self):
        from azext_sre.custom import _validate_agent_url
        accepted = {
            "https://x.azuresre.ai": "https://x.azuresre.ai",
            "https://x.azuresre.ai:443/api?q=1": "https://x.azuresre.ai:443",
            "HTTPS://X.AzureSRE.AI/": "https://x.azuresre.ai",
        }
        for url, expected in accepted.items():
            with self.subTest(url=url):
                self.assertEqual(_validate_agent_url(url), expected)
        for url in (
            # A backslash ends the host in requests/urllib3, so reject it outright.
            "https://attacker.example\\@a--1.x.swedencentral.azuresre.ai/api",
            "https://x.azuresre.ai\\foo",
            # Userinfo would become a Basic Authorization header replacing the bearer token.
            "https://evil.example@x.azuresre.ai",
            "https://x.azuresre.ai@evil.example",
            "https://x.azuresre.ai.evil.example",
            "https://x.azuresre.ai:evil",
            "https://x.azuresre.ai:99999",
            " https://x.azuresre.ai",
            "http://x.azuresre.ai",
            "https://azuresre.ai",
            "",
        ):
            with self.subTest(url=url), self.assertRaises(CLIError):
                _validate_agent_url(url)

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
             patch("azext_sre.custom._data_plane_request", return_value=[]), \
             patch("azext_sre.custom._extension_resource_list", return_value={"value": []}):
            result = command._handler(None)
        self.assertEqual(set(result), {"filter", "handler"})
        flt = created[0][1]
        self.assertEqual((flt["handlingAgent"], flt["agentMode"], flt["isEnabled"]), ("responder", "review", True))
        self.assertEqual(created[1][1]["incidentFilterId"], "plan")

    def _rejected_create(self, agent, subagent_exists, subagent="responder"):
        from azext_sre.custom import ResponsePlanCreate
        command = _bare_command(
            ResponsePlanCreate, agent_name="a", resource_group="rg", extension_name="plan",
            platform="AzMonitor", subagent=subagent, priorities=None, title_contains=None,
            incident_types=None, impacted_service=None, owning_teams=None, merge_enabled=None, merge_window_hours=None,
            title_not_contains=None, mode="review", disabled=None,
            instructions=None, processing_guide=None, overwrite=None)
        show = MagicMock() if subagent_exists else MagicMock(side_effect=ResourceNotFoundError("missing"))
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._incident_resource_create", side_effect=self.rejection), \
             patch("azext_sre.custom._cli_invoke", return_value=agent), \
             patch("azext_sre.custom._extension_resource_show", show):
            return command._handler(None)

    @property
    def rejection(self):
        return self._http_error(400, '{"error":{"message":"The extension configuration is invalid."}}')

    def test_response_plan_rejection_names_missing_subagent(self):
        agent = {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}}
        with self.assertRaisesRegex(CLIError, "Subagent 'responder' doesn't exist") as ctx:
            self._rejected_create(agent, subagent_exists=False)
        self.assertNotIn("incident platform", str(ctx.exception))
        self.assertIn("The extension configuration is invalid.", str(ctx.exception))

    def test_response_plan_rejection_keeps_service_error_when_cause_unknown(self):
        agent = {"properties": {"incidentManagementConfiguration": {"type": "AzMonitor"}}}
        with self.assertRaises(HTTPError) as raised:
            self._rejected_create(agent, subagent_exists=True)
        self.assertEqual(raised.exception.response.status_code, 400)

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

    def test_response_plan_explains_unconnected_platform(self):
        from azext_sre.custom import ResponsePlanCreate
        command = _bare_command(
            ResponsePlanCreate, agent_name="a", resource_group="rg", extension_name="plan",
            platform="AzMonitor", subagent="s", priorities=None, title_contains=None,
            incident_types=None, impacted_service=None, owning_teams=None, merge_enabled=None, merge_window_hours=None,
            title_not_contains=None, mode="review", disabled=None,
            instructions=None, processing_guide=None, overwrite=None)
        service_error = self.rejection
        for config, expect_hint in ((None, True), ({"type": "AzMonitor"}, False)):
            agent = {"properties": {"incidentManagementConfiguration": config}}
            with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                 patch("azext_sre.custom._incident_resource_create", side_effect=service_error), \
                 patch("azext_sre.custom._cli_invoke", return_value=agent), \
                 self.assertRaises((CLIError, HTTPError)) as raised:
                command._handler(None)
            message = str(raised.exception)
            if expect_hint:
                self.assertIn("has no incident platform connected", message)
                self.assertIn("{type:AzMonitor,connection-name:azmonitor}", message)
            else:
                self.assertIs(raised.exception, service_error)

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

    def test_html_response_raises_a_clear_route_error(self):
        from azext_sre.custom import DataPlaneRouteUnavailableError
        response = Response()
        response.status_code = 200
        response.headers["Content-Type"] = "text/html; charset=utf-8"
        response._content = b"<!doctype html><html></html>"
        with patch("azext_sre.custom._resolve_agent_endpoint", return_value="https://agent.example"), \
             patch("azext_sre.custom.send_raw_request", return_value=response), \
             self.assertRaisesRegex(DataPlaneRouteUnavailableError, "web page"):
            _data_plane_request(None, "agent", "rg", "GET", "/api/plan")

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

    _INSTRUCTIONS = (
        "You are the application evidence specialist. Read supplied reference "
        "files with ReadFile and return source-backed observations."
    )

    def test_accepts_the_real_confirmed_example_payload(self):
        raw = json.dumps({
            "instructions": self._INSTRUCTIONS,
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
            "instructions": self._INSTRUCTIONS, "handoffDescription": "y",
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
            "instructions": self._INSTRUCTIONS, "handoffDescription": "y",
            "tools": "ReadFile", "mcpTools": [], "commonTools": [],
            "allowedSkills": [], "allowParallelToolCalls": True,
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.tools must be a JSON array of strings", str(raised.exception))

    def test_rejects_non_bool_allow_parallel_tool_calls(self):
        raw = json.dumps({
            "instructions": self._INSTRUCTIONS, "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": "true",
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.allowParallelToolCalls", str(raised.exception))

    def test_rejects_hooks_not_object(self):
        raw = json.dumps({
            "instructions": self._INSTRUCTIONS, "handoffDescription": "y",
            "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
            "allowParallelToolCalls": True, "hooks": ["not", "an", "object"],
        })
        with self.assertRaises(CLIError) as raised:
            _encode_extension_value(raw, "subagents")
        self.assertIn("--value.hooks must be a JSON object", str(raised.exception))

    def test_hook_entry_script_is_type_checked_but_not_presence_required(self):
        raw = json.dumps({
            "instructions": self._INSTRUCTIONS, "handoffDescription": "y",
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


class SubagentCreateValidationTests(unittest.TestCase):
    _AGENT_ID = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/agent"
    _RESOURCE_ID = _AGENT_ID + "/subagents/specialist"
    _VALID_VALUE = json.dumps({
        "instructions": "Investigate the supplied evidence and return concise, source-backed observations.",
        "oldOnly": True,
    })

    def setUp(self):
        self.resources = {}
        for replacement in (
            patch.object(AAZCommand, "_handler", lambda command, command_args: None),
            patch("azext_sre.custom._cli_invoke", return_value={"id": self._AGENT_ID}),
            patch("azext_sre.custom._arm_request", side_effect=self._arm_request),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def _arm_request(self, cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
        if method == "PUT":
            self.resources[resource_id] = copy.deepcopy(body)
        elif method != "GET":
            raise AssertionError(f"Unexpected ARM method: {method}")
        return copy.deepcopy(self.resources.get(resource_id))

    def _create(self, raw_value, overwrite=False):
        return _bare_command(
            SubagentCreate, agent_name="agent", resource_group="rg", extension_name="specialist",
            value=raw_value, overwrite=overwrite, pre_tool_use_script_file=None,
        )._handler(None)

    def test_short_instructions_report_the_limit_without_mutating_resources(self):
        for instructions in ("You are a helpful assistant. Be concise.", "private-prompt-" + "x" * 34):
            for overwrite in (False, True):
                with self.subTest(length=len(instructions), overwrite=overwrite):
                    self.resources.clear()
                    if overwrite:
                        self._create(self._VALID_VALUE)
                    before = copy.deepcopy(self.resources)
                    with self.assertRaises(CLIError) as raised:
                        self._create(json.dumps({"instructions": instructions}), overwrite=overwrite)
                    message = str(raised.exception)
                    self.assertIn("--value.instructions", message)
                    self.assertIn("at least 50 characters", message)
                    self.assertNotIn(instructions, message)
                    self.assertEqual(self.resources, before)

    def test_valid_instructions_and_stop_hooks_are_sent_without_rewriting(self):
        for instructions in ("x" * 50, " " + "x" * 48 + " ", json.loads(self._VALID_VALUE)["instructions"]):
            for overwrite in (False, True):
                with self.subTest(length=len(instructions), overwrite=overwrite):
                    self.resources.clear()
                    if overwrite:
                        self._create(self._VALID_VALUE)
                    raw = json.dumps({
                        "instructions": instructions,
                        "handoffDescription": "Use for read-only evidence.",
                        "tools": [], "mcpTools": [], "commonTools": [], "allowedSkills": [],
                        "allowParallelToolCalls": False,
                        "hooks": {"Stop": [{
                            "type": "prompt", "prompt": "Require the final response marker DONE.",
                            "timeout": 30, "failMode": "block",
                        }]},
                    }, indent=2)
                    self._create(raw, overwrite=overwrite)
                    stored = self.resources[self._RESOURCE_ID]["properties"]["value"]
                    self.assertEqual(base64.b64decode(stored).decode("utf-8"), raw)

    def test_omitted_and_blank_instructions_keep_existing_default_handling(self):
        for value in ({}, {"instructions": ""}, {"instructions": " \t\r\n"}):
            with self.subTest(value=value):
                raw = json.dumps(value)
                self._create(self._VALID_VALUE, overwrite=True)
                self._create(raw, overwrite=True)
                stored = self.resources[self._RESOURCE_ID]["properties"]["value"]
                self.assertEqual(base64.b64decode(stored).decode("utf-8"), raw)

    def test_malformed_input_still_fails_without_overwriting(self):
        self._create(self._VALID_VALUE)
        before = copy.deepcopy(self.resources)
        for raw, error in (
            ("not json {{{", r"--value.*JSON"),
            ("[]", "must be a JSON object"),
            ('{"instructions": null}', r"--value.instructions.*string"),
            ('{"instructions": 123}', r"--value.instructions.*string"),
        ):
            with self.subTest(raw=raw):
                with self.assertRaisesRegex(CLIError, error):
                    self._create(raw, overwrite=True)
                self.assertEqual(self.resources, before)

    def test_existing_name_still_requires_explicit_overwrite(self):
        self._create(self._VALID_VALUE)
        before = copy.deepcopy(self.resources)
        with self.assertRaisesRegex(ResourceExistsError, "--overwrite"):
            self._create('{"instructions": "short"}')
        self.assertEqual(self.resources, before)

    def test_unrelated_service_errors_are_not_replaced_with_a_prompt_diagnosis(self):
        error = CLIError("Unrelated service validation failure.")
        with patch("azext_sre.custom._arm_request", side_effect=error):
            with self.assertRaises(CLIError) as raised:
                self._create(self._VALID_VALUE, overwrite=True)
        self.assertIs(raised.exception, error)

    def test_invalid_configuration_without_handoff_description_explains_the_field(self):
        error = CLIError("Bad Request: The extension configuration is invalid.")
        for value, explained in ((self._VALID_VALUE, True),
                                 (json.dumps({**json.loads(self._VALID_VALUE), "handoffDescription": "Use for triage."}), False)):
            with self.subTest(explained=explained), \
                 patch("azext_sre.custom._arm_request", side_effect=error), \
                 self.assertRaises(CLIError) as raised:
                self._create(value, overwrite=True)
            if explained:
                self.assertIn("--value.handoffDescription", str(raised.exception))
            else:
                self.assertIs(raised.exception, error)


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

    def test_rejects_lookalike_hosts(self):
        for url in ("https://evilvisualstudio.com/p/_git/r", "https://notdev.azure.com/o/p/_git/r"):
            with self.assertRaises(CLIError):
                _detect_repo_provider(url)


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
             patch("azext_sre.custom._devops_pat_token", lambda cli_ctx, org, name: ("ado-pat-xyz", "auth-id-1")):
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
             patch("azext_sre.custom._devops_pat_token", lambda cli_ctx, org, name: ("ado-pat-xyz", "auth-id-1")):
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

    def test_default_display_name_drops_git_suffix_query_and_slash(self):
        for url in ("https://github.com/org/repo.git", "https://github.com/org/repo/",
                    "https://github.com/org/repo.git?ref=main#readme"):
            _, calls = self._run_github(repo_url=url)
            self.assertEqual(calls[1][1], "repo", url)
            self.assertEqual(json.loads(calls[1][2])["description"], "repo")

    def test_bad_repository_name_fails_before_auth_is_written(self):
        with self.assertRaises(CLIError) as raised:
            self._run_github(display_name="bad/name")
        self.assertIn("not a valid repository name", str(raised.exception))
        command, calls, fake_create = self._run_devops(display_name="bad?name")
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_create), \
             patch("azext_sre.custom._devops_pat_token") as fake_pat:
            with self.assertRaises(CLIError):
                command._handler({})
        self.assertEqual(calls, [])
        fake_pat.assert_not_called()

    def test_invalid_repository_value_fails_before_auth_is_written(self):
        command, calls, fake_create = self._run_devops(branch=None)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_create), \
             patch("azext_sre.custom._normalize_extension_value",
                   side_effect=CLIError("--value.url is required")), \
             patch("azext_sre.custom._devops_pat_token") as fake_pat:
            with self.assertRaises(CLIError):
                command._handler({})
        self.assertEqual(calls, [])
        fake_pat.assert_not_called()

    def test_visualstudio_com_org_comes_from_the_host(self):
        command, calls, fake_create = self._run_devops(
            repo_url="https://contoso.visualstudio.com/Proj/_git/repo")
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_create), \
             patch("azext_sre.custom._devops_pat_token",
                   lambda cli_ctx, org, name: ("ado-pat-xyz", "auth-id-1")) as _:
            command._handler({})
        self.assertEqual(calls[0][:2], ("azureDevOpsAuths", "contoso"))

    def test_dev_azure_com_org_comes_from_the_path(self):
        self.assertEqual(_devops_organization_from_url("https://dev.azure.com/contoso/Proj/_git/repo"), "contoso")
        self.assertEqual(_devops_organization_from_url("https://contoso.visualstudio.com/Proj/_git/repo"), "contoso")

    def _run_devops_with_failure(self, fail_on):
        command, calls, _ = self._run_devops()

        def fake_create(cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value,
                        overwrite=False):
            calls.append(extension_type)
            if extension_type == fail_on:
                raise CLIError(f"{extension_type} PUT failed")
            return {"properties": {"value": "stub"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_create", fake_create), \
             patch("azext_sre.custom._devops_pat_token",
                   lambda cli_ctx, org, name: ("ado-pat-xyz", "auth-id-1")), \
             patch("azext_sre.custom._revoke_devops_pat") as fake_revoke, \
             patch("azext_sre.custom.logger") as fake_logger:
            with self.assertRaises(CLIError) as raised:
                command._handler({})
        warnings = [call.args[0] % call.args[1:] for call in fake_logger.warning.call_args_list]
        return raised.exception, fake_revoke, warnings

    def test_pat_is_revoked_when_the_auth_write_fails(self):
        error, fake_revoke, _ = self._run_devops_with_failure("azureDevOpsAuths")
        self.assertIn("azureDevOpsAuths PUT failed", str(error))
        fake_revoke.assert_called_once_with(ANY, "contoso", "auth-id-1")

    def test_repo_write_failure_warns_about_the_new_credentials(self):
        error, fake_revoke, logs = self._run_devops_with_failure("repositories")
        self.assertIn("repositories PUT failed", str(error))
        fake_revoke.assert_not_called()
        self.assertTrue(any("but connecting repository 'repo' failed" in line for line in logs), logs)

    def test_revoke_devops_pat_sends_delete_with_authorization_id(self):
        with patch("azext_sre.custom._cli_invoke", return_value={"accessToken": "aad"}), \
             patch("azext_sre.custom.send_raw_request") as fake_send:
            _revoke_devops_pat(object(), "contoso", "auth-id-1")
        method, url = fake_send.call_args[0][1:3]
        self.assertEqual(method, "DELETE")
        self.assertIn("vssps.dev.azure.com/contoso/_apis/tokens/pats?authorizationId=auth-id-1", url)
        self.assertIn("Authorization=Bearer aad", fake_send.call_args[1]["headers"])

    def test_revoke_devops_pat_failure_only_warns(self):
        with patch("azext_sre.custom._cli_invoke", return_value={"accessToken": "aad"}), \
             patch("azext_sre.custom.send_raw_request", side_effect=CLIError("boom")), \
             self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
            _revoke_devops_pat(object(), "contoso", "auth-id-1")
        self.assertIn("revoke it manually", "\n".join(logs.output))

    def test_devops_pat_token_returns_authorization_id(self):
        response = MagicMock()
        response.json.return_value = {"patToken": {"token": "pat", "authorizationId": "auth-id-1"}}
        with patch("azext_sre.custom._cli_invoke", return_value={"accessToken": "aad"}), \
             patch("azext_sre.custom.send_raw_request", return_value=response):
            self.assertEqual(_devops_pat_token(object(), "contoso", "name"), ("pat", "auth-id-1"))


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

        requested = []

        def fake_post(url, **kwargs):
            if url.endswith("/login/device/code"):
                requested.append(kwargs["data"]["scope"])
                return code_response
            return next(token_responses)

        with patch("requests.post", side_effect=fake_post), \
             patch("time.sleep"), \
             patch("azure.cli.core.util.open_page_in_browser"):
            token = _github_device_flow()
        self.assertEqual(token, "real-device-flow-token")
        self.assertEqual(requested, ["repo workflow"])

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

    def test_agent_mode_is_case_insensitive_and_sent_lowercase(self):
        encoded = _encode_extension_value(json.dumps({"agentPrompt": "x", "agentMode": "Review"}), "httpTriggers")
        self.assertEqual(json.loads(base64.b64decode(encoded))["agentMode"], "review")


class ScheduledTaskStatusTests(unittest.TestCase):

    def _sent(self, value):
        return json.loads(base64.b64decode(_encode_extension_value(json.dumps(value), "scheduledTasks")))

    def test_is_enabled_false_is_sent_as_paused_status(self):
        sent = self._sent({"cronExpression": "0 9 * * *", "agentPrompt": "x", "isEnabled": False})
        self.assertEqual(sent["status"], "Paused")
        self.assertNotIn("isEnabled", sent)
        self.assertEqual(self._sent({"agentPrompt": "x", "isEnabled": True})["status"], "Active")

    def test_conflicting_or_unknown_status_is_rejected(self):
        with self.assertRaisesRegex(CLIError, "disagree"):
            self._sent({"isEnabled": False, "status": "Active"})
        with self.assertRaisesRegex(CLIError, "status must be one of"):
            self._sent({"status": "Disabled"})

    def test_pause_and_resume_write_back_the_task_with_the_new_status(self):
        from azext_sre.custom import AutomationScheduledTaskPause, AutomationScheduledTaskResume

        current = {"name": "t", "properties": {"value": {
            "cronExpression": "0 9 * * *", "agentPrompt": "x", "agent": None, "status": "Active"}}}
        for cls, status in ((AutomationScheduledTaskPause, "Paused"), (AutomationScheduledTaskResume, "Active")):
            command = _bare_command(cls, agent_name="a", resource_group="rg", extension_name="t")
            with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                 patch("azext_sre.custom._extension_resource_show", return_value=json.loads(json.dumps(current))), \
                 patch("azext_sre.custom._extension_resource_create", return_value={}) as create:
                command._handler({})
            args, kwargs = create.call_args
            self.assertEqual(args[3:5], ("scheduledTasks", "t"))
            self.assertEqual(json.loads(args[5]), {"cronExpression": "0 9 * * *", "agentPrompt": "x", "status": status})
            self.assertTrue(kwargs["overwrite"])


class EmptyExtensionListWarningTests(unittest.TestCase):

    def _run(self, command):
        with patch.dict(os.environ, {"AZSRE_EXTENSION_ROUTE": "arm"}), \
             patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._resolve_agent_resource_id", return_value="/agents/a"), \
             patch("azext_sre.custom._extension_arm_request", return_value={"value": []}), \
             self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
            self.assertEqual(command._handler({}), [])
        return logs.output

    def test_empty_response_plan_list_warns_once(self):
        from azext_sre.custom import ResponsePlanList
        output = self._run(_bare_command(ResponsePlanList, agent_name="a", resource_group="rg", agent_url=None))
        self.assertEqual(len(output), 1, output)
        self.assertIn("No response plans found", output[0])

    def test_empty_pinned_list_still_warns(self):
        from azext_sre.custom import AutomationScheduledTaskList
        output = self._run(_bare_command(AutomationScheduledTaskList, agent_name="a", resource_group="rg"))
        self.assertEqual(len(output), 1, output)
        self.assertIn("scheduledTasks", output[0])


class HttpTriggerInvokeTests(unittest.TestCase):

    def _invoke(self, value, payload=None):
        from azext_sre.custom import AutomationHttpTriggerInvoke

        command = _bare_command(AutomationHttpTriggerInvoke, agent_name="a", resource_group="rg",
                                extension_name="hook", payload=payload)
        response = SimpleNamespace(content=b"{}", json=lambda: {"success": True, "threadId": "t1"})
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show",
                   return_value={"name": "hook", "properties": {"value": value}}), \
             patch("azext_sre.custom.send_raw_request", return_value=response) as send:
            return command._handler({}), send

    def test_posts_the_payload_to_the_trigger_url_with_the_agent_audience(self):
        url = "https://a--1.x.swedencentral.azuresre.ai/api/v1/httptriggers/trigger/hook"
        result, send = self._invoke({"triggerUrl": url, "triggerEnabled": True}, payload='{"alert": "x"}')
        self.assertEqual(result["threadId"], "t1")
        args, kwargs = send.call_args
        self.assertEqual(args[1:3], ("POST", url))
        self.assertEqual(kwargs["body"], '{"alert": "x"}')
        self.assertEqual(kwargs["resource"], "https://azuresre.dev")

    def test_refuses_unexpected_hosts_and_bad_payloads(self):
        with self.assertRaisesRegex(CLIError, "unexpected"):
            self._invoke({"triggerUrl": "https://evil.example.com/hook"})
        with self.assertRaisesRegex(CLIError, "JSON"):
            self._invoke({"triggerUrl": "https://a.azuresre.ai/hook"}, payload="not json")
        for url in ("https://attacker.example\\@a.swedencentral.azuresre.ai/api/v1/httptriggers/trigger/hook",
                    "https://attacker.example\\.azuresre.ai/hook",
                    "https://user@attacker.example@a.azuresre.ai/hook",
                    "http://a.azuresre.ai/hook"):
            with self.assertRaisesRegex(CLIError, "unexpected"):
                self._invoke({"triggerUrl": url})


class ValueNotAnObjectTests(unittest.TestCase):
    """Azure CLI's error line doesn't name the command, so each kind of
    --value needs its own message to be told apart in a script's log."""

    def test_each_kind_of_value_has_its_own_message(self):
        messages = {}
        for extension_type in EXTENSION_VALUE_VALIDATORS:
            with self.assertRaises(CLIError) as raised:
                _encode_extension_value("[]", extension_type)
            messages[extension_type] = str(raised.exception)
        self.assertEqual(len(set(messages.values())), len(messages), messages)


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


class HttpToolCreationPolicyTests(unittest.TestCase):
    """Exercise tool commands against persisted ARM envelopes, without Azure calls."""

    _AGENT_ID = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"
    _TOOL_ID = f"{_AGENT_ID}/tools/mytool"
    _HTTP_TOOL = {
        "type": "HttpClientTool",
        "description": "Call a read-only API",
        "url": "https://example.com/{{id}}",
        "method": "GET",
        "headers": [{"key": "Accept", "value": "application/json"}],
        "parameters": [{"name": "id", "type": "string", "required": True}],
        "auth": {"dataconnector": "api-connector", "scope": "https://example.com/.default"},
        "timeout_seconds": 30,
    }
    _SUPPORTED_TOOLS = (
        {"type": "LinkTool", "template": "https://example.com/docs"},
        {"type": "KustoTool", "connector": "kusto", "database": "db", "query": "Table | take 1"},
        {"type": "PythonFunctionTool", "functionCode": "def main():\n    return {'status': 200}\n"},
    )

    def setUp(self):
        self.resources = {}
        self.puts = []
        self.read_error = None

    def _seed(self, value):
        self.resources[self._TOOL_ID] = {
            "id": self._TOOL_ID,
            "type": "microsoft.app/agents/tools",
            "properties": {"value": base64.b64encode(json.dumps(value).encode("utf-8")).decode("ascii")},
        }

    def _arm_request(self, cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
        if method == "GET":
            if self.read_error is not None:
                raise self.read_error
            if resource_id == f"{self._AGENT_ID}/tools":
                return {"value": copy.deepcopy(list(self.resources.values()))}
            return copy.deepcopy(self.resources.get(resource_id))
        if method == "PUT":
            self.puts.append({"resource_id": resource_id, "body": copy.deepcopy(body)})
            self.resources[resource_id] = {"id": resource_id, **copy.deepcopy(body)}
            return copy.deepcopy(self.resources[resource_id])
        self.fail(f"Unexpected ARM method: {method}")

    def _invoke(self, command_cls, **args):
        command = _bare_command(command_cls, agent_name="myagent", resource_group="rg", **args)
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", return_value={"id": self._AGENT_ID}), \
             patch("azext_sre.custom._arm_request", self._arm_request):
            return command._handler({})

    def _create(self, value, overwrite=False):
        return self._invoke(
            ToolCreate, extension_name="mytool", value=json.dumps(value), overwrite=overwrite,
        )

    def test_rejects_new_http_tool_with_and_without_overwrite(self):
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                self.resources.clear()
                self.puts.clear()
                with self.assertRaises(CLIError) as raised:
                    self._create(self._HTTP_TOOL, overwrite=overwrite)
                message = str(raised.exception)
                self.assertIn("Creating new HttpClientTool tools is no longer supported", message)
                self.assertIn("--overwrite", message)
                self.assertIn("PythonFunctionTool", message)
                self.assertIn("MCP", message)
                self.assertEqual(self.resources, {})
                self.assertEqual(self.puts, [])

    def test_overwrite_cannot_replace_another_tool_type_with_http(self):
        for tool in self._SUPPORTED_TOOLS:
            with self.subTest(existing_type=tool["type"]):
                self.puts.clear()
                self._seed(tool)
                before = copy.deepcopy(self.resources)
                with self.assertRaises(CLIError):
                    self._create(self._HTTP_TOOL, overwrite=True)
                self.assertEqual(self.resources, before)
                self.assertEqual(self.puts, [])

    def test_existing_name_still_requires_intentional_overwrite(self):
        for tool in (self._HTTP_TOOL, *self._SUPPORTED_TOOLS):
            with self.subTest(existing_type=tool["type"]):
                self._seed(tool)
                before = copy.deepcopy(self.resources)
                with self.assertRaises(ResourceExistsError) as raised:
                    self._create(self._HTTP_TOOL)
                self.assertIn("--overwrite", str(raised.exception))
                self.assertEqual(self.resources, before)
                self.assertEqual(self.puts, [])

    def test_existing_http_tool_can_be_updated_without_converting_its_payload(self):
        self._seed({"type": "HttpClientTool", "url": "https://example.com/old", "method": "GET"})
        self._create(self._HTTP_TOOL, overwrite=True)
        self.assertEqual(set(self.resources), {self._TOOL_ID})
        persisted = self.resources[self._TOOL_ID]
        self.assertEqual(persisted["type"], "microsoft.app/agents/tools")
        self.assertEqual(json.loads(base64.b64decode(persisted["properties"]["value"])), self._HTTP_TOOL)

    def test_unrecognized_existing_payload_does_not_authorize_http_creation(self):
        for value in (None, [], {}, {"type": "UnknownTool"}):
            with self.subTest(existing_value=value):
                self.puts.clear()
                self._seed(value)
                before = copy.deepcopy(self.resources)
                with self.assertRaises(CLIError):
                    self._create(self._HTTP_TOOL, overwrite=True)
                self.assertEqual(self.resources, before)
                self.assertEqual(self.puts, [])

    def test_undecodable_existing_payload_does_not_authorize_http_creation(self):
        self.resources[self._TOOL_ID] = {"properties": {"value": "not a valid encoded tool"}}
        before = copy.deepcopy(self.resources)
        with self.assertRaises(CLIError):
            self._create(self._HTTP_TOOL, overwrite=True)
        self.assertEqual(self.resources, before)
        self.assertEqual(self.puts, [])

    def test_http_tools_remain_readable_by_show_and_list(self):
        self._seed(self._HTTP_TOOL)
        before = copy.deepcopy(self.resources)
        shown = self._invoke(ToolShow, extension_name="mytool")
        listed = self._invoke(ToolList)
        self.assertEqual(shown["properties"]["value"], self._HTTP_TOOL)
        self.assertEqual(listed[0]["properties"]["value"], self._HTTP_TOOL)
        self.assertEqual(self.resources, before)
        self.assertEqual(self.puts, [])

    def test_supported_tools_can_still_be_created(self):
        for tool in self._SUPPORTED_TOOLS:
            with self.subTest(tool_type=tool["type"]):
                self.resources.clear()
                self._create(tool)
                persisted = self.resources[self._TOOL_ID]
                self.assertEqual(json.loads(base64.b64decode(persisted["properties"]["value"])), tool)

    def test_supported_overwrite_does_not_require_a_tool_lookup(self):
        self.read_error = CLIError("Tool lookup denied")
        for tool in self._SUPPORTED_TOOLS:
            with self.subTest(tool_type=tool["type"]):
                self._seed(self._HTTP_TOOL)
                self._create(tool, overwrite=True)
                persisted = self.resources[self._TOOL_ID]
                self.assertEqual(json.loads(base64.b64decode(persisted["properties"]["value"])), tool)

    def test_http_lookup_errors_propagate_without_mutation(self):
        self._seed(self._HTTP_TOOL)
        before = copy.deepcopy(self.resources)
        self.read_error = CLIError("Tool lookup denied")
        with self.assertRaises(CLIError) as raised:
            self._create(self._HTTP_TOOL, overwrite=True)
        self.assertIs(raised.exception, self.read_error)
        self.assertEqual(self.resources, before)
        self.assertEqual(self.puts, [])

    def test_legacy_http_update_still_validates_the_payload(self):
        self._seed(self._HTTP_TOOL)
        before = copy.deepcopy(self.resources)
        with self.assertRaises(CLIError) as raised:
            self._create({**self._HTTP_TOOL, "headers": {"Accept": "application/json"}}, overwrite=True)
        self.assertIn("--value.headers", str(raised.exception))
        self.assertEqual(self.resources, before)
        self.assertEqual(self.puts, [])


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
                          args_kwargs, fake_result=None, expected_result=None, lookup=False):
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
        lookups = 0
        if lookup:
            # Deletes look the item up first, with the same pinned type and name.
            self.assertEqual(calls["show"], [("myagent", "rg", extension_type, call_args[0], {})])
            lookups = 1
        self.assertEqual(sum(len(v) for v in calls.values()), 1 + lookups)
        self.assertEqual(result, fake_result if expected_result is None else expected_result)

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
            fake_result={"value": [{"name": "app-investigator"}]},
            expected_result=[{"name": "app-investigator"}],
        )

    def test_skill_list_returns_a_bare_array(self):
        self._assert_forwards(
            SkillList, "skills",
            ("list", ({},)),
            {"agent_name": "myagent", "resource_group": "rg"},
            fake_result={"value": [{"name": "triage"}]},
            expected_result=[{"name": "triage"}],
        )

    def test_subagent_delete_pins_extension_type_subagents(self):
        self._assert_forwards(
            SubagentDelete, "subagents",
            ("delete", ("app-investigator", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "app-investigator"},
            lookup=True,
        )

    def test_hook_list_pins_extension_type_hooks(self):
        self._assert_forwards(
            HookList, "hooks",
            ("list", ({},)),
            {"agent_name": "myagent", "resource_group": "rg"},
            fake_result={"value": []},
            expected_result=[],
        )

    def test_hook_delete_prints_nothing(self):
        command = _bare_command(HookDelete, agent_name="myagent", resource_group="rg", extension_name="h")
        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._extension_resource_show", return_value={"name": "h"}), \
             patch("azext_sre.custom._extension_resource_delete", return_value={}) as delete:
            self.assertIsNone(command._handler({}))
        delete.assert_called_once()

    def test_instructions_delete_pins_extension_type_common_prompts(self):
        self._assert_forwards(
            InstructionsDelete, "commonPrompts",
            ("delete", ("default", {})),
            {"agent_name": "myagent", "resource_group": "rg", "extension_name": "default"},
            lookup=True,
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


class EmptyListWarningTests(unittest.TestCase):
    """A list command on an agent with nothing to list prints one warning,
    whichever API answers. 'response-plan list' prints its own, so the shared
    list helper must not add another."""

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def test_each_list_command_warns_once(self):
        from azext_sre.custom import ResponsePlanList
        for command_cls, extra_args in ((ResponsePlanList, {"agent_url": None}), (ToolList, {})):
            for route in ("arm", "direct"):
                with self.subTest(command=command_cls.__name__, route=route):
                    command = _bare_command(command_cls, agent_name="myagent", resource_group="rg", **extra_args)
                    with patch.dict(os.environ, {"AZSRE_EXTENSION_ROUTE": route}), \
                         patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
                         patch("azext_sre.custom._cli_invoke", return_value=self._AGENT), \
                         patch("azext_sre.custom._arm_request", return_value={"value": []}), \
                         patch("azext_sre.custom._data_plane_request", return_value={"value": []}), \
                         self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
                        command._handler(None)
                    self.assertEqual(len(logs.output), 1, logs.output)


class DeleteOfMissingItemTests(unittest.TestCase):
    """Deleting something that doesn't exist fails with ResourceNotFoundError
    (exit code 3) instead of reporting success, so each delete looks the item
    up first."""

    _AGENT_ID = "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/agents/myagent"

    def setUp(self):
        self.arm = {}
        self.agent_api = {}
        for replacement in (
            patch.object(AAZCommand, "_handler", lambda command, command_args: None),
            patch("azext_sre.custom._cli_invoke", return_value={"id": self._AGENT_ID}),
            patch("azext_sre.custom._arm_request", side_effect=(
                lambda cli_ctx, method, resource_id, api_version, body=None, missing_ok=False:
                self._answer(self.arm, method, resource_id, missing_ok))),
            patch("azext_sre.custom._data_plane_request", side_effect=(
                lambda cli_ctx, agent, group, method, path, body=None, missing_ok=False, agent_url=None:
                self._answer(self.agent_api, method, path, missing_ok))),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    @staticmethod
    def _answer(store, method, key, missing_ok):
        if method == "DELETE":
            store.pop(key, None)
            return {}
        if key in store:
            return store[key]
        if missing_ok:
            return None
        raise AssertionError(f"Unexpected {method} {key}")

    def _command(self, command_cls, **args):
        command = _bare_command(command_cls, agent_name="myagent", resource_group="rg", **args)
        command.ctx.subscription_id = "sub"
        command.callbacks = {}
        return command

    def test_extension_delete_on_either_route(self):
        for route, store, key in (
            ("arm", self.arm, f"{self._AGENT_ID}/tools/docs-link"),
            ("direct", self.agent_api, "/api/v2/extendedAgent/tools/docs-link"),
        ):
            with self.subTest(route=route), patch.dict(os.environ, {"AZSRE_EXTENSION_ROUTE": route}):
                with self.assertRaises(ResourceNotFoundError):
                    self._command(ToolDelete, extension_name="docs-link")._handler(None)
                store[key] = {"name": "docs-link", "properties": {}}
                self.assertIsNone(self._command(ToolDelete, extension_name="docs-link")._handler(None))
                self.assertNotIn(key, store)

    def test_agent_and_connector_delete_look_the_resource_up_first(self):
        from azext_sre.custom import ConnectorDelete, Delete as AgentDelete
        for command_cls, args, resource_id in (
            (AgentDelete, {}, self._AGENT_ID),
            (ConnectorDelete, {"connector_name": "conn"}, f"{self._AGENT_ID}/connectors/conn"),
        ):
            with self.subTest(command=command_cls.__name__):
                command = self._command(command_cls, **args)
                with self.assertRaises(ResourceNotFoundError):
                    command.pre_operations()
                self.arm[resource_id] = {"id": resource_id}
                command.pre_operations()


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
        command.ctx.subscription_id = "sub"
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
        with patch("azext_sre.custom._arm_request", return_value={"name": "docs"}):
            _, calls = self._run(
                KnowledgeDelete, agent_name="myagent", resource_group="rg", name="docs",
            )
        self.assertEqual(
            calls[0],
            ("sre", "connector", "delete", "--agent-name", "myagent", "--resource-group", "rg", "--name", "docs", "--yes"),
        )

    def test_delete_of_a_missing_knowledge_source_is_not_found(self):
        with patch("azext_sre.custom._arm_request", return_value=None), \
             self.assertRaises(ResourceNotFoundError):
            self._run(KnowledgeDelete, agent_name="myagent", resource_group="rg", name="docs")

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
    """UpdateNetwork PATCHes only the networking properties at
    NETWORK_API_VERSION, so nothing else on the agent is written back.
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

    def test_patches_only_networking_properties_on_app_insights_agent(self):
        command = _bare_command(
            UpdateNetwork,
            name="myagent", resource_group="rg",
            vnet_configuration=None,
            sandbox_configuration={"egress": {"mode": "Limited"}},
        )
        # Reads redact the connection string; writing this back fails with
        # InvalidApplicationInsightsConfiguration.
        current = {
            "id": self._AGENT["id"],
            "properties": {
                "displayName": "keep-me", "provisioningState": "Succeeded",
                "logConfiguration": {"applicationInsightsConfiguration": {
                    "appId": "app-id", "connectionString": None}},
            },
        }
        arm_calls = []

        def fake_cli_invoke(cli_ctx, *args, allow_missing=False):
            return self._AGENT

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            arm_calls.append({"method": method, "body": body, "api_version": api_version})
            if method == "PATCH":
                return {**current, "properties": {**current["properties"], **body["properties"]}}
            return current

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})

        self.assertEqual(arm_calls, [{
            "method": "PATCH", "api_version": "2026-11-01-preview",
            "body": {"properties": {"sandboxConfiguration": {"egress": {"mode": "Limited"}}}},
        }])
        # Result is trimmed to the networking-relevant fields.
        self.assertEqual(result["id"], self._AGENT["id"])
        self.assertEqual(result["provisioningState"], "Succeeded")
        self.assertEqual(result["sandboxConfiguration"], {"egress": {"mode": "Limited"}})
        self.assertNotIn("displayName", result)

    def test_reads_the_agent_back_when_patch_returns_no_body(self):
        command = _bare_command(
            UpdateNetwork,
            name="myagent", resource_group="rg",
            vnet_configuration={"subnet_resource_id": "/subnets/s"}, sandbox_configuration=None,
        )
        current = {"id": self._AGENT["id"], "properties": {"vnetConfiguration": {"subnetResourceId": "/subnets/s"}}}
        methods = []

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            methods.append(method)
            return {} if method == "PATCH" else current

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", lambda *a, **k: self._AGENT), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})

        self.assertEqual(methods, ["PATCH", "GET"])
        self.assertEqual(result["vnetConfiguration"], {"subnetResourceId": "/subnets/s"})


class NetworkUpdateCliTests(unittest.TestCase):
    """Runs `network update` through the real Azure CLI parser, loading the
    extension from source so CI doesn't need it installed."""

    _AGENT = {"id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"}

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
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
            "requests.sessions.Session.request",
            side_effect=AssertionError("This test must not use the network."),
        ))

    def test_accepts_network_show_output_with_nulls(self):
        # Shape of `network show --query sandboxConfiguration` on a new agent.
        shown = {
            "egress": {
                "mode": "Limited", "allowedHosts": ["a.example.com"],
                "allowedRegistries": ["pypi"], "allowHttpMcpServerNetworkAccess": True,
                "httpProxy": None, "vnetConfiguration": None,
            },
            "packages": None,
        }
        patches = []

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            if method == "PATCH":
                patches.append(body)
                return {"id": self._AGENT["id"], **body}
            return {"id": self._AGENT["id"], "properties": {}}

        with patch("azext_sre.custom._cli_invoke", lambda *a, **k: self._AGENT), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            try:
                code = get_default_cli().invoke([
                    "sre", "network", "update", "-g", "rg", "-n", "myagent",
                    "--sandbox-configuration", json.dumps(shown), "-o", "none",
                ], out_file=io.StringIO())
            except SystemExit as ex:
                code = ex.code

        self.assertEqual(code, 0)
        self.assertEqual(patches[0]["properties"]["sandboxConfiguration"], {
            "egress": {
                "mode": "Limited", "allowedHosts": ["a.example.com"],
                "allowedRegistries": ["pypi"], "allowHttpMcpServerNetworkAccess": True,
            },
        })

class ExperimentalSettingsOnCreateTests(unittest.TestCase):

    class _Base:
        def pre_operations(self):
            pass

        def post_operations(self):
            pass

    class _Command(_ExperimentalSettingsOnCreateMixin, _Base):
        pass

    def _command(self, **args):
        cmd = self._Command()
        cmd.cli_ctx = object()
        cmd.ctx = SimpleNamespace(subscription_id="sub", args=SimpleNamespace(
            resource_group="rg", agent_name="myagent", **args))
        return cmd

    def test_settings_are_patched_after_create(self):
        cmd = self._command(experimental_settings={"EnableWorkspaceTools": True}, no_wait=False)
        cmd.pre_operations()
        with patch("azext_sre.custom._arm_request") as arm:
            cmd.post_operations()
        arm.assert_called_once_with(
            cmd.cli_ctx, "PATCH", "/subscriptions/sub/resourceGroups/rg/providers/Microsoft.App/agents/myagent",
            ANY, body={"properties": {"experimentalSettings": {"EnableWorkspaceTools": True}}})

    def test_no_request_without_settings_and_no_wait_is_rejected(self):
        with patch("azext_sre.custom._arm_request") as arm:
            self._command(experimental_settings=None, no_wait=False).post_operations()
        arm.assert_not_called()
        with self.assertRaisesRegex(CLIError, "--no-wait"):
            self._command(experimental_settings={"A": True}, no_wait=True).pre_operations()

    def test_monthly_unit_limit_is_patched_after_create(self):
        cmd = self._command(experimental_settings=None, monthly_unit_limit=1000, no_wait=False)
        cmd.pre_operations()
        with patch("azext_sre.custom._arm_request") as arm:
            cmd.post_operations()
        self.assertEqual(arm.call_args.kwargs["body"], {"properties": {"monthlyAgentUnitLimit": 1000}})
        with self.assertRaisesRegex(CLIError, "negative"):
            self._command(experimental_settings=None, monthly_unit_limit=-1, no_wait=False).pre_operations()


class AgentUpdateCliTests(unittest.TestCase):
    """Runs `agent update` through the real CLI with ARM faked at the HTTP layer."""

    _ID = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.App/agents/myagent"

    def setUp(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        config_dir = stack.enter_context(tempfile.TemporaryDirectory())
        stack.enter_context(patch.dict(os.environ, {
            "AZURE_CONFIG_DIR": config_dir,
            "AZURE_CORE_COLLECT_TELEMETRY": "no",
            "AZURE_CORE_USE_COMMAND_INDEX": "no",
            "AZURE_EXTENSION_USE_DYNAMIC_INSTALL": "no",
        }))
        stack.enter_context(patch("azure.cli.core._config.GLOBAL_CONFIG_DIR", config_dir))
        extension = DevExtension("sre", str(Path(__file__).resolve().parents[3]))
        stack.enter_context(patch.object(extension, "get_metadata", return_value={"version": "1.0.0b1"}))
        stack.enter_context(patch("azure.cli.core.extension.get_extensions", return_value=[extension]))
        stack.enter_context(patch("azure.cli.core.MainCommandsLoader._load_modules", return_value=[]))
        stack.enter_context(patch("azure.cli.core.util.handle_version_update"))
        stack.enter_context(patch("azure.cli.core.util.show_updates_available"))
        token = SimpleNamespace(token="t", expires_on=4102444800)
        credential = SimpleNamespace(get_token=lambda *a, **k: token, get_token_info=lambda *a, **k: token)
        stack.enter_context(patch(
            "azure.cli.core.aaz._command_ctx.AAZCommandCtx.get_login_credential", return_value=credential))
        stack.enter_context(patch(
            "azure.cli.core.commands.client_factory.get_subscription_id",
            return_value="00000000-0000-0000-0000-000000000000"))
        self.requests = []
        self.agent = {
            "id": self._ID, "name": "myagent", "location": "swedencentral", "tags": {},
            "identity": {"type": "SystemAssigned"},
            "properties": {
                "provisioningState": "Succeeded", "upgradeChannel": "Stable",
                "logConfiguration": {"applicationInsightsConfiguration": {
                    "appId": "app-id", "connectionString": None}},
            },
        }
        stack.enter_context(patch("requests.sessions.Session.request", self._fake_request))

    def _fake_request(self, method, url, data=None, **kwargs):
        body = json.loads(data) if data else None
        self.requests.append((method, body))
        if method in ("PUT", "PATCH"):
            app_insights = ((body.get("properties") or {}).get("logConfiguration") or {}).get(
                "applicationInsightsConfiguration")
            if app_insights and not app_insights.get("connectionString"):
                return self._response(400, {"error": {
                    "code": "InvalidApplicationInsightsConfiguration",
                    "message": "The AppId and ConnectionString fields must be provided together."}}, url)
            self.agent["tags"] = body.get("tags", self.agent["tags"])
        return self._response(200, self.agent, url)

    @staticmethod
    def _response(status, payload, url):
        response = Response()
        response.status_code = status
        response._content = json.dumps(payload).encode()
        response.raw = io.BytesIO(response._content)
        response.headers["Content-Type"] = "application/json"
        response.url = url
        response.request = SimpleNamespace(method="GET", url=url, headers={})
        return response

    def _invoke(self, *arguments):
        errors = io.StringIO()
        try:
            from contextlib import redirect_stderr
            with redirect_stderr(errors):
                code = get_default_cli().invoke([
                    "sre", "agent", "update", "-g", "rg", "-n", "myagent", *arguments, "-o", "none",
                ], out_file=io.StringIO())
        except SystemExit as ex:
            code = ex.code
        return code, errors.getvalue()

    def test_update_on_app_insights_agent_patches_without_the_redacted_link(self):
        code, errors = self._invoke("--tags", "env=test")
        self.assertEqual(code, 0, errors)
        method, body = self.requests[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(body["tags"], {"env": "test"})
        self.assertNotIn("logConfiguration", body["properties"])

    def test_new_log_configuration_is_sent_with_a_put(self):
        code, errors = self._invoke(
            "--log-configuration", "{application-insights-configuration:{app-id:new,connection-string:cs}}")
        self.assertEqual(code, 0, errors)
        method, body = self.requests[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(body["properties"]["logConfiguration"], {
            "applicationInsightsConfiguration": {"appId": "new", "connectionString": "cs"}})

    def test_experimental_settings_are_patched_in(self):
        del self.agent["properties"]["logConfiguration"]
        code, errors = self._invoke("--experimental-settings", '{"EnableWorkspaceTools": true}')
        self.assertEqual(code, 0, errors)
        method, body = self.requests[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(body["properties"]["experimentalSettings"], {"EnableWorkspaceTools": True})

    def test_monthly_unit_limit_is_patched_in(self):
        del self.agent["properties"]["logConfiguration"]
        code, errors = self._invoke("--monthly-unit-limit", "2000")
        self.assertEqual(code, 0, errors)
        method, body = self.requests[-1]
        self.assertEqual(method, "PATCH")
        self.assertEqual(body["properties"]["monthlyAgentUnitLimit"], 2000)

    def test_put_keeps_the_existing_monthly_unit_limit(self):
        del self.agent["properties"]["logConfiguration"]
        self.agent["properties"]["monthlyAgentUnitLimit"] = 700
        code, errors = self._invoke("--tags", "env=test")
        self.assertEqual(code, 0, errors)
        method, body = self.requests[-1]
        self.assertEqual(method, "PUT")
        self.assertEqual(body["properties"]["monthlyAgentUnitLimit"], 700)


class ShowNetworkTests(unittest.TestCase):
    _ID = "/subscriptions/x/resourceGroups/rg/providers/Microsoft.App/agents/myagent"

    def test_reads_at_networking_api_version_and_trims(self):
        command = _bare_command(ShowNetwork, name="myagent", resource_group="rg")
        calls = []

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            calls.append((method, resource_id, api_version))
            return {"id": self._ID, "name": "myagent", "properties": {
                "displayName": "hide-me", "provisioningState": "Succeeded",
                "sandboxConfiguration": {"egress": {"mode": "Limited"}}}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._resolve_agent_resource_id", lambda *a, **k: self._ID), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            result = command._handler({})

        self.assertEqual(calls, [("GET", self._ID, "2026-11-01-preview")])
        self.assertEqual(result["sandboxConfiguration"], {"egress": {"mode": "Limited"}})
        self.assertIsNone(result["vnetConfiguration"])
        # The live ARM response has no resourceGroup field; it comes from the ID.
        self.assertEqual(result["resourceGroup"], "rg")
        self.assertNotIn("displayName", result)

    def test_missing_agent_raises(self):
        command = _bare_command(ShowNetwork, name="myagent", resource_group="rg")

        def fake_arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
            if not missing_ok:
                raise AssertionError("a 404 must be tolerated with missing_ok=True")
            return None

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._resolve_agent_resource_id", lambda *a, **k: self._ID), \
             patch("azext_sre.custom._arm_request", fake_arm_request):
            with self.assertRaises(ResourceNotFoundError):
                command._handler({})

    def test_404_on_the_get_becomes_not_found(self):
        command = _bare_command(ShowNetwork, name="myagent", resource_group="rg")

        class Http404(Exception):
            response = type("R", (), {"status_code": 404})()

        def raise_404(*args, **kwargs):
            raise Http404()

        command.cli_ctx.cloud = types.SimpleNamespace(
            endpoints=types.SimpleNamespace(resource_manager="https://management.azure.com/"))

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._resolve_agent_resource_id", lambda *a, **k: self._ID), \
             patch("azext_sre.custom.send_raw_request", raise_404):
            with self.assertRaises(ResourceNotFoundError):
                command._handler({})


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
            "sre access grant", "sre access revoke", "sre network update", "sre network show",
            "sre connector create", "sre connector show", "sre connector list",
            "sre connector update", "sre connector delete", "sre connector list-secret",
            "sre identity assign", "sre identity remove", "sre identity show",
            "sre agent list-models", "sre version",
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
        must stay gone, not silently reappear if the generator config in
        scripts/generate_sre_extension.py is ever changed. 'sre extension ...' was
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


class GeneratedCommandNamingTests(unittest.TestCase):
    """The generated aaz package is produced directly with the final 'sre'
    names (scripts/generate_sre_extension.py); nothing is renamed at load
    time, so no 'app ...' command, group or help entry may exist."""

    @classmethod
    def setUpClass(cls):
        from knack.help_files import helps

        cls.loader = SreCommandsLoader(cli_ctx=DummyCli())
        cls.command_table = cls.loader.load_command_table(None)
        cls.helps = dict(helps)

    def test_no_app_commands_groups_or_help_entries(self):
        def is_app(name):
            return name == "app" or name.startswith("app ")

        self.assertEqual([n for n in self.command_table if is_app(n)], [])
        self.assertEqual([n for n in self.loader.command_group_table if is_app(n)], [])
        self.assertEqual([n for n in self.helps if is_app(n)], [])

    def test_generated_package_is_aaz_latest_sre(self):
        from azext_sre import aaz
        from azext_sre.aaz.latest import sre as generated_sre

        self.assertEqual(generated_sre.__name__, "azext_sre.aaz.latest.sre")
        latest_dir = os.path.dirname(aaz.latest.__file__)
        packages = sorted(
            name for name in os.listdir(latest_dir)
            if os.path.isfile(os.path.join(latest_dir, name, "__init__.py"))
        )
        self.assertEqual(packages, ["sre"])
        for base in (IdentityAssign, SupportedAgentModelList):
            generated = base.__mro__[1]
            self.assertTrue(generated.__module__.startswith("azext_sre.aaz.latest.sre."))
            self.assertEqual(generated.AZ_NAME, base.AZ_NAME)

    def test_custom_hooks_find_their_generated_arguments(self):
        # custom.py reads these by name with getattr(..., None); a regeneration that renames
        # one would otherwise silently disable the hook.
        from azext_sre import custom

        connector_args = ["data_connector_type", "data_source", "endpoint", "identity",
                          "extended_properties", "connector_name"]
        for command, paths in (
            (custom.Create, ["incident_management_configuration.type", "knowledge_graph_configuration",
                             "default_model.provider", "action_configuration.mode", "mi_system_assigned",
                             "mi_user_assigned", "log_configuration"]),
            (custom.Update, ["incident_management_configuration.type", "knowledge_graph_configuration",
                             "default_model.provider", "action_configuration.mode"]),
            (custom.ConnectorCreate, connector_args),
            (custom.ConnectorUpdate, connector_args),
        ):
            schema = command._build_arguments_schema()
            for path in paths:
                with self.subTest(command=command.AZ_NAME, argument=path):
                    node = schema
                    for part in path.split("."):
                        node = getattr(node, part)

    def test_generated_only_commands_have_help(self):
        for name, command in self.command_table.items():
            if type(command).__module__.startswith("azext_sre.aaz."):
                self.assertTrue(command.help and command.help.get("short-summary"), name)


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
        self.assertIn("Azure Data Explorer", cmd_arg.type.settings.get("help"))

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


class InternalFeatureHelpVisibilityTests(unittest.TestCase):
    """Help hides Microsoft-internal options for non-Microsoft tenants, like the portal."""

    def test_listed_connector_types_match_portal_picker(self):
        with patch("azext_sre.custom._show_internal_features", return_value=False):
            third_party = _listed_connector_types()
        with patch("azext_sre.custom._show_internal_features", return_value=True):
            internal = _listed_connector_types()
        for hidden in ("Icm", "Dgrep", "GenevaMetrics", "S360"):
            self.assertNotIn(hidden, third_party)
            self.assertIn(hidden, internal)
        for unlisted in ("Kusto", "Documentation", "KnowledgeText", "Outlook", "Teams"):
            self.assertNotIn(unlisted, internal)
        self.assertIn("MonitorClient", third_party)
        self.assertEqual(_normalize_data_connector_type(PORTAL_CONNECTOR_NAMES["MonitorClient"]), "MonitorClient")
        for retired in ("KustoDataIndexer", "TsgCrawler"):
            self.assertNotIn(retired, third_party)
            self.assertNotIn(retired, internal)
            self.assertEqual(
                _normalize_data_connector_type(PORTAL_CONNECTOR_NAMES[retired]), retired)

    def _visible_with_profile(self, profile):
        with tempfile.TemporaryDirectory() as config_dir:
            if profile is not None:
                with open(os.path.join(config_dir, "azureProfile.json"), "w", encoding="utf-8") as f:
                    f.write(profile if isinstance(profile, str) else json.dumps(profile))
            old = os.environ.get("AZURE_CONFIG_DIR")
            os.environ["AZURE_CONFIG_DIR"] = config_dir
            try:
                return _show_internal_features()
            finally:
                if old is None:
                    del os.environ["AZURE_CONFIG_DIR"]
                else:
                    os.environ["AZURE_CONFIG_DIR"] = old

    @staticmethod
    def _profile(tenant_id):
        return {"subscriptions": [
            {"id": "other", "tenantId": "11111111-1111-1111-1111-111111111111", "isDefault": False},
            {"id": "sub", "tenantId": tenant_id, "isDefault": True},
        ]}

    def test_hidden_for_non_microsoft_tenant(self):
        self.assertFalse(self._visible_with_profile(self._profile("e0a62563-74af-4081-8ae3-fb94b692e394")))

    def test_shown_for_microsoft_and_sovereign_tenants(self):
        self.assertTrue(self._visible_with_profile(self._profile("72f988bf-86f1-41af-91ab-2d7cd011db47")))
        self.assertTrue(self._visible_with_profile(self._profile("70a90262-f46c-48aa-ac4c-37e37f8be1a2")))

    def test_shown_when_tenant_unknown(self):
        self.assertTrue(self._visible_with_profile(None))
        self.assertTrue(self._visible_with_profile("not json"))
        self.assertTrue(self._visible_with_profile({"subscriptions": []}))


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


class ConnectorPartnerTypeTests(unittest.TestCase):

    class _Base:
        def pre_operations(self):
            pass

        def post_instance_update(self, instance):
            pass

    class _Command(_ConnectorPartnerTypeMixin, _Base):
        pass

    def test_partner_type_is_merged_into_extended_properties_on_create(self):
        command = _bare_command(self._Command, data_connector_type="Mcp", partner_type="DynatraceMcp",
                                extended_properties={"authType": "BearerToken"})
        command.pre_operations()
        self.assertEqual(command.ctx.args.extended_properties,
                         {"authType": "BearerToken", "partnerType": "DynatraceMcp"})
        with self.assertRaisesRegex(CLIError, "Mcp"):
            _bare_command(self._Command, data_connector_type="Kusto", partner_type="DynatraceMcp",
                          extended_properties=None).pre_operations()

    def test_partner_type_is_set_on_the_existing_connector_on_update(self):
        command = _bare_command(self._Command, partner_type="DynatraceMcp")
        extended = {"endpoint": "https://x"}
        instance = SimpleNamespace(properties=SimpleNamespace(
            data_connector_type=SimpleNamespace(to_serialized_data=lambda: "Mcp"), extended_properties=extended))
        command.post_instance_update(instance)
        self.assertEqual(extended, {"endpoint": "https://x", "partnerType": "DynatraceMcp"})

    def test_partner_type_on_update_requires_the_full_connector_definition(self):
        from azext_sre.custom import _GeneratedConnectorUpdate

        class _Update(_ConnectorPartnerTypeMixin, _GeneratedConnectorUpdate):
            pass

        with patch.object(_GeneratedConnectorUpdate, "pre_operations", lambda self: None):
            with self.assertRaisesRegex(CLIError, "--data-source and --extended-properties"):
                _bare_command(_Update, partner_type="DynatraceMcp", data_connector_type=None,
                              data_source=None, extended_properties=None).pre_operations()
            _bare_command(_Update, partner_type="DynatraceMcp", data_connector_type=None,
                          data_source="https://x", extended_properties={"endpoint": "https://x"}).pre_operations()


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

    def test_http_logging_is_disabled_for_the_secret_request(self):
        operation = ConnectorListSecret.AgentsConnectorsListSecrets.__new__(
            ConnectorListSecret.AgentsConnectorsListSecrets
        )
        seen = {}
        parent = ConnectorListSecret.AgentsConnectorsListSecrets.__mro__[2]
        with patch.object(
            parent, "__call__", lambda self, *a, **kw: seen.update(kw) or "ok"
        ):
            self.assertEqual(operation(logging_enable=True), "ok")
        self.assertIs(seen["logging_enable"], False)

    def test_connector_create_and_update_writes_disable_tracing(self):
        for command in (ConnectorCreate, ConnectorUpdate):
            operation_class = command.AgentsConnectorsCreateOrUpdate
            operation = operation_class.__new__(operation_class)
            seen = {}
            parent = operation_class.__bases__[1]
            with patch.object(
                parent, "__call__", lambda self, *a, **kw: seen.update(kw) or "ok"
            ):
                operation(logging_enable=True)
            self.assertIs(seen["logging_enable"], False, command.__name__)

    def test_extension_create_silences_http_trace(self):
        import logging

        from azext_sre import custom

        logger = logging.getLogger("cli.azure.cli.core.util")
        levels = []
        with patch.object(
            custom, "_with_direct_fallback", lambda *a, **kw: levels.append(logger.level) or "ok"
        ):
            custom._extension_resource_create(None, "a", "rg", "pluginMarketplaces", "m", "{}")
        self.assertEqual(levels, [logging.CRITICAL])


class IdentityAndSupportedAgentModelRegistrationTests(unittest.TestCase):
    """'sre identity'/'sre agent list-models' are thin overrides of generated
    recipes with the same names -- just confirms their schemas build."""

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
            SkillCreate, extension_name="my-skill", file_path=path, value=None, description=None,
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
            SkillCreate, extension_name="my-skill", file_path=path, value=None, description="From flag", tools=None,
        )
        command._prepare_value()
        self.assertEqual(json.loads(command.ctx.args.value)["description"], "From flag")

    def test_prepare_value_no_description_anywhere_raises(self):
        path = self._write("Body with no frontmatter at all\n")
        command = _bare_command(SkillCreate, extension_name="my-skill", file_path=path, value=None, description=None, tools=None)
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_rejects_a_path_like_frontmatter_name(self):
        for bad in ("../tools/victim", "a/b", ".."):
            path = self._write(f"---\nname: {bad}\ndescription: D\n---\nBody\n")
            command = _bare_command(SkillCreate, extension_name=None, file_path=path, value=None,
                                    description=None, tools=None)
            with self.assertRaisesRegex(CLIError, "valid skill name"):
                command._prepare_value()

    def test_arm_extension_paths_quote_the_name(self):
        from azext_sre.custom import _arm_extension_resource_id

        self.assertEqual(_arm_extension_resource_id("/agents/a", "skills", "../tools/victim"),
                         "/agents/a/skills/..%2Ftools%2Fvictim")
        with self.assertRaises(CLIError):
            _arm_extension_resource_id("/agents/a", "skills", "..")

    def test_prepare_value_both_file_path_and_value_raises(self):
        path = self._write("---\ndescription: D\n---\nBody\n")
        command = _bare_command(
            SkillCreate, extension_name="my-skill", file_path=path, value='{"description": "x"}', description=None, tools=None,
        )
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_neither_file_path_nor_value_raises(self):
        command = _bare_command(SkillCreate, extension_name="my-skill", file_path=None, value=None, description=None, tools=None)
        with self.assertRaises(CLIError):
            command._prepare_value()

    def test_prepare_value_noop_when_only_value_given(self):
        command = _bare_command(
            SkillCreate, extension_name="my-skill", file_path=None, value='{"description": "x"}', description=None, tools=None,
        )
        command._prepare_value()
        self.assertEqual(command.ctx.args.value, '{"description": "x"}')

    def test_frontmatter_name_is_used_when_name_is_omitted(self):
        path = self._write("---\nname: azure-monitor-rca\ndescription: D\n---\nBody\n")
        command = _bare_command(
            SkillCreate, extension_name=None, file_path=path, value=None, description=None, tools=None)
        command._prepare_value()
        self.assertEqual(command.ctx.args.extension_name, "azure-monitor-rca")

    def test_name_flag_wins_over_frontmatter_name_with_a_warning(self):
        path = self._write("---\nname: from-file\ndescription: D\n---\nBody\n")
        command = _bare_command(
            SkillCreate, extension_name="from-flag", file_path=path, value=None, description=None, tools=None)
        with self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
            command._prepare_value()
        self.assertEqual(command.ctx.args.extension_name, "from-flag")
        self.assertIn("from-file", logs.output[0])

    def test_no_name_anywhere_raises(self):
        path = self._write("---\ndescription: D\n---\nBody\n")
        command = _bare_command(
            SkillCreate, extension_name=None, file_path=path, value=None, description=None, tools=None)
        with self.assertRaisesRegex(CLIError, "name:"):
            command._prepare_value()


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
    """--grant-access-to-me on 'agent create' runs
    'sre access grant --assignee-me' after provisioning, so "me" is resolved
    the same Graph-free way as 'access grant'."""

    def _run(self, calls, grant_result=None, **extra_args):
        args = {
            "agent_name": "myagent", "resource_group": "rg",
            "grant_access_to_me": None,
        }
        args.update(extra_args)
        command = _bare_command(_TestGrantAccessToMe, **args)

        def fake_cli_invoke(cli_ctx, *cmd_args, allow_missing=False):
            calls.append(cmd_args)
            self.assertNotEqual(cmd_args[:1], ("ad",), f"Microsoft Graph command: {cmd_args}")
            self.assertNotIn("--assignee", cmd_args)
            return grant_result if grant_result is not None else {"principalId": "user-object-id"}

        with patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            command.post_operations()
        return calls

    def test_no_flag_does_nothing(self):
        calls = self._run([])
        self.assertEqual(calls, [])

    def test_resolves_signed_in_user_and_calls_grant_access(self):
        with self.assertLogs("cli.azext_sre.custom", level="WARNING") as logs:
            calls = self._run([], grant_access_to_me="admin")
        self.assertEqual(calls, [(
            "sre", "access", "grant", "--agent-name", "myagent", "--resource-group", "rg",
            "--role", "admin", "--assignee-me",
        )])
        self.assertIn("SRE Agent Administrator", logs.output[-1])
        self.assertIn("user-object-id", logs.output[-1])

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

    def test_malformed_connections_file_is_not_overwritten(self):
        command = _bare_command(
            GetConnection, name="myagent", resource_group="rg",
            data_plane_audience="https://azuresre.dev",
        )

        def fake_cli_invoke(cli_ctx, *cmd_args, allow_missing=False):
            return {"properties": {"agentEndpoint": "https://myagent.example"}}

        with patch.object(AAZCommand, "_handler", lambda self, command_args: None), \
             patch("azext_sre.custom._cli_invoke", fake_cli_invoke), \
             tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, "sreAgentConnections.json")
            for bad in ("{not json", "[1, 2]"):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write(bad)
                with patch("azext_sre.custom._CONNECTIONS_FILE", path):
                    with self.assertRaises(CLIError):
                        command._handler({})
                with open(path, "r", encoding="utf-8") as handle:
                    self.assertEqual(handle.read(), bad)

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

    def test_access_list_format_shows_object_id_when_names_are_not_filled(self):
        from azext_sre._transformers import access_list_table_format

        without_name = dict(self._ROLE_ASSIGNMENT)
        del without_name["principalName"]
        empty_name = dict(self._ROLE_ASSIGNMENT, principalName="")
        rows = access_list_table_format([without_name, empty_name, self._ROLE_ASSIGNMENT])
        self.assertEqual([row["Principal"] for row in rows], ["user-id", "user-id", "someone@example.com"])

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


class _FakeCreateBase:
    """Mimics the generated create's _execute_operations generator."""

    polling = None

    def pre_operations(self):
        pass

    def post_operations(self):
        pass

    def _execute_operations(self):
        self.pre_operations()
        yield self.polling
        self.post_operations()


class _TestIdentityCleanup(_DefaultSystemIdentityMixin, _FakeCreateBase):
    pass


class _FakePolling:
    def __init__(self, error=None):
        self.error = error
        self.extra = "delegated"

    def run(self):
        if self.error:
            raise self.error


class AutoIdentityCleanupTests(unittest.TestCase):
    """The identity auto-created for 'agent create' is deleted again if the
    agent itself is never created."""

    IDENTITY_ID = ("/subscriptions/sub/resourceGroups/rg/providers/"
                   "Microsoft.ManagedIdentity/userAssignedIdentities/myagent-identity-abc")

    def _command(self, polling=None, **extra_args):
        args = {"mi_system_assigned": AAZUndefined, "mi_user_assigned": AAZUndefined,
                "agent_name": "myagent", "resource_group": "rg", "location": "eastus2"}
        args.update(extra_args)
        command = _bare_command(_TestIdentityCleanup, **args)
        command.ctx.subscription_id = "sub"
        command.polling = polling
        return command

    def _drive(self, command, arm_side_effect=None):
        with patch("azext_sre.custom._create_user_assigned_identity", return_value=self.IDENTITY_ID), \
             patch("azext_sre.custom._arm_request", side_effect=arm_side_effect) as arm, \
             patch("azext_sre.custom.logger") as fake_logger:
            try:
                for polling in command._execute_operations():
                    polling.run()
            finally:
                command.arm, command.log = arm, fake_logger

    def _assert_identity_deleted(self, command):
        command.arm.assert_called_once_with(ANY, "DELETE", self.IDENTITY_ID, "2023-01-31", missing_ok=True)

    def test_initial_put_failure_deletes_the_identity(self):
        command = self._command()

        def failing_execute(_self):
            _self.pre_operations()
            raise CLIError("PUT failed")
            yield  # pylint: disable=unreachable

        with patch.object(_FakeCreateBase, "_execute_operations", failing_execute):
            with self.assertRaisesRegex(CLIError, "PUT failed"):
                self._drive(command)
        self._assert_identity_deleted(command)

    def test_lro_failure_deletes_the_identity(self):
        command = self._command(polling=_FakePolling(CLIError("provisioning failed")))
        with self.assertRaisesRegex(CLIError, "provisioning failed"):
            self._drive(command)
        self._assert_identity_deleted(command)

    def test_success_keeps_the_identity(self):
        command = self._command(polling=_FakePolling())
        self._drive(command)
        command.arm.assert_not_called()

    def test_wrapped_polling_delegates_other_attributes(self):
        command = self._command(polling=_FakePolling())
        with patch("azext_sre.custom._create_user_assigned_identity", return_value=self.IDENTITY_ID):
            polling = next(command._execute_operations())
        self.assertEqual(polling.extra, "delegated")

    def test_failure_after_agent_was_created_keeps_the_identity(self):
        command = self._command(polling=_FakePolling())
        with patch.object(_FakeCreateBase, "post_operations", side_effect=CLIError("grant failed")):
            with self.assertRaisesRegex(CLIError, "grant failed"):
                self._drive(command)
        command.arm.assert_not_called()

    def test_explicit_identity_is_never_deleted(self):
        command = self._command(polling=_FakePolling(CLIError("provisioning failed")),
                                mi_system_assigned="True")
        with self.assertRaisesRegex(CLIError, "provisioning failed"):
            self._drive(command)
        command.arm.assert_not_called()

    def test_cleanup_failure_warns_and_keeps_the_original_error(self):
        command = self._command(polling=_FakePolling(CLIError("provisioning failed")))
        with self.assertRaisesRegex(CLIError, "provisioning failed"):
            self._drive(command, arm_side_effect=CLIError("delete failed"))
        message = command.log.warning.call_args[0][0] % command.log.warning.call_args[0][1:]
        self.assertIn("az identity delete --ids " + self.IDENTITY_ID, message)


class GrantAccessToMeFailureTests(unittest.TestCase):
    def test_grant_failure_says_the_agent_exists_and_how_to_retry(self):
        command = _bare_command(_TestGrantAccessToMe, agent_name="myagent", resource_group="rg",
                                grant_access_to_me="admin")

        def fake_cli_invoke(cli_ctx, *cmd_args, allow_missing=False):
            raise CLIError("AuthorizationFailed")

        with patch("azext_sre.custom._cli_invoke", fake_cli_invoke):
            with self.assertRaises(CLIError) as raised:
                command.post_operations()
        message = str(raised.exception)
        self.assertIn("Agent 'myagent' was created", message)
        self.assertIn("AuthorizationFailed", message)
        self.assertIn("az sre access grant --agent-name myagent --resource-group rg --role admin --assignee-me",
                      message)


class ConnectorOverwriteTests(unittest.TestCase):
    def test_overwrite_skips_the_existence_check(self):
        command = _bare_command(_TestConnectorExistenceGuard, agent_name="myagent", resource_group="rg",
                                connector_name="myconn", overwrite=True)
        with patch("azext_sre.custom._arm_request") as arm, \
             patch("azext_sre.custom._resolve_agent_resource_id") as resolve:
            command.pre_operations()
        arm.assert_not_called()
        resolve.assert_not_called()

    def test_existence_check_still_runs_by_default(self):
        command = _bare_command(_TestConnectorExistenceGuard, agent_name="myagent", resource_group="rg",
                                connector_name="myconn", overwrite=False)
        with patch("azext_sre.custom._arm_request", return_value={"name": "myconn"}), \
             patch("azext_sre.custom._resolve_agent_resource_id", return_value="/agents/myagent"):
            with self.assertRaises(ResourceExistsError) as raised:
                command.pre_operations()
        self.assertIn("--overwrite", str(raised.exception))

    def test_connector_create_schema_has_overwrite(self):
        schema = ConnectorCreate._build_arguments_schema()
        self.assertEqual(schema.overwrite._options, ["--overwrite"])


class McpEndpointSafetyTests(unittest.TestCase):
    def _run(self, **extra_args):
        args = {"data_connector_type": "Mcp", "file_path": None, "mcp_endpoint": None, "github": None,
                "data_source": None, "extended_properties": None}
        args.update(extra_args)
        command = _bare_command(_TestConnectorConvenience, **args)
        with patch("azext_sre.custom.logger") as fake_logger:
            command.pre_operations()
        return command.ctx.args, fake_logger

    def test_non_https_endpoint_is_rejected(self):
        for endpoint in ("http://example.com/mcp", "ftp://example.com", "example.com/mcp"):
            with self.assertRaises(InvalidArgumentValueError):
                self._run(mcp_endpoint=endpoint)

    def test_managed_identity_without_scope_warns_about_the_arm_token(self):
        args, log = self._run(mcp_endpoint="https://mcp.contoso.com/mcp", managed_identity_auth=True)
        self.assertEqual(args.extended_properties["armScope"], "https://management.azure.com/.default")
        log.warning.assert_called_once()
        self.assertEqual(log.warning.call_args[0][1], "mcp.contoso.com")

    def test_managed_identity_with_scope_does_not_warn(self):
        _, log = self._run(mcp_endpoint="https://mcp.contoso.com/mcp", managed_identity_auth=True,
                           mi_token_scope="api://contoso-mcp/.default")
        log.warning.assert_not_called()


class Utf8BomFileTests(unittest.TestCase):
    """Files saved by Windows editors often start with a UTF-8 BOM."""

    def _write(self, text, suffix):
        handle = tempfile.NamedTemporaryFile(mode="w", suffix=suffix, delete=False, encoding="utf-8-sig")
        self.addCleanup(lambda: os.remove(handle.name))
        handle.write(text)
        handle.close()
        return handle.name

    def test_skill_md_frontmatter_is_found_after_a_bom(self):
        path = self._write("---\ndescription: Desc\n---\nBody\n", ".md")
        self.assertEqual(_parse_skill_md(path), ("Desc", "Body"))

    def test_knowledge_text_does_not_keep_the_bom(self):
        path = self._write("hello", ".txt")
        command = _bare_command(_TestConnectorConvenience, data_connector_type="KnowledgeText",
                                file_path=path, mcp_endpoint=None, github=None,
                                data_source=None, extended_properties=None)
        command.pre_operations()
        self.assertEqual(command.ctx.args.extended_properties, {"content": "hello"})

    def test_hook_script_does_not_keep_the_bom(self):
        path = self._write("print('x')\n", ".py")
        command = _bare_command(SubagentCreate, value=json.dumps({"instructions": "x"}),
                                pre_tool_use_script_file=path)
        command._prepare_value()
        script = json.loads(command.ctx.args.value)["hooks"]["PreToolUse"][0]["script"]
        self.assertEqual(script, "print('x')\n")


class DirectExtensionCreateNormalizationTests(unittest.TestCase):
    """The agent-endpoint create path applies the same --value handling as ARM."""

    def _create(self, raw_value, existing=None, overwrite=True):
        requests = []

        def fake_request(cli_ctx, agent_name, resource_group, method, path, body=None, missing_ok=False):
            requests.append((method, path, body))
            return existing if method == "GET" else body

        with patch("azext_sre.custom._direct_extension_request", fake_request):
            _direct_extension_create(None, "myagent", "rg", "tools", "t", raw_value, overwrite)
        return requests

    def test_python_tool_is_sent_as_python_function_tool(self):
        value = json.dumps({"type": "PythonTool", "description": "d", "functionCode": "def main(): pass"})
        with patch.dict("azext_sre.custom.EXTENSION_VALUE_VALIDATORS", {"tools": lambda parsed: None}):
            requests = self._create(value)
        self.assertEqual(requests[-1][0], "PUT")
        self.assertEqual(requests[-1][2]["properties"]["type"], "PythonFunctionTool")

    def test_validator_runs_on_the_direct_path(self):
        with patch.dict("azext_sre.custom.EXTENSION_VALUE_VALIDATORS",
                        {"tools": MagicMock(side_effect=CLIError("bad tool"))}):
            with self.assertRaisesRegex(CLIError, "bad tool"):
                self._create(json.dumps({"type": "LinkTool"}))

    def test_new_http_client_tool_is_rejected(self):
        with patch.dict("azext_sre.custom.EXTENSION_VALUE_VALIDATORS", {"tools": lambda parsed: None}):
            with self.assertRaisesRegex(CLIError, "HttpClientTool"):
                self._create(json.dumps({"type": "HttpClientTool"}), existing=None)

    def test_existing_http_client_tool_can_be_updated(self):
        existing = {"name": "t", "properties": {"type": "HttpClientTool"}}
        with patch.dict("azext_sre.custom.EXTENSION_VALUE_VALIDATORS", {"tools": lambda parsed: None}):
            requests = self._create(json.dumps({"type": "HttpClientTool"}), existing=existing)
        self.assertEqual(requests[-1][0], "PUT")


class ShortTimestampTests(unittest.TestCase):
    def test_trailing_z_is_not_doubled(self):
        from azext_sre._transformers import _short_timestamp

        self.assertEqual(_short_timestamp("2026-11-03T18:10:42Z"), "2026-11-03T18:10:42Z")
        self.assertEqual(_short_timestamp("2026-11-03T18:10:42.12Z"), "2026-11-03T18:10:42Z")
        self.assertEqual(_short_timestamp("2026-11-03T18:10:42.126877+00:00"), "2026-11-03T18:10:42Z")


class GithubTokenEnvWarningTests(unittest.TestCase):
    def test_env_token_warning_names_the_variable(self):
        for var in ("GITHUB_TOKEN", "GH_TOKEN"):
            with patch.dict(os.environ, {"GITHUB_TOKEN": "", "GH_TOKEN": ""}), \
                 patch("azext_sre.custom.logger") as fake_logger:
                os.environ[var] = "env-token"
                self.assertEqual(_github_token(), "env-token")
            message = fake_logger.warning.call_args[0][0] % fake_logger.warning.call_args[0][1:]
            self.assertIn(var, message)
            self.assertIn("stored on the agent", message)

    def test_explicit_token_does_not_warn(self):
        with patch("azext_sre.custom.logger") as fake_logger:
            _github_token(explicit_token="explicit")
        fake_logger.warning.assert_not_called()


def setUpModule():
    # Keep route detection off by default so tests never touch the network or the real cache.
    os.environ["AZSRE_EXTENSION_ROUTE"] = "arm"


if __name__ == "__main__":
    unittest.main()

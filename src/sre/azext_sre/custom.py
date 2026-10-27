# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# This is the sanctioned override layer, not regenerated. The generated AAZ
# command recipes live under aaz/latest/... and are produced from the
# Microsoft.App/agents (SRE Agent) ARM swagger using the public command name
# "app agent *" (the swagger's RP folder is literally "app"). Every class
# below is a thin subclass of a generated command that:
#   1. renames the public surface from "app agent ..." to "sre agent ...",
#      which is the only reason these recipes exist (there is no behavioral
#      difference the generator could not already produce);
#   2. adds real-world-validated argument help/enums where the generated
#      swagger left them as bare strings (e.g. --model-provider), grounded in
#      the official SRE Agent docs and the merged stable/2026-07-01 TypeSpec
#      source (see running notes section -1 for citations);
#   3. never duplicates generated request/response logic -- it is reused via
#      super().
#
# commands.py auto-discovers every class defined here via
# inspect.isclass/issubclass scanning of vars(custom) (same pattern as
# azext-aigateway), so a new command only needs to be added here, decorated
# with @register_command("sre agent ..."), to be picked up.
# --------------------------------------------------------------------------------------------

# pylint: disable=too-many-lines
# pylint: disable=too-many-statements
# pylint: disable=protected-access

import base64
import json
import os
from functools import partial

from azure.cli.core.aaz import (
    AAZBoolArg,
    AAZCommand,
    AAZCommandGroup,
    AAZListArg,
    AAZObjectArg,
    AAZResourceGroupNameArg,
    AAZStrArg,
    AAZStrArgFormat,
    AAZUndefined,
    has_value,
    register_command,
    register_command_group,
)
from azure.cli.core.aaz._operation import AAZHttpOperation
from azure.cli.core.azclierror import CLIError, ResourceNotFoundError
from azure.core.exceptions import ResourceExistsError
from azure.cli.core.util import send_raw_request
from knack.log import get_logger

from .aaz.latest.app.agent import Create as _GeneratedCreate
from .aaz.latest.app.agent import Delete as _GeneratedDelete
from .aaz.latest.app.agent import List as _GeneratedList
from .aaz.latest.app.agent import Show as _GeneratedShow
from .aaz.latest.app.agent import Start as _GeneratedStart
from .aaz.latest.app.agent import Stop as _GeneratedStop
from .aaz.latest.app.agent import Update as _GeneratedUpdate
from .aaz.latest.app.agent.connector import Create as _GeneratedConnectorCreate
from .aaz.latest.app.agent.connector import Update as _GeneratedConnectorUpdate
from .aaz.latest.app.agent.connector import Show as _GeneratedConnectorShow
from .aaz.latest.app.agent.connector import List as _GeneratedConnectorList

logger = get_logger(__name__)

# api-version pinned to match the already-generated aaz/latest recipes
# (2026-01-01, see aaz/latest/app/agent/_show.py). Running notes section 1a
# flags an unresolved discrepancy against the officially published docs
# (2025-05-01-preview) -- reconcile before GA, but every command in this
# extension must use the SAME version the generated code already uses or
# property names may silently mismatch between hand-written and generated
# calls.
API_VERSION = "2026-01-01"

# Networking (VNet injection + sandbox egress) is only supported by the
# REAL deployed api-version 2026-11-01-preview (confirmed live via
# `az provider show --namespace Microsoft.App`). It is NOT present in
# 2026-01-01 (the version aaz/latest is generated against) and the
# 2026-07-01 public-spec version that DOES have it is NOT actually
# deployed to production (ARM rejects it -- see running notes section 25).
# There is no public swagger for 2026-11-01-preview yet, so these fields
# cannot be codegen'd; the shape below was read directly from the
# internal control-plane source (AAPT-SREAgent-ControlPlane repo,
# src/WebApi/Views/Version20261101Preview/AgentView.cs) with Dalibor's
# repo access, not from any public spec. Treat this as hand-maintained
# and re-verify against that source if the service's shape ever changes.
NETWORK_API_VERSION = "2026-11-01-preview"


def _arg_value(value):
    """Unwrap an AAZ argument into a plain Python value (None if unset).

    Mirrors azext-aigateway's custom.py helper of the same name -- reused
    here verbatim since this extension follows the same AAZ-override
    pattern.
    """
    if value == AAZUndefined:
        return None
    return AAZHttpOperation.serialize_content(value)


def _snake_to_camel(key):
    """Convert a single snake_case key segment to camelCase."""
    head, *rest = key.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _camelize_keys(value):
    """Recursively rewrite snake_case dict keys to camelCase.

    Needed for any hand-written command (e.g. UpdateNetwork below) that
    builds its request body straight from an AAZObjectArg/AAZListArg via
    _arg_value(): those are pure CLI-argument-parsing schemas with no
    serialized_name/JSON mapping, so AAZHttpOperation.serialize_content()
    returns dicts keyed by the raw Python attribute name (snake_case), e.g.
    "allowed_hosts" instead of "allowedHosts". Confirmed live against
    mytestagent: ARM rejects the un-camelized body with "Unknown properties
    allowed_hosts ... are not supported" (2026-10-26). Generated aaz commands
    never hit this because their request body comes from a real AAZObjectType
    schema with camelCase serialized_name baked in from swagger -- only
    hand-written raw-PUT commands need this conversion.
    """
    if isinstance(value, dict):
        return {_snake_to_camel(k): _camelize_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_camelize_keys(item) for item in value]
    return value


def _arm_request(cli_ctx, method, resource_id, api_version, body=None, missing_ok=False):
    """Issue a raw ARM request against a resource ID not covered by a
    generated aaz recipe (e.g. the agent's /usages and /dailyusages child
    collections, which are read-only list endpoints with no corresponding
    Create/Update verb for aaz-dev-tools to anchor a command group on).

    Copied from azext-aigateway's custom.py (same helper name/signature) so
    both extensions share one well-understood pattern for "generated CLI
    doesn't cover this ARM GET" situations.
    """
    if resource_id.startswith("http://") or resource_id.startswith("https://"):
        url = resource_id
    else:
        separator = "&" if "?" in resource_id else "?"
        resource_manager = cli_ctx.cloud.endpoints.resource_manager.rstrip("/")
        url = f"{resource_manager}{resource_id}{separator}api-version={api_version}"
    try:
        response = send_raw_request(
            cli_ctx,
            method,
            url,
            headers=["Content-Type=application/json"],
            body=json.dumps(body) if body is not None else None,
        )
    except Exception as ex:  # Azure CLI normalizes HTTP errors by command.
        status_code = getattr(getattr(ex, "response", None), "status_code", None)
        if missing_ok and status_code == 404:
            return None
        raise
    if not response.content:
        return {}
    return response.json()


def _cli_invoke(cli_ctx, *args, allow_missing=False):
    """Run another public `az sre ...` command in-process and return its
    parsed result. Copied from azext-aigateway's helper of the same name.
    """
    import io

    from azure.cli.core import get_default_cli
    from azure.cli.core.azclierror import ResourceNotFoundError as _RNFE

    cli = get_default_cli()
    cli.out_file = io.StringIO()
    try:
        exit_code = cli.invoke(list(args), out_file=io.StringIO())
    except (_RNFE, SystemExit) as ex:
        if allow_missing:
            return None
        raise CLIError(f"'{' '.join(args)}' failed: {ex}") from ex
    if exit_code not in (0, None):
        if allow_missing:
            return None
        raise CLIError(f"'{' '.join(args)}' exited with code {exit_code}.")
    result = cli.result.result if cli.result else None
    if result is None and allow_missing:
        return None
    return result


# Local file the data-plane `sre` CLI (separate deliverable, not an az
# extension -- see running notes section 1) is expected to read from, the
# same way `az aks get-credentials` writes kubeconfig for kubectl to pick
# up. Keeping the bridge file format here (not duplicated at the data-plane
# side) means this is the only place the on-disk schema is defined.
_CONNECTIONS_FILE = os.path.join(
    os.path.expanduser("~"), ".azure", "sreAgentConnections.json"
)


# Real API enum values confirmed from the merged stable/2026-07-01 TypeSpec
# source (agent.models.tsp DefaultModel.provider doc comment) and the SRE
# Agent docs. The portal UI shows a friendly label ("Azure OpenAI") that does
# NOT match the wire value -- the CLI must always send/accept the real
# values below, surfacing the friendly names only in --help text.
MODEL_PROVIDERS = {
    "anthropic": "Anthropic",
    "microsoftfoundry": "MicrosoftFoundry",
}


def _normalize_model_provider(value):
    if value is None:
        return value
    normalized = MODEL_PROVIDERS.get(str(value).strip().lower())
    if normalized is None:
        raise CLIError(
            "--model-provider must be one of: "
            + ", ".join(sorted(MODEL_PROVIDERS))
            + f" (got '{value}')."
        )
    return normalized


class _ModelProviderArgMixin:
    """Shared --default-model.provider help/validation for create and update.

    The generated schema types `default_model.provider` as a bare AAZStrArg
    (the swagger models it as `string`, not an enum, because the service
    documents it informally). We tighten it here without touching the
    generated file: real values are case-insensitively accepted and
    normalized to the exact wire casing the service expects.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        default_model = getattr(schema, "default_model", None)
        if default_model is not None:
            provider = getattr(default_model, "provider", None)
            # AAZBaseArg always initializes ._help as a dict (keyed by
            # 'short-summary'/'long-summary'/'name'/'populator-commands');
            # to_cmd_arg() calls ._help.get(...), so overwriting it with a
            # plain string (instead of merging into the dict) breaks `-h`
            # with "'str' object has no attribute 'get'". Must assign into
            # the existing dict, not replace it.
            if provider is not None and isinstance(getattr(provider, "_help", None), dict):
                provider._help["short-summary"] = (
                    "AI provider for the agent's default model. Real API "
                    "values are 'Anthropic' and 'MicrosoftFoundry' -- note "
                    "the Azure Portal shows 'Azure OpenAI' as a friendly "
                    "label for MicrosoftFoundry, but the API never accepts "
                    "that string. Case-insensitive."
                )
        return schema

    def pre_operations(self):
        args = self.ctx.args
        default_model = getattr(args, "default_model", None)
        if default_model is not None and has_value(default_model.provider):
            default_model.provider = _normalize_model_provider(
                default_model.provider.to_serialized_data()
            )
        super().pre_operations()


class _GrantAccessToMeMixin:
    """Adds --grant-access-to-me to 'agent create', collapsing the
    create -> `az ad signed-in-user show` -> grant-access dance into one
    flag. GrantAccess (defined further below in this module) already
    builds the agent's resource-ID scope and issues 'role assignment
    create' for you; this just auto-resolves "me" and calls it right
    after the agent finishes provisioning.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.grant_access_to_me = AAZStrArg(
            options=["--grant-access-to-me"],
            help="Grant the signed-in user a built-in SRE Agent role "
            "immediately after creating the agent: 'admin', 'user', "
            "'author', or 'reader'. Resolves your object ID via "
            "'az ad signed-in-user show' automatically -- equivalent to "
            "running 'sre agent grant-access --assignee <your-object-id>' "
            "as a separate, manual follow-up command.",
            enum={key: key for key in GrantAccess._ROLES},
        )
        return schema

    def post_operations(self):
        super().post_operations()
        role_key = _arg_value(getattr(self.ctx.args, "grant_access_to_me", None))
        if not role_key:
            return
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        invoke = partial(_cli_invoke, self.cli_ctx)
        signed_in_user = invoke("ad", "signed-in-user", "show")
        object_id = (signed_in_user or {}).get("id") if isinstance(signed_in_user, dict) else None
        if not object_id:
            raise CLIError("Could not resolve the signed-in user's object ID via 'az ad signed-in-user show'.")
        invoke(
            "sre", "agent", "grant-access",
            "--agent-name", agent_name, "--resource-group", resource_group,
            "--role", role_key, "--assignee", object_id,
        )
        logger.warning(
            "Granted '%s' role to signed-in user (%s) on agent '%s'.",
            GrantAccess._ROLES[role_key], object_id, agent_name,
        )


@register_command("sre agent create")
class Create(_ModelProviderArgMixin, _GrantAccessToMeMixin, _GeneratedCreate):
    """Create an SRE Agent.

    :example: Create an agent with an Anthropic default model
        az sre agent create --name myagent --resource-group myrg \\
            --location eastus2 --default-model "{provider:anthropic,name:claude-sonnet-4-5}"
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        # The generated pattern is correct (confirmed against the merged
        # stable/2026-07-01 TypeSpec: ^[A-Za-z]([-A-Za-z0-9]{0,30}[A-Za-z0-9])$
        # for both Agent and AgentConnector names) -- re-declared here only
        # so the CLI --help text is explicit about the constraint up front,
        # instead of surfacing it as a raw regex error after submission.
        schema.agent_name._fmt = AAZStrArgFormat(
            pattern="^[A-Za-z]([-A-Za-z0-9]{0,30}[A-Za-z0-9])$",
        )
        cls._args_schema = schema
        return cls._args_schema


@register_command("sre agent update")
class Update(_ModelProviderArgMixin, _GeneratedUpdate):
    """Update an SRE Agent."""

    _args_schema = None


# Real wire values confirmed via the control-plane source
# (src/ApiResources/DataModels/KnownDataConnectorTypes.cs and
# src/Services/Validators/DataConnectorValidator.cs): "Kusto" covers
# Azure Data Explorer/App Insights/Log Analytics (differentiated by
# --data-source endpoint, not a separate type value), "Mcp" covers generic
# MCP-compatible connectors (PagerDuty/ServiceNow/Datadog/Splunk/S360/Ev2/
# etc. -- these are *not* separate enum values, just Mcp connectors pointed
# at different endpoints), "Outlook", "Teams", "Icm" (Incident Management --
# singleton per agent, e.g. "https://prod.microsofticm.com"), "KustoClient"
# (Kusto via the @azure/mcp server -- no DataSource/ExtendedProperties
# needed, the runtime hardcodes the mcp server command), "Dgrep"
# (Diagnostics Grep -- singleton per agent). Also four "knowledge item"
# types that are multiplexed over this same connectors route and carry
# their payload in --extended-properties (content/fileContent/url) instead
# of --data-source, which they don't require at all: "KnowledgeText",
# "KnowledgeFile", "KnowledgeWebPage", "KnowledgeRepository". Same
# friendly-name-vs-wire-value problem as --model-provider: the swagger
# types this as a bare string, so the generated arg accepts anything -- we
# tighten it here without touching the generated file.
DATA_CONNECTOR_TYPES = {
    "kusto": "Kusto",
    "mcp": "Mcp",
    "outlook": "Outlook",
    "teams": "Teams",
    "icm": "Icm",
    "kustoclient": "KustoClient",
    "dgrep": "Dgrep",
    "knowledgetext": "KnowledgeText",
    "knowledgefile": "KnowledgeFile",
    "knowledgewebpage": "KnowledgeWebPage",
    "knowledgerepository": "KnowledgeRepository",
}

# Connector types that do not require --data-source at all (the data-plane
# validator exempts them -- see DataConnectorValidator.cs
# IsKnowledgeConnectorType). Used only to keep --help accurate; the CLI
# does not enforce --data-source presence itself (that's left to the
# service), so this is documentation, not a code path.
KNOWLEDGE_DATA_CONNECTOR_TYPES = {
    "KnowledgeText",
    "KnowledgeFile",
    "KnowledgeWebPage",
    "KnowledgeRepository",
}


def _normalize_data_connector_type(value):
    if value is None:
        return value
    normalized = DATA_CONNECTOR_TYPES.get(str(value).strip().lower())
    if normalized is None:
        raise CLIError(
            "--data-connector-type must be one of: "
            + ", ".join(sorted(DATA_CONNECTOR_TYPES))
            + f" (got '{value}')."
        )
    return normalized


class _DataConnectorTypeArgMixin:
    """Shared --data-connector-type help/validation for connector create and update.

    Mirrors _ModelProviderArgMixin above: the generated schema types
    data_connector_type as a bare AAZStrArg (the swagger models it as
    `string`, not an enum). We tighten it here without touching the
    generated file: real values are case-insensitively accepted and
    normalized to the exact wire casing the service expects.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        data_connector_type = getattr(schema, "data_connector_type", None)
        # See _ModelProviderArgMixin above for why this must merge into the
        # existing ._help dict rather than replace it.
        if data_connector_type is not None and isinstance(getattr(data_connector_type, "_help", None), dict):
            data_connector_type._help["short-summary"] = (
                "Type of the data connector. Real API values: 'Kusto' "
                "(covers Azure Data Explorer, App Insights, and Log "
                "Analytics -- differentiated by --data-source, not a "
                "separate type), 'Mcp' (PagerDuty/ServiceNow/Datadog/Splunk/"
                "S360/Ev2/etc. -- differentiated by endpoint, not a "
                "separate type), 'Outlook', 'Teams', 'Icm' (singleton per "
                "agent), 'KustoClient' (Kusto via the @azure/mcp server; "
                "no --data-source needed), 'Dgrep' (singleton per agent), "
                "and four knowledge-item types that need --extended-"
                "properties instead of --data-source: 'KnowledgeText', "
                "'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository'."
                " Case-insensitive."
            )
        return schema

    def pre_operations(self):
        args = self.ctx.args
        data_connector_type = getattr(args, "data_connector_type", None)
        if has_value(data_connector_type):
            args.data_connector_type = _normalize_data_connector_type(
                data_connector_type.to_serialized_data()
            )
        super().pre_operations()


# Real public GitHub Copilot MCP endpoint, confirmed live this session
# (provisioningState: Succeeded against a real agent). Same constant
# azext-aigateway's _onboarding.py uses for its own "--github true" shortcut
# -- this is the SRE-Agent-side equivalent for 'connector create --type Mcp'.
GITHUB_COPILOT_MCP_ENDPOINT = "https://api.githubcopilot.com/mcp/"


class _ConnectorConvenienceArgsMixin:
    """Adds --file-path/--mcp-endpoint/--github to 'connector create', so
    KnowledgeFile/KnowledgeText/Mcp connectors don't require a hand-built
    base64 payload or the (confirmed live, easy to get wrong) nested
    --extended-properties JSON shape Mcp actually needs. The service's real
    wire shape is unchanged -- this only builds it for the caller, the same
    spirit as 'sre agent repo connect' and azext-aigateway's
    'mcp create --github true'.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        if hasattr(schema, "file_path"):
            # Already added -- _build_arguments_schema can be invoked more
            # than once against the same cached schema instance (e.g. by
            # repeated test calls), and AAZArgumentsSchema forbids
            # redefining a key.
            return schema
        schema.file_path = AAZStrArg(
            options=["--file-path"],
            arg_group="Properties",
            help="Local file to ingest, instead of hand-building "
            "--extended-properties yourself. For --data-connector-type "
            "KnowledgeFile, the CLI reads and base64-encodes the file into "
            "extended-properties.fileContent/fileName. For KnowledgeText, "
            "the CLI reads the file as UTF-8 text into "
            "extended-properties.content.",
        )
        schema.mcp_endpoint = AAZStrArg(
            options=["--mcp-endpoint"],
            arg_group="Properties",
            help="For --data-connector-type Mcp: the MCP server's HTTP "
            "endpoint URL. Builds both --data-source and the nested "
            "extended-properties.transport/endpoint the service actually "
            "requires (confirmed live: a bare --data-source alone is "
            "rejected with 'Endpoint value is required for MCP connector "
            "with HTTP transport.').",
        )
        schema.github = AAZBoolArg(
            options=["--github"],
            arg_group="Properties",
            help="For --data-connector-type Mcp: shortcut for "
            "--mcp-endpoint pointed at the real public GitHub Copilot MCP "
            "server (https://api.githubcopilot.com/mcp/).",
        )
        return schema

    def pre_operations(self):
        args = self.ctx.args
        connector_type = _arg_value(getattr(args, "data_connector_type", None))
        file_path = _arg_value(getattr(args, "file_path", None))
        mcp_endpoint = _arg_value(getattr(args, "mcp_endpoint", None))
        github = _arg_value(getattr(args, "github", None))

        if github or mcp_endpoint:
            if connector_type != "Mcp":
                raise CLIError("--github/--mcp-endpoint require --data-connector-type Mcp.")
            endpoint = GITHUB_COPILOT_MCP_ENDPOINT if github else mcp_endpoint
            args.data_source = endpoint
            args.extended_properties = {"transport": "Http", "endpoint": endpoint}
        elif file_path:
            if connector_type not in ("KnowledgeFile", "KnowledgeText"):
                raise CLIError(
                    "--file-path is only supported for --data-connector-type "
                    "KnowledgeFile or KnowledgeText."
                )
            if not os.path.isfile(file_path):
                raise CLIError(f"--file-path '{file_path}' does not exist.")
            if connector_type == "KnowledgeFile":
                with open(file_path, "rb") as handle:
                    content = base64.b64encode(handle.read()).decode("ascii")
                args.extended_properties = {
                    "fileContent": content,
                    "fileName": os.path.basename(file_path),
                }
            else:
                with open(file_path, "r", encoding="utf-8") as handle:
                    text = handle.read()
                args.extended_properties = {"content": text}

        super().pre_operations()


class _ConnectorExistenceGuardMixin:
    """Guards 'connector create' against silently overwriting an existing
    connector of the same name. The generated PUT has no If-Match/If-None-
    Match support here, so a second 'create' with the same --name would
    otherwise replace the first one's configuration without any warning --
    same risk (and same GET-before-PUT guard) as azext-aigateway's
    'mcp create' ResourceExistsError check. Use 'connector update' to
    intentionally change an existing connector.
    """

    def pre_operations(self):
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        connector_name = _arg_value(self.ctx.args.connector_name)
        existing = _cli_invoke(
            self.cli_ctx, "sre", "agent", "connector", "show",
            "--agent-name", agent_name, "--resource-group", resource_group,
            "--name", connector_name, allow_missing=True,
        )
        if existing is not None:
            raise ResourceExistsError(
                f"A connector named '{connector_name}' already exists on agent "
                f"'{agent_name}'. Use 'az sre agent connector update' to change "
                "it, or choose another --name."
            )
        super().pre_operations()


@register_command("sre agent connector create")
class ConnectorCreate(
    _DataConnectorTypeArgMixin,
    _ConnectorConvenienceArgsMixin,
    _ConnectorExistenceGuardMixin,
    _GeneratedConnectorCreate,
):
    """Create an Agent Connector."""

    _args_schema = None


@register_command("sre agent connector update")
class ConnectorUpdate(_DataConnectorTypeArgMixin, _GeneratedConnectorUpdate):
    """Update an Agent Connector."""

    _args_schema = None


# Consent-flow surfacing (issue #10). Confirmed via direct inspection of
# AAPT-SREAgent-ControlPlane src/WebApi/Views/Version20261101Preview/
# DataConnectorView.cs (SetCommonPropertiesFromModel, lines 176-182) and
# src/ApiResources/DataModels/McpEntraOAuth/McpEntraConnectorReference.cs:
# for an EntraOAuth-authenticated Mcp connector, the ARM response's
# properties.extendedProperties dict always contains "authType":
# "EntraOAuth", plus an "entraOAuth" key that is null until the user
# completes the separate browser OAuth consent flow (handled by a
# different, non-ARM service -- src/AuthenticationEndpoint, route "sso",
# Mise-authenticated -- not something the CLI calls directly), and a
# McpEntraConnectorReference JSON object (ConnectorName/Endpoint/ClientId/
# Profile/Principal/etc., via ToPublicJson()) once consent is granted.
# This lets the CLI report consent status purely from data already on the
# existing ARM connector resource -- no new data-plane call needed.
def _connector_consent_status(extended_properties):
    if not isinstance(extended_properties, dict):
        return None
    auth_type = extended_properties.get("authType")
    if not isinstance(auth_type, str) or auth_type.strip().lower() != "entraoauth":
        return None
    return "Consented" if extended_properties.get("entraOAuth") else "PendingConsent"


def _annotate_connector_consent_status(connector):
    """Add a CLI-only consentStatus field to a connector response dict,
    computed from properties.extendedProperties.{authType,entraOAuth}.
    No-ops (leaves the dict unchanged) for connectors that are not
    EntraOAuth-authenticated -- e.g. Kusto/Outlook/Teams connectors, or
    Mcp connectors using a different auth type, have no consent step.
    """
    if not isinstance(connector, dict):
        return connector
    extended_properties = connector.get("extendedProperties")
    if not isinstance(extended_properties, dict):
        properties = connector.get("properties")
        if isinstance(properties, dict):
            extended_properties = properties.get("extendedProperties")
    status = _connector_consent_status(extended_properties)
    if status is not None:
        connector["consentStatus"] = status
    return connector


@register_command("sre agent connector show")
class ConnectorShow(_GeneratedConnectorShow):
    """Show the details of an Agent Connector, including OAuth consent
    status (consentStatus: Consented/PendingConsent) for EntraOAuth-backed
    Mcp connectors."""

    _args_schema = None

    def _output(self, *args, **kwargs):
        result = super()._output(*args, **kwargs)
        return _annotate_connector_consent_status(result)


@register_command("sre agent connector list")
class ConnectorList(_GeneratedConnectorList):
    """List an SRE Agent's Connectors, including OAuth consent status
    (consentStatus: Consented/PendingConsent) for EntraOAuth-backed Mcp
    connectors."""

    _args_schema = None

    EMPTY_GUIDANCE = (
        "No connectors found. Add one with 'az sre agent connector create "
        "--data-connector-type Mcp --github true' (or --mcp-endpoint/"
        "--file-path for other connector types)."
    )

    def _output(self, *args, **kwargs):
        # The generated List is paginated (AZ_SUPPORT_PAGINATION), so
        # _output() returns a (value_list, next_link) tuple here, not a
        # plain dict -- treating it as a dict (the previous version of this
        # method did `result.get("value")`) silently always skipped the
        # annotation step, since isinstance(tuple, dict) is False.
        value, next_link = super()._output(*args, **kwargs)
        if isinstance(value, list):
            value = [_annotate_connector_consent_status(item) for item in value]
        if not value and not next_link:
            logger.warning(self.EMPTY_GUIDANCE)
        return value, next_link


@register_command("sre agent show")
class Show(_GeneratedShow):
    """Show the details of an SRE Agent."""


@register_command("sre agent list")
class List(_GeneratedList):
    """List SRE Agents in a subscription or resource group."""


@register_command("sre agent delete")
class Delete(_GeneratedDelete):
    """Delete an SRE Agent."""


@register_command("sre agent start")
class Start(_GeneratedStart):
    """Start a stopped SRE Agent."""


@register_command("sre agent stop")
class Stop(_GeneratedStop):
    """Stop a running SRE Agent."""


@register_command("sre agent get-connection")
class GetConnection(AAZCommand):
    """Resolve and save an SRE Agent's data-plane connection.

    Reads the agent's control-plane resource (ARM), extracts the
    'agentEndpoint' property (the data-plane base URL, pattern
    'https://{name}--{id}.{hash}.{region}.azuresre.ai' -- see running notes
    section 1a), and writes it to a local connections file for the
    separate, standalone data-plane 'sre' CLI to read. Mirrors
    'az aks get-credentials' writing kubeconfig for kubectl: the control
    plane and data plane are two different CLIs/binaries by design (see
    running notes section 1), and this command is their only bridge.
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to connect to.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.data_plane_audience = AAZStrArg(
            options=["--data-plane-audience"],
            help=(
                "Audience used to request the data-plane access token. "
                "The data plane uses a separate token from the control "
                "plane -- see running notes section 1a."
            ),
            default="https://azuresre.dev",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        audience = _arg_value(self.ctx.args.data_plane_audience)

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{name}' in resource group '{resource_group}'."
            )
        properties = agent.get("properties") or {}
        endpoint = properties.get("agentEndpoint")
        if not endpoint:
            raise CLIError(
                f"Agent '{name}' has no 'agentEndpoint' yet -- it may still "
                "be provisioning. Check 'az sre agent show' for "
                "'provisioningState'."
            )

        connections = {}
        if os.path.exists(_CONNECTIONS_FILE):
            try:
                with open(_CONNECTIONS_FILE, "r", encoding="utf-8") as handle:
                    connections = json.load(handle)
            except (OSError, json.JSONDecodeError) as ex:
                logger.warning(
                    "Could not read existing %s (%s); it will be overwritten.",
                    _CONNECTIONS_FILE, ex,
                )
                connections = {}
        key = f"{resource_group}/{name}"
        connections[key] = {
            "name": name,
            "resourceGroup": resource_group,
            "agentEndpoint": endpoint,
            "dataPlaneAudience": audience,
        }
        os.makedirs(os.path.dirname(_CONNECTIONS_FILE), exist_ok=True)
        with open(_CONNECTIONS_FILE, "w", encoding="utf-8") as handle:
            json.dump(connections, handle, indent=2)
        logger.warning("Merged '%s' connection into %s", key, _CONNECTIONS_FILE)

        return {
            "name": name,
            "resourceGroup": resource_group,
            "agentEndpoint": endpoint,
            "dataPlaneAudience": audience,
            "connectionsFile": _CONNECTIONS_FILE,
        }


@register_command("sre agent list-usage")
class ListUsage(AAZCommand):
    """List monthly or daily agent-unit usage for an SRE Agent.

    Wraps the dedicated 'usages'/'dailyusages' read-only ARM child
    collections (confirmed real in running notes section 1a) -- these are
    plain GETs with no Create/Update verb, so aaz-dev-tools has nothing to
    anchor a generated command group on. Hand-written the same way
    azext-aigateway wraps metrics it has no generated recipe for.
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to report usage for.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.daily = AAZBoolArg(
            options=["--daily"],
            help="Report daily usage (dailyusages) instead of monthly (usages).",
            default=False,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        daily = _arg_value(self.ctx.args.daily)

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{name}' in resource group '{resource_group}'."
            )
        resource_id = agent.get("id")
        if not resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{name}'.")

        suffix = "dailyusages" if daily else "usages"
        return _arm_request(
            self.cli_ctx, "GET", f"{resource_id}/{suffix}", API_VERSION,
        )


@register_command_group("sre agent")
class _AgentGroup(AAZCommandGroup):
    """Commands for managing SRE Agent resources (control plane)."""


@register_command("sre agent grant-access")
class GrantAccess(AAZCommand):
    """Grant a built-in SRE Agent RBAC role to a user, group, or principal.

    Thin convenience wrapper over 'az role assignment create' that builds
    the agent's full resource-ID scope for you (see running notes section
    0's "Role assignment" row) -- not a new ARM operation, just a shortcut
    so callers do not need to construct the scope string by hand.
    """

    _args_schema = None

    # Real built-in role names confirmed live via
    # `az role definition list --query "[?contains(roleName, 'SRE Agent')].roleName"`:
    # SRE Agent Reader, SRE Agent Administrator, SRE Agent Standard User, SRE Agent Author.
    # (Earlier draft wrongly used "SRE Agent User" and the generic ARM "Reader" role --
    # the latter grants ARM-level visibility only, NOT data-plane agent access; the
    # data-plane UI explicitly rejects Owner/Contributor/plain-Reader and requires one
    # of these SRE-Agent-specific roles.)
    _ROLES = {
        "admin": "SRE Agent Administrator",
        "user": "SRE Agent Standard User",
        "author": "SRE Agent Author",
        "reader": "SRE Agent Reader",
    }

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to grant access to.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.role = AAZStrArg(
            options=["--role"],
            help="Built-in role to grant: 'admin', 'user', 'author', or 'reader'.",
            required=True,
            enum={key: key for key in cls._ROLES},
        )
        schema.assignee = AAZStrArg(
            options=["--assignee"],
            help="User, group, or service principal object ID/UPN to grant the role to.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        role_key = _arg_value(self.ctx.args.role)
        assignee = _arg_value(self.ctx.args.assignee)
        role_name = self._ROLES[role_key]

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{name}' in resource group '{resource_group}'."
            )
        resource_id = agent.get("id")
        if not resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{name}'.")

        return invoke(
            "role", "assignment", "create",
            "--role", role_name,
            "--assignee", assignee,
            "--scope", resource_id,
        )


@register_command("sre agent update-network")
class UpdateNetwork(AAZCommand):
    """Configure VNet injection and sandbox egress for an SRE Agent (preview).

    Hand-written, NOT generated -- there is no public swagger for the
    api-version that actually supports these fields in production
    (2026-11-01-preview; see NETWORK_API_VERSION comment above). Does a
    real ARM read-modify-write (GET then full PUT, matching the pattern
    the generated 'agent update' command itself uses for every other
    property) directly against that api-version, merging only the
    networking properties the caller actually supplied and leaving
    everything else on the resource untouched.
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to configure networking on.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)

        schema.vnet_configuration = AAZObjectArg(
            options=["--vnet-configuration"],
            help=(
                "VNet injection for the agent itself. Shorthand JSON, e.g. "
                "--vnet-configuration \"{subnet-resource-id:/subscriptions/.../subnets/mysubnet}\"."
            ),
        )
        vnet_configuration = schema.vnet_configuration
        vnet_configuration.subnet_resource_id = AAZStrArg(
            options=["subnet-resource-id"],
            help="Resource ID of a delegated subnet (Microsoft.Network/virtualNetworks/subnets) for the agent.",
        )

        schema.sandbox_configuration = AAZObjectArg(
            options=["--sandbox-configuration"],
            help=(
                "Sandbox egress/package configuration for code the agent runs. Shorthand "
                "JSON, e.g. --sandbox-configuration \"{egress:{mode:Limited,allowed-hosts:[example.com]}}\"."
            ),
        )
        sandbox_configuration = schema.sandbox_configuration
        sandbox_configuration.egress = AAZObjectArg(
            options=["egress"],
            help="Egress configuration for the agent's sandbox.",
        )
        sandbox_configuration.packages = AAZListArg(
            options=["packages"],
            help="Packages to pre-install in the sandbox.",
        )
        sandbox_configuration.packages.Element = AAZObjectArg()
        package_element = sandbox_configuration.packages.Element
        package_element.name = AAZStrArg(options=["name"], help="Package name.")
        package_element.version = AAZStrArg(options=["version"], help="Package version.")
        package_element.package_manager = AAZStrArg(
            options=["package-manager"],
            help="Package manager: pip, npm, or nuget.",
        )

        egress = sandbox_configuration.egress
        egress.mode = AAZStrArg(
            options=["mode"],
            help="Sandbox egress mode.",
            enum={"Unrestricted": "Unrestricted", "Limited": "Limited", "AzureVNet": "AzureVNet"},
        )
        egress.allow_http_mcp_server_network_access = AAZBoolArg(
            options=["allow-http-mcp-server-network-access"],
            help="Allow the sandbox to reach HTTP MCP servers over the network.",
        )
        egress.allowed_hosts = AAZListArg(
            options=["allowed-hosts"],
            help="Hosts the sandbox is allowed to reach when in Limited mode.",
        )
        egress.allowed_hosts.Element = AAZStrArg()
        egress.allowed_registries = AAZListArg(
            options=["allowed-registries"],
            help="Package registries the sandbox is allowed to reach (e.g. pypi, npmjs, nuget-org, ubuntu).",
        )
        egress.allowed_registries.Element = AAZStrArg()
        egress.allowed_code_repositories = AAZListArg(
            options=["allowed-code-repositories"],
            help="Code repository hosts the sandbox is allowed to reach (e.g. Github, GithubEnterprise, AzureDevOps, GitLab).",
        )
        egress.allowed_code_repositories.Element = AAZStrArg()
        egress.vnet_configuration = AAZObjectArg(
            options=["vnet-configuration"],
            help="VNet-specific egress configuration (distinct from the top-level --vnet-configuration, which is for the agent itself).",
        )
        egress.vnet_configuration.use_private_dns_resolution = AAZBoolArg(
            options=["use-private-dns-resolution"],
            help="Use private DNS resolution for sandbox VNet egress.",
        )
        egress.http_proxy = AAZObjectArg(
            options=["http-proxy"],
            help="Forward-proxy endpoints for sandbox outbound HTTP/HTTPS traffic.",
        )
        egress.http_proxy.http_url = AAZStrArg(options=["http-url"], help="Proxy URL for plain HTTP.")
        egress.http_proxy.https_url = AAZStrArg(options=["https-url"], help="Proxy URL for HTTPS.")
        egress.http_proxy.no_proxy = AAZListArg(
            options=["no-proxy"],
            help="Hosts excluded from the proxy.",
        )
        egress.http_proxy.no_proxy.Element = AAZStrArg()

        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        vnet_configuration = _arg_value(self.ctx.args.vnet_configuration)
        sandbox_configuration = _arg_value(self.ctx.args.sandbox_configuration)

        if vnet_configuration is None and sandbox_configuration is None:
            raise CLIError(
                "Specify at least one of --vnet-configuration or --sandbox-configuration."
            )

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{name}' in resource group '{resource_group}'."
            )
        resource_id = agent.get("id")
        if not resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{name}'.")

        # Re-GET at the networking-capable api-version rather than reusing
        # the 2026-01-01 'show' response above, since that response won't
        # contain (and would silently drop on PUT) any networking fields
        # already set on the resource by another caller.
        current = _arm_request(self.cli_ctx, "GET", resource_id, NETWORK_API_VERSION)
        if not isinstance(current, dict):
            raise ResourceNotFoundError(
                f"Could not re-resolve SRE Agent '{name}' at api-version {NETWORK_API_VERSION}."
            )
        properties = current.setdefault("properties", {})
        if vnet_configuration is not None:
            properties["vnetConfiguration"] = _camelize_keys(vnet_configuration)
        if sandbox_configuration is not None:
            properties["sandboxConfiguration"] = _camelize_keys(sandbox_configuration)

        return _arm_request(self.cli_ctx, "PUT", resource_id, NETWORK_API_VERSION, body=current)


# --------------------------------------------------------------------------------------------
# "Runbook" / agent extensions (subagents, tools, skills, scheduledTasks,
# incidentFilters, commonPrompts, hooks, incidentHandlers, httpTriggers,
# repositories, pluginMarketplaces, pluginInstallations, githubAuths,
# azureDevOpsAuths, globalSettings) -- Paul's P0 prerequisite for threads/
# incidents, previously blocked on "do these even exist as control-plane
# resources?" (running notes section 24). Resolved in section 28: they are
# real, ARM-authenticated proxy endpoints
# (.../providers/Microsoft.App/agents/{agentName}/{extensionType}[/{name}])
# that the control plane forwards to the agent's data-plane cluster, but
# they are NOT modeled as standard ARM resource types -- no public swagger
# covers them, so aaz-dev could never generate commands for them. Found and
# confirmed directly in the internal AAPT-SREAgent-ControlPlane repo:
#   - src/WebApi/Controllers/Version20261101Preview/AgentExtensionsApiController.cs
#     (route + the authoritative regex of valid extensionType values)
#   - src/Services/Services/AgentExtensionsApiService.cs's GetExtensionTypes()
#     (the canonical ApiType/ExtensionType pairs, reproduced below)
#   - src/WebApi/ApiCalls/Agents.http (real example request/response bodies)
# Hand-written the same way update-network is: no codegen, _arm_request
# directly, re-verify against the real swagger once one is ever published.
# --------------------------------------------------------------------------------------------

EXTENSION_API_VERSION = "2026-11-01-preview"

# Mirrors AgentExtensionsApiService.GetExtensionTypes() exactly (ApiType is
# the internal/service-side name, unused here -- CLI only needs the public
# ExtensionType strings, which are also what the ARM route's regex accepts).
EXTENSION_TYPES = [
    "subagents",
    "tools",
    "skills",
    "scheduledTasks",
    "incidentFilters",
    "commonPrompts",
    "hooks",
    "incidentHandlers",
    "httpTriggers",
    "repositories",
    "pluginMarketplaces",
    "pluginInstallations",
    "githubAuths",
    "azureDevOpsAuths",
    "globalSettings",
]


def _extension_type_arg():
    return AAZStrArg(
        options=["--extension-type", "--type"],
        help="Kind of agent extension. One of: " + ", ".join(EXTENSION_TYPES) + ".",
        required=True,
        enum={t: t for t in EXTENSION_TYPES},
    )


# Per-extension-type inner JSON shape, confirmed where noted. The control-
# plane repo's own route (AgentExtensionsApiController.cs) is a pure
# base64 pass-through with zero shape validation -- it never tells us if
# a payload is malformed until the data-plane cluster rejects it. We
# tighten client-side only for shapes we've actually confirmed from real
# source (see issue #13 -- 14 of 15 extension types confirmed via
# sreagent-runtime authoritative source + live round-trips; only
# 'subagents' remains unconfirmed, believed server/portal-managed).
#
# commonPrompts: CORRECTED after live verification against the real
# mytestagent data-plane (2026-10-25). The earlier reading of
# DebugApp/Client/ModelPromptsViewer.tsx's TS prop type
# (`commonPrompts?: string | Array<{ name: string; content: string }>`) was
# WRONG for the per-resource wire shape -- that type describes an
# aggregated, multi-resource UI display value, not what a single PUT
# accepts. Live testing (PUT with --debug + raw `az rest` probes against
# mytestagent) proved: the real data-plane requires the decoded root value
# to be a JSON OBJECT for every extension type (a bare array is always
# rejected as "invalid or unrecognized property", confirmed to repro for
# commonPrompts AND tools with []), and for commonPrompts specifically the
# only recognized field is a single string "prompt" -- {"name": ...,
# "content": ...} round-trips back as {"prompt": ""} (silently dropped,
# not rejected), while {"prompt": "..."} round-trips byte-for-byte. The
# ARM resource name (e.g. "default") is the prompt's identifier; "prompt"
# is its content.
def _validate_common_prompts_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type commonPrompts must be a JSON "
            "object of the form {\"prompt\": \"...\"} (confirmed live "
            "against a real agent -- the ARM resource name is the "
            "prompt's identifier, 'prompt' holds its string content)."
        )
    if "prompt" not in parsed or not isinstance(parsed["prompt"], str):
        raise CLIError(
            "--value for --extension-type commonPrompts must include a "
            "string 'prompt' field."
        )


# globalSettings: confirmed via a REAL end-to-end round-trip integration
# test (not a pass-through mock) --
# Tests.Integration/Version20261101Preview/GlobalSettingsExtensionTests.cs,
# "Configured" const (lines 32-37) -- the control-plane team's own test
# payload that is base64-encoded, PUT, decoded server-side, and asserted
# byte-for-byte equal on GET/list. All fields are optional (the test also
# exercises "{}" as valid), so we only type-check fields if present.
def _validate_global_settings_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type globalSettings must be a JSON "
            "object (confirmed via GlobalSettingsExtensionTests.cs's "
            "real round-trip test payload)."
        )

    def _require_str_list(obj, key, path):
        if key not in obj:
            return
        value = obj[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CLIError(f"{path}.{key} must be a JSON array of strings.")

    if "toolPermissions" in parsed:
        tp = parsed["toolPermissions"]
        if not isinstance(tp, dict):
            raise CLIError("--value.toolPermissions must be a JSON object with optional 'allow'/'ask'/'deny' arrays.")
        for key in ("allow", "ask", "deny"):
            _require_str_list(tp, key, "--value.toolPermissions")

    def _require_name_enabled_list(obj, key):
        if key not in obj:
            return
        value = obj[key]
        if not isinstance(value, list):
            raise CLIError(f"--value.{key} must be a JSON array of {{\"name\": ..., \"enabled\": ...}} objects.")
        for idx, item in enumerate(value):
            if not isinstance(item, dict) or "name" not in item or "enabled" not in item:
                raise CLIError(f"--value.{key}[{idx}] must be an object with 'name' and 'enabled' fields.")
            if not isinstance(item["name"], str) or not isinstance(item["enabled"], bool):
                raise CLIError(f"--value.{key}[{idx}].name must be a string and .enabled must be a boolean.")

    _require_name_enabled_list(parsed, "toolStatuses")
    _require_name_enabled_list(parsed, "skillStatuses")

    if "customInstructions" in parsed and not isinstance(parsed["customInstructions"], str):
        raise CLIError("--value.customInstructions must be a string.")

    if "approvalExpirationSetting" in parsed:
        aes = parsed["approvalExpirationSetting"]
        if not isinstance(aes, dict):
            raise CLIError("--value.approvalExpirationSetting must be a JSON object.")
        if "enabled" in aes and not isinstance(aes["enabled"], bool):
            raise CLIError("--value.approvalExpirationSetting.enabled must be a boolean.")
        if "approvalExpirationInMinutes" in aes and not isinstance(aes["approvalExpirationInMinutes"], (int, float)):
            raise CLIError("--value.approvalExpirationSetting.approvalExpirationInMinutes must be a number.")


def _validate_plugin_marketplaces_shape(parsed):
    """Confirmed via AAPT-SREAgent-ControlPlane's Agents.http worked example
    and a real base64-decoded payload; live create/show round-trip against
    a test agent confirmed the shape passes service-side validation (it
    fails later at Kubernetes provisioning in this test environment, which
    is an infra limitation, not a shape problem)."""
    if not isinstance(parsed, dict):
        raise CLIError("--value for --extension-type pluginMarketplaces must be a JSON object.")
    if "sourceType" in parsed and not isinstance(parsed["sourceType"], str):
        raise CLIError("--value.sourceType must be a string (e.g. \"github\").")
    if "sourceUrl" in parsed and not isinstance(parsed["sourceUrl"], str):
        raise CLIError("--value.sourceUrl must be a string.")
    if "owner" in parsed:
        owner = parsed["owner"]
        if not isinstance(owner, dict) or ("name" in owner and not isinstance(owner["name"], str)):
            raise CLIError("--value.owner must be a JSON object with a string 'name'.")
    if "description" in parsed and not isinstance(parsed["description"], str):
        raise CLIError("--value.description must be a string.")


def _validate_plugin_installations_shape(parsed):
    """Confirmed via a real live create/show round-trip against a test
    agent (Agents.http's worked example payload), which the service
    accepted and echoed back enriched with defaults (autoUpdate,
    mcpConnectorStatus, source.credentials/ref/sha/url)."""
    if not isinstance(parsed, dict):
        raise CLIError("--value for --extension-type pluginInstallations must be a JSON object.")
    if "marketplaceName" in parsed and not isinstance(parsed["marketplaceName"], str):
        raise CLIError("--value.marketplaceName must be a string.")
    if "pluginName" in parsed and not isinstance(parsed["pluginName"], str):
        raise CLIError("--value.pluginName must be a string.")
    if "source" in parsed:
        source = parsed["source"]
        if not isinstance(source, dict):
            raise CLIError("--value.source must be a JSON object (e.g. {\"type\": \"relative\", \"repo\": \"owner/repo\"}).")
        if "type" in source and not isinstance(source["type"], str):
            raise CLIError("--value.source.type must be a string.")
        if "repo" in source and not isinstance(source["repo"], str):
            raise CLIError("--value.source.repo must be a string.")


def _validate_incident_filters_shape(parsed):
    """Confirmed via AAPT-SREAgent-ControlPlane's real E2E scenario fixtures
    (PagerDutySetupFixture.cs, IcmSetupFixture.cs -- both run against a real
    data-plane environment and asserted a successful round trip there).
    Live create against our own test agent was rejected with a generic
    "extension configuration is invalid" error even after adding a matching
    Icm data connector -- consistent with needing real IcM team-identity
    resolution our sandbox tenant doesn't have (same category as the
    Dgrep/pluginMarketplaces environment-specific limitations), not a shape
    problem: the same payload shape is the one PagerDuty/Icm's own E2E
    tests use successfully."""
    if not isinstance(parsed, dict):
        raise CLIError("--value for --extension-type incidentFilters must be a JSON object.")
    if "incidentPlatform" in parsed and not isinstance(parsed["incidentPlatform"], str):
        raise CLIError("--value.incidentPlatform must be a string (e.g. \"Icm\", \"PagerDuty\").")
    if "incidentTypes" in parsed:
        it = parsed["incidentTypes"]
        if not isinstance(it, list) or not all(isinstance(v, str) for v in it):
            raise CLIError("--value.incidentTypes must be a JSON array of strings.")
    if "titleContains" in parsed and not isinstance(parsed["titleContains"], str):
        raise CLIError("--value.titleContains must be a string.")
    if "agentMode" in parsed and not isinstance(parsed["agentMode"], str):
        raise CLIError("--value.agentMode must be a string (e.g. \"autonomous\").")
    if "isEnabled" in parsed and not isinstance(parsed["isEnabled"], bool):
        raise CLIError("--value.isEnabled must be a boolean.")
    for list_field in ("owningTeamIds", "handlingAgents"):
        if list_field in parsed:
            value = parsed[list_field]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise CLIError(f"--value.{list_field} must be a JSON array of strings.")


def _validate_incident_handlers_shape(parsed):
    """Confirmed via AAPT-SREAgent-ControlPlane's real E2E scenario fixtures
    (PagerDutySetupFixture.cs's handlerConfig, asserted round-trip against a
    real environment including server-populated incidentFilterId/
    incidentProcessingGuide/tools fields). Live create blocked in our
    sandbox the same way incidentFilters is (see
    _validate_incident_filters_shape) -- not a shape problem."""
    if not isinstance(parsed, dict):
        raise CLIError("--value for --extension-type incidentHandlers must be a JSON object.")
    for str_field in ("id", "name", "description", "incidentFilterId", "customInstructions"):
        if str_field in parsed and not isinstance(parsed[str_field], str):
            raise CLIError(f"--value.{str_field} must be a string.")
    for list_field in ("incidentProcessingGuide", "tools", "incidents"):
        if list_field in parsed:
            value = parsed[list_field]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise CLIError(f"--value.{list_field} must be a JSON array of strings.")


def _require_str(obj, key, path):
    if key in obj and not isinstance(obj[key], str):
        raise CLIError(f"{path}.{key} must be a string.")


def _require_bool(obj, key, path):
    if key in obj and not isinstance(obj[key], bool):
        raise CLIError(f"{path}.{key} must be a boolean.")


def _require_str_list(obj, key, path):
    if key in obj:
        value = obj[key]
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise CLIError(f"{path}.{key} must be a JSON array of strings.")


# tools: confirmed via sreagent-runtime (the real SRE Agent runtime/CLI
# source, a strictly more authoritative source than the ARM control-plane
# proxy repo) -- Agent.Cli/Models/ToolSpecV2.cs (base/common fields,
# polymorphic on "type") + KustoToolSpecV2.cs/LinkToolSpecV2.cs/
# PythonToolSpecV2.cs/HttpClientToolSpecV2.cs (per-type fields). The CLI's
# YamlMember aliases are camelCase and line up 1:1 with other confirmed
# types' JsonPropertyName casing (see HookSpecV2), so these are used
# directly as the JSON wire field names.
def _validate_tools_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type tools must be a JSON object "
            "(confirmed via sreagent-runtime's ToolSpecV2 model)."
        )
    valid_types = ("KustoTool", "LinkTool", "PythonTool", "HttpClientTool")
    if "type" in parsed:
        if not isinstance(parsed["type"], str) or parsed["type"] not in valid_types:
            raise CLIError(f"--value.type must be one of: {', '.join(valid_types)}.")
    _require_str(parsed, "connector", "--value")
    _require_str(parsed, "toolMode", "--value")
    _require_str(parsed, "description", "--value")
    if "parameters" in parsed:
        params = parsed["parameters"]
        if not isinstance(params, list):
            raise CLIError("--value.parameters must be a JSON array of parameter objects.")
        for idx, p in enumerate(params):
            if not isinstance(p, dict):
                raise CLIError(f"--value.parameters[{idx}] must be a JSON object.")
            _require_str(p, "name", f"--value.parameters[{idx}]")
            _require_str(p, "type", f"--value.parameters[{idx}]")
            _require_str(p, "description", f"--value.parameters[{idx}]")
            _require_bool(p, "required", f"--value.parameters[{idx}]")
    tool_type = parsed.get("type")
    if tool_type == "KustoTool":
        _require_str(parsed, "database", "--value")
        _require_str(parsed, "query", "--value")
    elif tool_type == "LinkTool":
        _require_str(parsed, "template", "--value")
    elif tool_type == "PythonTool":
        _require_str(parsed, "functionCode", "--value")
        if "timeoutSeconds" in parsed and not isinstance(parsed["timeoutSeconds"], (int, float)):
            raise CLIError("--value.timeoutSeconds must be a number.")
        _require_str_list(parsed, "dependencies", "--value")
        _require_bool(parsed, "authEnabled", "--value")
        _require_str_list(parsed, "authScopes", "--value")
    elif tool_type == "HttpClientTool":
        _require_str(parsed, "url", "--value")
        if "method" in parsed:
            if not isinstance(parsed["method"], str) or parsed["method"].upper() not in (
                "GET", "POST", "PUT", "DELETE", "PATCH",
            ):
                raise CLIError("--value.method must be one of: GET, POST, PUT, DELETE, PATCH.")
        _require_str(parsed, "body", "--value")
        if "headers" in parsed:
            headers = parsed["headers"]
            if not isinstance(headers, list):
                raise CLIError("--value.headers must be a JSON array of {\"key\": ..., \"value\": ...} objects.")
            for idx, h in enumerate(headers):
                if not isinstance(h, dict):
                    raise CLIError(f"--value.headers[{idx}] must be a JSON object.")
                _require_str(h, "key", f"--value.headers[{idx}]")
                _require_str(h, "value", f"--value.headers[{idx}]")
        if "auth" in parsed:
            auth = parsed["auth"]
            if not isinstance(auth, dict):
                raise CLIError("--value.auth must be a JSON object.")
            _require_str(auth, "dataconnector", "--value.auth")
            _require_str(auth, "scope", "--value.auth")
        if "timeout_seconds" in parsed and not isinstance(parsed["timeout_seconds"], (int, float)):
            raise CLIError("--value.timeout_seconds must be a number.")


# skills: confirmed via sreagent-runtime Agent.Cli/Models/ExtendedSkillV2.cs
# (SkillSpecV2). The CLI's primary authoring format is SKILL.md with
# frontmatter (name/description/tools), but the API-facing fields map to
# description/tools/skillContent -- only description and tools are
# settable-looking JSON fields; skillContent is markdown body text.
def _validate_skills_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type skills must be a JSON object "
            "(confirmed via sreagent-runtime's SkillSpecV2 model)."
        )
    _require_str(parsed, "description", "--value")
    _require_str_list(parsed, "tools", "--value")
    _require_str(parsed, "skillContent", "--value")


# hooks: confirmed via sreagent-runtime Agent.Cli/Models/HookV2.cs
# (HookSpecV2/HookDefinitionModel) -- these fields carry explicit
# [JsonPropertyName] attributes confirming camelCase wire field names
# distinct from (but matching) the YAML aliases, the strongest evidence
# available for any type this session.
def _validate_hooks_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type hooks must be a JSON object "
            "(confirmed via sreagent-runtime's HookSpecV2/HookDefinitionModel, "
            "which carry explicit JsonPropertyName wire-field attributes)."
        )
    if "eventType" in parsed:
        if not isinstance(parsed["eventType"], str) or parsed["eventType"] not in ("Stop", "PostToolUse"):
            raise CLIError("--value.eventType must be \"Stop\" or \"PostToolUse\".")
    if "activationMode" in parsed:
        if not isinstance(parsed["activationMode"], str) or parsed["activationMode"] not in ("always", "onDemand"):
            raise CLIError("--value.activationMode must be \"always\" or \"onDemand\".")
    _require_str(parsed, "description", "--value")
    if "hook" in parsed:
        hook = parsed["hook"]
        if not isinstance(hook, dict):
            raise CLIError("--value.hook must be a JSON object.")
        if "type" in hook and (not isinstance(hook["type"], str) or hook["type"] not in ("prompt", "command")):
            raise CLIError("--value.hook.type must be \"prompt\" or \"command\".")
        for str_field in ("prompt", "command", "script", "matcher", "model", "failMode"):
            _require_str(hook, str_field, "--value.hook")
        if "timeout" in hook and not isinstance(hook["timeout"], (int, float)):
            raise CLIError("--value.hook.timeout must be a number.")
        if "maxRejections" in hook and not isinstance(hook["maxRejections"], (int, float)):
            raise CLIError("--value.hook.maxRejections must be a number.")
        _require_str_list(hook, "sources", "--value.hook")


# scheduledTasks: confirmed via sreagent-runtime
# Agent.Cli/Models/ScheduledTaskV2.cs's ScheduledTaskSpecV2 -- explicit
# doc comment there states these are exactly the fields the real
# "GET api/v2/extendedAgent/scheduledtasks" endpoint returns in each
# envelope's properties bag (server-owned runtime fields like status/
# executionHistory are intentionally excluded from the caller-owned spec).
def _validate_scheduled_tasks_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type scheduledTasks must be a JSON "
            "object (confirmed via sreagent-runtime's ScheduledTaskSpecV2 "
            "model, which documents these as exactly the fields the real "
            "v2 scheduledtasks API returns/accepts)."
        )
    for str_field in (
        "description", "cronExpression", "agentPrompt", "agent", "threadId",
        "notificationChannel", "modelTier", "agentMode",
    ):
        _require_str(parsed, str_field, "--value")
    for date_field in ("startTime", "endTime"):
        if date_field in parsed and not isinstance(parsed[date_field], str):
            raise CLIError(f"--value.{date_field} must be an ISO-8601 date-time string.")
    if "maxExecutions" in parsed and not isinstance(parsed["maxExecutions"], (int, float)):
        raise CLIError("--value.maxExecutions must be a number.")


# repositories: confirmed via sreagent-runtime
# Agent.Cli/Models/RepositoryV2.cs's own RepositoryV2.Validate() method,
# the most direct evidence available (actual shipped validation logic,
# not just a model shape guess).
def _validate_repositories_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type repositories must be a JSON "
            "object (confirmed via sreagent-runtime's RepositoryV2.Validate())."
        )
    if "url" not in parsed or not isinstance(parsed["url"], str):
        raise CLIError("--value.url is required and must be a string.")
    _require_str(parsed, "description", "--value")
    if "type" in parsed:
        if not isinstance(parsed["type"], str) or parsed["type"] not in ("GitHub", "AzureDevOps", "GitLab"):
            raise CLIError("--value.type must be \"GitHub\", \"AzureDevOps\", or \"GitLab\".")
    _require_str(parsed, "branch", "--value")
    _require_str_list(parsed, "sparseCheckoutPaths", "--value")
    if "feedCredentials" in parsed:
        feeds = parsed["feedCredentials"]
        if not isinstance(feeds, list):
            raise CLIError("--value.feedCredentials must be a JSON array.")
        for idx, feed in enumerate(feeds):
            if not isinstance(feed, dict):
                raise CLIError(f"--value.feedCredentials[{idx}] must be a JSON object.")
            if "orgName" not in feed or not isinstance(feed["orgName"], str):
                raise CLIError(f"--value.feedCredentials[{idx}].orgName is required and must be a string.")
            if "feedUrl" not in feed or not isinstance(feed["feedUrl"], str):
                raise CLIError(f"--value.feedCredentials[{idx}].feedUrl is required and must be a string.")
            if "feedType" not in feed or feed["feedType"] not in ("NuGet", "Npm", "Pip"):
                raise CLIError(f"--value.feedCredentials[{idx}].feedType must be \"NuGet\", \"Npm\", or \"Pip\".")
            if "pat" not in feed or not isinstance(feed["pat"], str):
                raise CLIError(f"--value.feedCredentials[{idx}].pat is required and must be a string.")


# githubAuths: confirmed via sreagent-runtime
# Agent.Cli/Models/GitHubAuthV2.cs's own GitHubAuthV2.Validate() method.
def _validate_github_auths_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type githubAuths must be a JSON "
            "object (confirmed via sreagent-runtime's GitHubAuthV2.Validate())."
        )
    auth_type = parsed.get("authType")
    if "authType" in parsed and auth_type not in ("Pat", "GitHubApp"):
        raise CLIError("--value.authType must be \"Pat\" or \"GitHubApp\".")
    if auth_type == "Pat" and ("pat" not in parsed or not isinstance(parsed["pat"], str)):
        raise CLIError("--value.pat is required and must be a string when --value.authType is \"Pat\".")
    if auth_type == "GitHubApp":
        if "clientId" not in parsed or not isinstance(parsed["clientId"], str):
            raise CLIError("--value.clientId is required and must be a string when --value.authType is \"GitHubApp\".")
        if "privateKeySecretUri" not in parsed or not isinstance(parsed["privateKeySecretUri"], str):
            raise CLIError(
                "--value.privateKeySecretUri is required and must be a string when "
                "--value.authType is \"GitHubApp\"."
            )
    _require_str(parsed, "keyVaultManagedIdentityId", "--value")


# azureDevOpsAuths: confirmed via sreagent-runtime
# Agent.Cli/Models/AzureDevOpsAuthV2.cs's own AzureDevOpsAuthV2.Validate()
# method.
def _validate_azure_devops_auths_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type azureDevOpsAuths must be a JSON "
            "object (confirmed via sreagent-runtime's "
            "AzureDevOpsAuthV2.Validate())."
        )
    auth_type = parsed.get("authType")
    if "authType" in parsed and auth_type not in ("Pat", "ManagedIdentity"):
        raise CLIError("--value.authType must be \"Pat\" or \"ManagedIdentity\".")
    if auth_type == "Pat" and ("pat" not in parsed or not isinstance(parsed["pat"], str)):
        raise CLIError("--value.pat is required and must be a string when --value.authType is \"Pat\".")
    if auth_type == "ManagedIdentity":
        if "identity" not in parsed or not isinstance(parsed["identity"], str):
            raise CLIError(
                "--value.identity is required and must be a string when "
                "--value.authType is \"ManagedIdentity\"."
            )
        has_client_id = "federatedClientId" in parsed and parsed["federatedClientId"]
        has_tenant_id = "federatedTenantId" in parsed and parsed["federatedTenantId"]
        if bool(has_client_id) != bool(has_tenant_id):
            raise CLIError(
                "--value.federatedClientId and --value.federatedTenantId must "
                "both be provided or both be omitted."
            )


# httpTriggers: confirmed via sreagent-runtime
# Agent.Web/Controllers/v1/HttpTriggersController.cs's
# UpdateHttpTriggerApiRequest/HttpTriggerArmPutRequest records -- this is
# the strongest evidence of any type this session: the controller's own
# ARM-alias route comment states verbatim "The control plane wraps every
# extension payload as { name, type, properties } before forwarding it to
# the runtime, so the trigger fields arrive nested under properties",
# i.e. the exact base64-decoded --value shape our CLI constructs IS this
# inner properties/UpdateHttpTriggerApiRequest object.
def _validate_http_triggers_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value for --extension-type httpTriggers must be a JSON "
            "object (confirmed via sreagent-runtime's "
            "HttpTriggersController ARM-alias route, whose own code "
            "comment documents this exact shape)."
        )
    for str_field in ("name", "description", "agentPrompt", "agent", "modelTier", "threadId"):
        _require_str(parsed, str_field, "--value")
    if "agentMode" in parsed:
        if not isinstance(parsed["agentMode"], str) or parsed["agentMode"] not in (
            "readonly", "review", "autonomous",
        ):
            raise CLIError("--value.agentMode must be \"readonly\", \"review\", or \"autonomous\".")


EXTENSION_VALUE_VALIDATORS = {
    "commonPrompts": _validate_common_prompts_shape,
    "globalSettings": _validate_global_settings_shape,
    "pluginMarketplaces": _validate_plugin_marketplaces_shape,
    "pluginInstallations": _validate_plugin_installations_shape,
    "incidentFilters": _validate_incident_filters_shape,
    "incidentHandlers": _validate_incident_handlers_shape,
    "tools": _validate_tools_shape,
    "skills": _validate_skills_shape,
    "hooks": _validate_hooks_shape,
    "scheduledTasks": _validate_scheduled_tasks_shape,
    "repositories": _validate_repositories_shape,
    "githubAuths": _validate_github_auths_shape,
    "azureDevOpsAuths": _validate_azure_devops_auths_shape,
    "httpTriggers": _validate_http_triggers_shape,
}


def _encode_extension_value(raw_value, extension_type=None):
    """Base64-encode a user-supplied JSON string for properties.value, the
    wire format confirmed in Agents.http (e.g. pluginMarketplaces' example
    body). Validates the input is JSON first so typos fail fast client-side
    instead of as an opaque base64 blob the service will silently accept
    but the data plane can't parse. Additionally applies a per-type shape
    check for any extension_type we have a confirmed real shape for (see
    EXTENSION_VALUE_VALIDATORS) -- unconfirmed types are passed through
    with only the baseline JSON-syntax check.
    """
    import base64

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError) as ex:
        raise CLIError(
            f"--value must be a JSON document (it is base64-encoded and sent "
            f"as-is to the agent's data plane): {ex}"
        ) from ex
    validator = EXTENSION_VALUE_VALIDATORS.get(extension_type)
    if validator is not None:
        validator(parsed)
    return base64.b64encode(raw_value.encode("utf-8")).decode("ascii")


def _decode_extension_envelope(envelope):
    """Best-effort base64-decode (and, if it parses, JSON-parse) an
    extension envelope's properties.value for human-readable display.
    Falls back to leaving the raw base64 untouched if it's not valid
    UTF-8/JSON -- some extension types may carry opaque/binary payloads.
    """
    import base64
    import contextlib

    if not isinstance(envelope, dict):
        return envelope
    properties = envelope.get("properties")
    if not isinstance(properties, dict):
        return envelope
    value = properties.get("value")
    if not isinstance(value, str):
        return envelope
    with contextlib.suppress(Exception):
        decoded_bytes = base64.b64decode(value)
        decoded_text = decoded_bytes.decode("utf-8")
        with contextlib.suppress(ValueError):
            properties["value"] = json.loads(decoded_text)
            return envelope
        properties["value"] = decoded_text
    return envelope


@register_command_group("sre agent extension")
class _ExtensionGroup(AAZCommandGroup):
    """Commands for an SRE Agent's 'runbook' extensions -- subagents, tools,
    skills, scheduled tasks, incident filters/handlers, common prompts,
    hooks, HTTP triggers, repositories, plugin marketplaces/installations,
    GitHub/Azure DevOps auths, and global settings (preview).

    Hand-written: these are real ARM-authenticated proxy endpoints the
    control plane forwards to the agent's data plane, but they are not
    modeled as ARM resource types in any public swagger, so there is no
    generated command surface to subclass (see the module-level comment
    above this command group for citations).
    """


@register_command("sre agent extension create")
class ExtensionCreate(AAZCommand):
    """Create or update an SRE Agent extension (subagent/tool/skill/etc.).

    By default, refuses to silently overwrite an existing extension of the
    same --extension-type/--extension-name (there is no separate 'extension
    update' command, so an unguarded PUT here would clobber an existing
    repo/auth/tool registration with no warning). Pass --overwrite to update
    an existing one intentionally.
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"],
            help="Name of the SRE Agent.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_type = _extension_type_arg()
        schema.extension_name = AAZStrArg(
            options=["--extension-name", "--name", "-n"],
            help="Name of the extension instance.",
            required=True,
        )
        schema.value = AAZStrArg(
            options=["--value"],
            help=(
                "Extension configuration as a JSON document (the CLI "
                "base64-encodes it for you -- the wire format is "
                "properties.value = base64(json), confirmed via the "
                "internal control-plane repo's Agents.http examples). For "
                "--extension-type commonPrompts, the confirmed shape is a "
                "JSON object {\"prompt\": \"...\"} (one prompt per ARM "
                "resource name, e.g. 'default'). "
                "For globalSettings, the confirmed shape is a JSON object "
                "with optional toolPermissions/toolStatuses/skillStatuses/"
                "customInstructions/approvalExpirationSetting fields. "
                "14 of 15 extension types now have confirmed inner shapes "
                "(source-cited in custom.py's _validate_*_shape functions; "
                "12 also live-round-tripped against a real agent) -- only "
                "'subagents' remains unconfirmed (believed server/portal-"
                "managed, not CLI-creatable). See issue #13 for the full "
                "findings and evidence."
            ),
            required=True,
        )
        schema.overwrite = AAZBoolArg(
            options=["--overwrite"],
            help="Allow replacing an existing extension of the same "
            "--extension-type/--extension-name. Without this flag, "
            "'extension create' refuses to overwrite an existing extension.",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_type = _arg_value(self.ctx.args.extension_type)
        extension_name = _arg_value(self.ctx.args.extension_name)
        raw_value = _arg_value(self.ctx.args.value)
        overwrite = _arg_value(getattr(self.ctx.args, "overwrite", None))

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", agent_name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{agent_name}' in resource group '{resource_group}'."
            )
        agent_resource_id = agent.get("id")
        if not agent_resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{agent_name}'.")

        resource_id = f"{agent_resource_id}/{extension_type}/{extension_name}"
        if not overwrite:
            existing = _arm_request(
                self.cli_ctx, "GET", resource_id, EXTENSION_API_VERSION, missing_ok=True
            )
            if existing is not None:
                raise ResourceExistsError(
                    f"An extension named '{extension_name}' of type "
                    f"'{extension_type}' already exists on agent '{agent_name}'. "
                    "Pass --overwrite to replace it intentionally, or choose "
                    "another --extension-name."
                )
        body = {
            "type": f"microsoft.app/agents/{extension_type}",
            "properties": {"value": _encode_extension_value(raw_value, extension_type)},
        }
        result = _arm_request(self.cli_ctx, "PUT", resource_id, EXTENSION_API_VERSION, body=body)
        return _decode_extension_envelope(result)


@register_command("sre agent extension show")
class ExtensionShow(AAZCommand):
    """Show an SRE Agent extension."""

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"],
            help="Name of the SRE Agent.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_type = _extension_type_arg()
        schema.extension_name = AAZStrArg(
            options=["--extension-name", "--name", "-n"],
            help="Name of the extension instance.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_type = _arg_value(self.ctx.args.extension_type)
        extension_name = _arg_value(self.ctx.args.extension_name)

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", agent_name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{agent_name}' in resource group '{resource_group}'."
            )
        agent_resource_id = agent.get("id")
        if not agent_resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{agent_name}'.")

        resource_id = f"{agent_resource_id}/{extension_type}/{extension_name}"
        result = _arm_request(
            self.cli_ctx, "GET", resource_id, EXTENSION_API_VERSION, missing_ok=True
        )
        if result is None:
            raise ResourceNotFoundError(
                f"Extension '{extension_name}' of type '{extension_type}' not found on agent '{agent_name}'."
            )
        return _decode_extension_envelope(result)


@register_command("sre agent extension list")
class ExtensionList(AAZCommand):
    """List an SRE Agent's extensions of a given type."""

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"],
            help="Name of the SRE Agent.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_type = _extension_type_arg()
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_type = _arg_value(self.ctx.args.extension_type)

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", agent_name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{agent_name}' in resource group '{resource_group}'."
            )
        agent_resource_id = agent.get("id")
        if not agent_resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{agent_name}'.")

        resource_id = f"{agent_resource_id}/{extension_type}"
        result = _arm_request(self.cli_ctx, "GET", resource_id, EXTENSION_API_VERSION)
        if isinstance(result, dict) and isinstance(result.get("value"), list):
            result["value"] = [_decode_extension_envelope(item) for item in result["value"]]
            if not result["value"]:
                logger.warning(
                    "No '%s' extensions found on agent '%s'. Add one with "
                    "'az sre agent extension create --extension-type %s "
                    "--extension-name <name> --value <json>' (or "
                    "'az sre agent repo connect' for repositories/"
                    "githubAuths/azureDevOpsAuths).",
                    extension_type, agent_name, extension_type,
                )
        return result


@register_command("sre agent extension delete")
class ExtensionDelete(AAZCommand):
    """Delete an SRE Agent extension."""

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"],
            help="Name of the SRE Agent.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_type = _extension_type_arg()
        schema.extension_name = AAZStrArg(
            options=["--extension-name", "--name", "-n"],
            help="Name of the extension instance.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_type = _arg_value(self.ctx.args.extension_type)
        extension_name = _arg_value(self.ctx.args.extension_name)

        invoke = partial(_cli_invoke, self.cli_ctx)
        agent = invoke(
            "sre", "agent", "show", "--name", agent_name, "--resource-group", resource_group,
        )
        if not isinstance(agent, dict):
            raise ResourceNotFoundError(
                f"Could not resolve SRE Agent '{agent_name}' in resource group '{resource_group}'."
            )
        agent_resource_id = agent.get("id")
        if not agent_resource_id:
            raise CLIError(f"Could not resolve the resource ID of agent '{agent_name}'.")

        resource_id = f"{agent_resource_id}/{extension_type}/{extension_name}"
        return _arm_request(self.cli_ctx, "DELETE", resource_id, EXTENSION_API_VERSION, missing_ok=True)


# --------------------------------------------------------------------------------------------
# "sre agent repo connect" -- a one-command golden path for the GitHub/Azure
# DevOps repo-connection flow, modeled directly on azext-aigateway's
# "az aigateway mcp create --github true" (custom.py's McpCreate.pre_operations
# + _onboarding.py's github_mcp_endpoints/_github_cli_token). That command
# collapses what would otherwise be a manual PAT-copy-paste + hand-built JSON
# payload into one flag because it already has a locally authenticated
# credential available (gh auth token) and a canonical payload shape it can
# build for the user.
#
# Before this command, connecting one repo required two raw
# "sre agent extension create" calls the user had to build by hand:
#   1. githubAuths/azureDevOpsAuths, with a manually-pasted PAT
#   2. repositories, with a hand-written JSON --value
# This command does both, using a token it fetches itself -- `gh auth token`
# for GitHub (identical helper to aigateway's), or a freshly minted
# Azure DevOps PAT via the vssps.dev.azure.com REST API for Azure DevOps
# (ADO PAT creation has no `az devops` command; see running notes section on
# ADO PAT generation). Nothing here bypasses the real extension model --
# it is sugar that calls "sre agent extension create" twice with payloads it
# builds instead of asking the user to build them.
# --------------------------------------------------------------------------------------------

ADO_PAT_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"


def _github_cli_token(account=None):
    """Fetch the already-authenticated GitHub token from the GitHub CLI.

    Copied from azext-aigateway's custom.py._github_cli_token verbatim (same
    helper name/signature) so both extensions share one well-understood
    pattern for "borrow the user's existing `gh auth login` session instead
    of asking them to mint and paste a PAT."
    """
    import subprocess

    command = ["gh", "auth", "token", "--hostname", "github.com"]
    if account:
        command.extend(("--user", account))
    environment = os.environ.copy()
    environment.pop("GITHUB_TOKEN", None)
    try:
        result = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as ex:
        raise CLIError(
            "GitHub authentication is required. Run "
            "'gh auth login --hostname github.com', or pass --pat yourself."
        ) from ex
    token = result.stdout.strip()
    if not token:
        raise CLIError("GitHub CLI returned an empty credential.")
    return token


def _devops_pat_token(cli_ctx, organization, display_name):
    """Mint a short-lived Azure DevOps PAT via the vssps REST API.

    `az devops` has no PAT-creation command, so this calls the same
    vssps.dev.azure.com/_apis/tokens/pats endpoint the Portal's "New token"
    button uses, authenticated with an AAD token scoped to Azure DevOps's own
    resource ID (499b84ac-1321-427f-aa17-267ca6975798). Confirmed live this
    session against a real Azure DevOps org.
    """
    import datetime

    # Reuses the public `az account get-access-token` command (via
    # _cli_invoke, same pattern as every other cross-command call in this
    # file) instead of touching azure.cli.core internals directly -- the
    # resource is the bare Azure DevOps application ID GUID, NOT an
    # "https://<guid>" URI (that form was tried first and fails tenant-wide
    # with AADSTS500011, confirmed live 2026-10-27).
    token_response = _cli_invoke(
        cli_ctx, "account", "get-access-token", "--resource", ADO_PAT_RESOURCE_ID,
    )
    token = (token_response or {}).get("accessToken")
    if not token:
        raise CLIError("Could not acquire an Azure DevOps access token.")
    valid_to = (datetime.datetime.utcnow() + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {
        "displayName": display_name,
        "scope": "vso.code",
        "validTo": valid_to,
        "allOrgs": False,
    }
    url = f"https://vssps.dev.azure.com/{organization}/_apis/tokens/pats?api-version=7.1-preview.1"
    response = send_raw_request(
        cli_ctx,
        "POST",
        url,
        headers=[f"Authorization=Bearer {token}", "Content-Type=application/json"],
        body=json.dumps(body),
    )
    pat = response.json().get("patToken", {}).get("token")
    if not pat:
        raise CLIError("Azure DevOps did not return a PAT token.")
    return pat


def _detect_repo_provider(repo_url):
    from urllib.parse import urlparse

    host = (urlparse(repo_url).hostname or "").lower()
    if host == "github.com":
        return "GitHub"
    if host.endswith("dev.azure.com") or host.endswith("visualstudio.com"):
        return "AzureDevOps"
    raise CLIError(
        f"Could not detect the repo provider from '{repo_url}'. Pass "
        "--provider GitHub or --provider AzureDevOps explicitly."
    )


@register_command("sre agent repo connect")
class RepoConnect(AAZCommand):
    """Connect a GitHub or Azure DevOps repo to an SRE Agent in one step.

    Mirrors 'az aigateway mcp create --github true': fetches your existing
    'gh auth login' credential (GitHub) or mints a fresh PAT via the Azure
    DevOps REST API (Azure DevOps) and wires up both the auth extension and
    the repositories extension for you, instead of requiring two manual
    'sre agent extension create' calls with hand-built JSON --value payloads.
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"],
            help="Name of the SRE Agent.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.repo_url = AAZStrArg(
            options=["--repo-url"],
            help="HTTPS clone URL of the repo, e.g. https://github.com/org/repo "
            "or https://dev.azure.com/org/project/_git/repo.",
            required=True,
        )
        schema.provider = AAZStrArg(
            options=["--provider"],
            help="Repo provider. Auto-detected from --repo-url's host when omitted.",
            enum={"GitHub": "GitHub", "AzureDevOps": "AzureDevOps"},
        )
        schema.display_name = AAZStrArg(
            options=["--display-name", "--name", "-n"],
            help="Display name for the repo. Defaults to the last path segment of --repo-url.",
        )
        schema.branch = AAZStrArg(
            options=["--branch"],
            help="Branch to check out. Defaults to the repo's default branch.",
        )
        schema.github_account = AAZStrArg(
            options=["--github-account"],
            help="GitHub account to use when 'gh' is logged into more than one "
            "(GitHub repos only; passed to 'gh auth token --user').",
        )
        schema.devops_organization = AAZStrArg(
            options=["--devops-organization"],
            help="Azure DevOps organization name, e.g. 'contoso' for "
            "dev.azure.com/contoso (Azure DevOps repos only; auto-detected "
            "from --repo-url when it is a dev.azure.com URL).",
        )
        schema.devops_auth_type = AAZStrArg(
            options=["--devops-auth-type"],
            help="Azure DevOps auth mechanism. 'pat' (default) mints a PAT via "
            "the vssps REST API -- some orgs block this with a "
            "'DisablePatCreationPolicyViolation' org policy, in which case use "
            "'managed-identity' with --devops-identity instead (the identity "
            "must already be added as a user/group member of the Azure DevOps "
            "org -- this command does not grant that membership).",
            enum={"pat": "pat", "managed-identity": "managed-identity"},
            default="pat",
        )
        schema.devops_identity = AAZStrArg(
            options=["--devops-identity"],
            help="Resource ID of the user- or system-assigned managed identity "
            "to authenticate with Azure DevOps as (required when "
            "--devops-auth-type managed-identity). Typically the SRE Agent's "
            "own identity -- see 'az sre agent show --query identity'.",
        )
        schema.devops_federated_client_id = AAZStrArg(
            options=["--devops-federated-client-id"],
            help="Federated client ID, only needed alongside "
            "--devops-federated-tenant-id for a user-assigned identity in a "
            "different tenant than the Azure DevOps org (managed-identity auth "
            "only; both or neither must be set).",
        )
        schema.devops_federated_tenant_id = AAZStrArg(
            options=["--devops-federated-tenant-id"],
            help="Federated tenant ID, only needed alongside "
            "--devops-federated-client-id (managed-identity auth only; both or "
            "neither must be set).",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        repo_url = _arg_value(self.ctx.args.repo_url)
        provider = _arg_value(self.ctx.args.provider) or _detect_repo_provider(repo_url)
        display_name = _arg_value(self.ctx.args.display_name) or repo_url.rstrip("/").rsplit("/", 1)[-1]
        branch = _arg_value(self.ctx.args.branch)
        github_account = _arg_value(self.ctx.args.github_account)
        devops_organization = _arg_value(self.ctx.args.devops_organization)
        devops_auth_type = _arg_value(self.ctx.args.devops_auth_type) or "pat"
        devops_identity = _arg_value(self.ctx.args.devops_identity)
        devops_federated_client_id = _arg_value(self.ctx.args.devops_federated_client_id)
        devops_federated_tenant_id = _arg_value(self.ctx.args.devops_federated_tenant_id)

        invoke = partial(_cli_invoke, self.cli_ctx)

        if provider == "GitHub":
            token = _github_cli_token(github_account)
            try:
                auth_value = json.dumps({"authType": "Pat", "pat": token})
            finally:
                token = None
            auth_result = invoke(
                "sre", "agent", "extension", "create",
                "--agent-name", agent_name, "--resource-group", resource_group,
                "--extension-type", "githubAuths", "--extension-name", "github_com",
                "--value", auth_value, "--overwrite", "true",
            )
            repo_type = "GitHub"
        else:
            from urllib.parse import urlparse

            organization = devops_organization or urlparse(repo_url).path.strip("/").split("/", 1)[0]
            if not organization:
                raise CLIError(
                    "Could not detect the Azure DevOps organization from --repo-url. "
                    "Pass --devops-organization explicitly."
                )

            if devops_auth_type == "managed-identity":
                if not devops_identity:
                    raise CLIError(
                        "--devops-identity is required when --devops-auth-type "
                        "managed-identity is set."
                    )
                if bool(devops_federated_client_id) != bool(devops_federated_tenant_id):
                    raise CLIError(
                        "--devops-federated-client-id and --devops-federated-tenant-id "
                        "must both be provided or both be omitted."
                    )
                auth_dict = {"authType": "ManagedIdentity", "identity": devops_identity}
                if devops_federated_client_id:
                    auth_dict["federatedClientId"] = devops_federated_client_id
                    auth_dict["federatedTenantId"] = devops_federated_tenant_id
                auth_value = json.dumps(auth_dict)
            else:
                try:
                    pat = _devops_pat_token(self.cli_ctx, organization, f"sre-agent-{agent_name}")
                except Exception as ex:
                    if "DisablePatCreationPolicyViolation" in str(ex):
                        raise CLIError(
                            f"Azure DevOps org '{organization}' has a policy blocking PAT "
                            "creation. Retry with --devops-auth-type managed-identity "
                            "--devops-identity <resource-id-of-an-identity-already-added-to-"
                            f"the-'{organization}'-org> instead."
                        ) from ex
                    raise
                try:
                    auth_value = json.dumps({"authType": "Pat", "pat": pat})
                finally:
                    pat = None
            auth_result = invoke(
                "sre", "agent", "extension", "create",
                "--agent-name", agent_name, "--resource-group", resource_group,
                "--extension-type", "azureDevOpsAuths", "--extension-name", organization,
                "--value", auth_value, "--overwrite", "true",
            )
            repo_type = "AzureDevOps"

        repo_body = {"url": repo_url, "type": repo_type, "description": display_name}
        if branch:
            repo_body["branch"] = branch
        repo_result = invoke(
            "sre", "agent", "extension", "create",
            "--agent-name", agent_name, "--resource-group", resource_group,
            "--extension-type", "repositories", "--extension-name", display_name,
            "--value", json.dumps(repo_body), "--overwrite", "true",
        )
        return {"auth": auth_result, "repository": repo_result}

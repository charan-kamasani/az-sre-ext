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
from azure.cli.core.util import send_raw_request
from knack.log import get_logger

from .aaz.latest.app.agent import Create as _GeneratedCreate
from .aaz.latest.app.agent import Delete as _GeneratedDelete
from .aaz.latest.app.agent import List as _GeneratedList
from .aaz.latest.app.agent import Show as _GeneratedShow
from .aaz.latest.app.agent import Start as _GeneratedStart
from .aaz.latest.app.agent import Stop as _GeneratedStop
from .aaz.latest.app.agent import Update as _GeneratedUpdate

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
        raise ValueError(
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
            if provider is not None:
                provider._help = (
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


@register_command("sre agent create")
class Create(_ModelProviderArgMixin, _GeneratedCreate):
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
            properties["vnetConfiguration"] = vnet_configuration
        if sandbox_configuration is not None:
            properties["sandboxConfiguration"] = sandbox_configuration

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


def _encode_extension_value(raw_value):
    """Base64-encode a user-supplied JSON string for properties.value, the
    wire format confirmed in Agents.http (e.g. pluginMarketplaces' example
    body). Validates the input is JSON first so typos fail fast client-side
    instead of as an opaque base64 blob the service will silently accept
    but the data plane can't parse.
    """
    import base64

    try:
        json.loads(raw_value)
    except (TypeError, ValueError) as ex:
        raise CLIError(
            f"--value must be a JSON document (it is base64-encoded and sent "
            f"as-is to the agent's data plane): {ex}"
        ) from ex
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
    """Create or update an SRE Agent extension (subagent/tool/skill/etc.)."""

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
                "internal control-plane repo's Agents.http examples)."
            ),
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
        raw_value = _arg_value(self.ctx.args.value)

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
        body = {
            "type": f"microsoft.app/agents/{extension_type}",
            "properties": {"value": _encode_extension_value(raw_value)},
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

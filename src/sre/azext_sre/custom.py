# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# This is the sanctioned override layer, not regenerated. The generated AAZ
# command recipes live under aaz/latest/sre/... and are produced from the
# Microsoft.App/agents (SRE Agent) ARM swagger by
# scripts/generate_sre_extension.py directly with their final "sre ..."
# command names. Every class below is a thin subclass of a generated
# command, registered under the same name, that:
#   1. adds behavior the generator cannot produce (client-side validation,
#      defaults, follow-up calls, output shaping);
#   2. adds real-world-validated argument help/enums where the generated
#      swagger left them as bare strings (e.g. --model-provider), grounded in
#      the official SRE Agent docs and the merged stable/2026-07-01 TypeSpec
#      source (see running notes section -1 for citations);
#   3. never duplicates generated request/response logic -- it is reused via
#      super().
#
# commands.py auto-discovers every class defined here via
# inspect.isclass/issubclass scanning of vars(custom), so a new command
# only needs to be added here, decorated with @register_command("sre
# agent ..."), to be picked up.
# --------------------------------------------------------------------------------------------

# pylint: disable=too-many-lines
# pylint: disable=too-many-statements
# pylint: disable=protected-access
# AAZ command/group subclasses intentionally expose only framework hooks.
# pylint: disable=too-few-public-methods

import base64
import contextlib
import json
import logging
import os
import re
import sys
import uuid
from functools import partial
from urllib.parse import quote, urlparse

# 'requests' is imported eagerly here (rather than left to its normal lazy
# import inside azure.cli.core.util.send_raw_request) to avoid a real,
# live-reproduced Python import deadlock: _DefaultSystemIdentityMixin's
# auto-created-identity PUT (_arm_request -> send_raw_request) runs inside
# 'agent create's pre_operations(), which the AAZ LRO poller executes on a
# background thread. If 'requests' has never been imported yet, that
# background thread's first-time lazy import can race against the main
# thread's own first-time import of the same module and deadlock in
# CPython's import lock (_frozen_importlib._DeadlockError: deadlock detected
# by _ModuleLock('requests.structures')) -- confirmed live, 2026-11-01,
# reproduced on every 'az sre agent create' with no --mi-* flags given.
# Importing it here, synchronously, during module load (which always
# happens single-threaded, well before any poller thread exists) guarantees
# it is already in sys.modules and the race can never occur. Also used
# directly by the GitHub OAuth Device Flow fallback in _github_token.
import requests

from azure.cli.core.aaz import (
    AAZArgEnum,
    AAZBoolArg,
    AAZCommand,
    AAZCommandGroup,
    AAZFreeFormDictArg,
    AAZIntArg,
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
from azure.cli.core.aaz.exceptions import AAZUnknownFieldError
from azure.cli.core.azclierror import CLIError, InvalidArgumentValueError, ResourceNotFoundError
from azure.core.exceptions import ResourceExistsError
from azure.core.polling.base_polling import OperationFailed
from azure.cli.core.util import send_raw_request
from azure.mgmt.core.tools import parse_resource_id
from knack.log import get_logger

from .aaz.latest.sre.agent import Create as _GeneratedCreate
from .aaz.latest.sre.agent import Delete as _GeneratedDelete
from .aaz.latest.sre.agent import List as _GeneratedList
from .aaz.latest.sre.agent import ListModels as _GeneratedListModels
from .aaz.latest.sre.agent import Show as _GeneratedShow
from .aaz.latest.sre.agent import Start as _GeneratedStart
from .aaz.latest.sre.agent import Stop as _GeneratedStop
from .aaz.latest.sre.agent import Update as _GeneratedUpdate
from .aaz.latest.sre.agent import Wait as _GeneratedWait
from .aaz.latest.sre.connector import Create as _GeneratedConnectorCreate
from .aaz.latest.sre.connector import Update as _GeneratedConnectorUpdate
from .aaz.latest.sre.connector import Show as _GeneratedConnectorShow
from .aaz.latest.sre.connector import List as _GeneratedConnectorList
from .aaz.latest.sre.connector import Delete as _GeneratedConnectorDelete
from .aaz.latest.sre.connector import Wait as _GeneratedConnectorWait
from .aaz.latest.sre.connector import ListSecret as _GeneratedConnectorListSecret
from .aaz.latest.sre.identity import Assign as _GeneratedIdentityAssign
from .aaz.latest.sre.identity import Remove as _GeneratedIdentityRemove
from .aaz.latest.sre.identity import Show as _GeneratedIdentityShow
from .aaz.latest.sre.identity import Wait as _GeneratedIdentityWait

logger = get_logger(__name__)

# api-version pinned to match the already-generated aaz/latest recipes
# (2026-01-01, see aaz/latest/sre/agent/_show.py). Running notes section 1a
# flags an unresolved discrepancy against the officially published docs
# (2025-05-01-preview) -- reconcile before GA, but every command in this
# extension must use the SAME version the generated code already uses or
# property names may silently mismatch between hand-written and generated
# calls.
API_VERSION = "2026-01-01"

# Networking fields (VNet injection, sandbox egress) are not in the generated
# 2026-01-01 code, so they are hand-written against 2026-11-01-preview. The
# service returns them on read in both versions; writing them on 2026-01-01
# has not been verified. 2026-07-01 is not deployed to production. There is no
# public swagger for 2026-11-01-preview, so the shape was read from the
# control-plane source (src/WebApi/Views/Version20261101Preview/AgentView.cs).
# Align on one version before GA.
NETWORK_API_VERSION = "2026-11-01-preview"


def _arg_value(value):
    """Unwrap an AAZ argument into a plain Python value (None if unset)."""
    if value == AAZUndefined:
        return None
    return AAZHttpOperation.serialize_content(value)


def _snake_to_camel(key):
    """Convert a single snake_case key segment to camelCase."""
    head, *rest = key.split("_")
    return head + "".join(part.capitalize() for part in rest)


def _drop_nulls(value):
    """Recursively remove dict entries whose value is None."""
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value]
    return value


def _camelize_keys(value):
    """Recursively rewrite snake_case dict keys to camelCase.

    Needed for any hand-written command (e.g. UpdateNetwork below) that
    builds its request body straight from an AAZObjectArg/AAZListArg via
    _arg_value(): those are pure CLI-argument-parsing schemas with no
    serialized_name/JSON mapping, so AAZHttpOperation.serialize_content()
    returns dicts keyed by the raw Python attribute name (snake_case), e.g.
    "allowed_hosts" instead of "allowedHosts". Confirmed live against a
    real test agent: ARM rejects the un-camelized body with "Unknown properties
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


DATA_PLANE_AUDIENCE = "https://azuresre.dev"


def _resolve_agent_endpoint(cli_ctx, agent_name, resource_group):
    """Resolve the agent's data-plane URL through ARM."""
    agent_resource_id = _resolve_agent_resource_id(cli_ctx, agent_name, resource_group)
    agent = _arm_request(cli_ctx, "GET", agent_resource_id, API_VERSION)
    endpoint = (agent.get("properties") or {}).get("agentEndpoint") if isinstance(agent, dict) else None
    if not endpoint:
        raise CLIError(
            f"Agent '{agent_name}' has no 'agentEndpoint' yet. It may still be "
            "provisioning. Check 'provisioningState' in 'az sre agent show'."
        )
    return endpoint


def _is_azuresre_https_url(url):
    """True only for a plain https URL whose host is under .azuresre.ai.

    urlparse and requests/urllib3 disagree on backslashes and userinfo, so
    'https://evil\\@x.azuresre.ai' passes a urlparse host check but is sent
    to 'evil'. Reject anything either parser could read differently.
    """
    if not isinstance(url, str) or "\\" in url or any(ord(c) < 33 for c in url):
        return False
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return (
        parsed.scheme == "https"
        and "@" not in parsed.netloc
        and parsed.netloc.lower().split(":")[0] == hostname
        and hostname.endswith(".azuresre.ai")
    )


def _validate_agent_url(agent_url):
    """Return the https *.azuresre.ai origin of agent_url, since a data-plane token is sent to it.

    Uses the same strict check as http-trigger invoke (_is_azuresre_https_url),
    which rejects backslashes, userinfo and control characters that urlparse and
    requests/urllib3 could read as different hosts. Only scheme, host and port
    are kept in the returned origin.
    """
    error = CLIError(
        "--agent-url must be an https agent endpoint on *.azuresre.ai, "
        "for example https://<agent>.<hash>.eastus2.azuresre.ai"
    )
    if not _is_azuresre_https_url(agent_url):
        raise error
    parsed = urlparse(agent_url)
    try:
        port = parsed.port
    except ValueError:
        raise error from None
    return f"https://{parsed.hostname}" + (f":{port}" if port is not None else "")


def _read_target(args):
    """Return (agent_name, resource_group, agent_url) and require one addressing mode."""
    agent_name = _arg_value(args.agent_name)
    resource_group = _arg_value(args.resource_group)
    agent_url = _arg_value(args.agent_url)
    if agent_url:
        if agent_name or resource_group:
            raise CLIError("--agent-url cannot be combined with --agent-name/--resource-group.")
        return None, None, _validate_agent_url(agent_url)
    if not (agent_name and resource_group):
        raise CLIError("Provide --agent-name and --resource-group, or --agent-url for a shared agent.")
    return agent_name, resource_group, None


def _add_read_target_args(schema, short_name=True):
    schema.agent_name = AAZStrArg(
        options=["-n", "--name", "--agent-name"] if short_name else ["--agent-name"],
        help="Name of the SRE Agent.",
    )
    schema.resource_group = AAZResourceGroupNameArg()
    schema.agent_url = AAZStrArg(
        options=["--agent-url"],
        help="Agent endpoint URL (`https://<agent>.<hash>.<region>.azuresre.ai`) for a shared "
             "agent that is not in your subscription. Read-only commands only.",
    )


def _data_plane_request(cli_ctx, agent_name, resource_group, method, path, body=None,
                        missing_ok=False, agent_url=None):
    """Call the agent endpoint using its data-plane OAuth audience."""
    endpoint = agent_url or _resolve_agent_endpoint(cli_ctx, agent_name, resource_group)
    url = f"{endpoint.rstrip('/')}{path}"
    try:
        response = send_raw_request(
            cli_ctx,
            method,
            url,
            headers=["Content-Type=application/json"],
            body=json.dumps(body) if body is not None else None,
            resource=DATA_PLANE_AUDIENCE,
        )
    except Exception as ex:  # Azure CLI normalizes HTTP errors by command.
        status_code = getattr(getattr(ex, "response", None), "status_code", None)
        if missing_ok and status_code == 404:
            return None
        raise
    if not response.content:
        return {}
    content_type = (getattr(response, "headers", None) or {}).get("Content-Type")
    if isinstance(content_type, str) and "html" in content_type.lower():
        # Agents without this API route answer with their web app's HTML page and a 200.
        raise DataPlaneRouteUnavailableError(
            f"The agent doesn't support '{method} {path}' (it returned a web page, not data).")
    return response.json()


class DataPlaneRouteUnavailableError(CLIError):
    """The agent endpoint does not serve the requested API route."""


# Nested commands that take --subscription. 'ad ...' commands do not.
_SUBSCRIPTION_COMMAND_PREFIXES = (
    ("sre",),
    ("role", "assignment"),
    ("account", "show"),
    ("account", "get-access-token"),
)


def _accepts_subscription(args):
    return any(tuple(args[:len(prefix)]) == prefix for prefix in _SUBSCRIPTION_COMMAND_PREFIXES)


def _cli_invoke(cli_ctx, *args, allow_missing=False):
    """Run another public `az sre ...` command in-process and return its
    parsed result.
    """
    import io

    from azure.cli.core import get_default_cli

    args = list(args)
    # The nested CLI starts fresh, so pass along the caller's --subscription
    # to commands that accept it.
    subscription = (getattr(cli_ctx, "data", None) or {}).get("subscription_id")
    if (subscription and _accepts_subscription(args)
            and "--subscription" not in args and "--ids" not in args):
        args += ["--subscription", subscription]

    cli = get_default_cli()
    cli.out_file = io.StringIO()
    try:
        exit_code = cli.invoke(list(args), out_file=io.StringIO())
    except (ResourceNotFoundError, SystemExit) as ex:
        if allow_missing:
            return None
        raise CLIError(f"'{' '.join(args)}' failed: {ex}") from ex
    except Exception as ex:  # pylint: disable=broad-except
        # cli.invoke() normally reports a failing invoked command via its
        # exit code (handled below), not an exception -- but some failures
        # (e.g. an expired/missing login token, a broken credential
        # provider) can raise before that machinery engages and escape as a
        # raw, unrelated-looking exception type. Wrapping everything here,
        # the same way as the ResourceNotFoundError/SystemExit case above,
        # means every one of this helper's 19+ call sites (tenant/user
        # object ID resolution, PAT token fetch, identity lookups, etc.)
        # always surfaces a clear "'<command>' failed: <reason>" CLIError
        # instead of a confusing unrelated stack trace.
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


def _redact_auth_result(auth_result):
    """Mask a freshly-minted PAT/secret before 'sre repo connect' echoes it
    back to the user. Confirmed live that 'extension create' already
    redacts this server-side for githubAuths (pat comes back as "******"),
    but NOT for azureDevOpsAuths (the real PAT is returned verbatim) --
    redact defensively here for both so this command never prints a live
    secret regardless of which provider's server-side behavior changes.
    """
    import copy

    if not isinstance(auth_result, dict):
        return auth_result
    redacted = copy.deepcopy(auth_result)
    value = redacted.get("properties", {}).get("value")
    if isinstance(value, dict):
        for secret_key in ("pat", "secret", "password", "token"):
            if value.get(secret_key):
                value[secret_key] = "******"
    return redacted


@contextlib.contextmanager
def _no_http_trace():
    """Keep Azure CLI's HTTP trace logging from printing bodies that carry a
    secret. send_raw_request logs them on one logger and the AAZ pipeline logs
    them on another, including on a retried request, so silence both for the
    duration of the call."""
    http_loggers = [logging.getLogger(name) for name in (
        "cli.azure.cli.core.util", "cli.azure.cli.core.sdk.policies")]
    previous = [http_logger.level for http_logger in http_loggers]
    for http_logger in http_loggers:
        http_logger.setLevel(logging.CRITICAL)
    try:
        yield
    finally:
        for http_logger, level in zip(http_loggers, previous):
            http_logger.setLevel(level)


def _warn_if_secret_typed(flag, safer):
    """Warn when a secret was typed on the command line instead of read from
    @file. Azure CLI loads @file after echoing the arguments, so sys.argv
    still shows the raw form."""
    argv = sys.argv[1:]
    for index, arg in enumerate(argv):
        if arg == flag and index + 1 < len(argv):
            value = argv[index + 1]
        elif arg.startswith(flag + "="):
            value = arg[len(flag) + 1:]
        else:
            continue
        if not value.startswith("@"):
            logger.warning(
                "%s was typed on the command line, so it shows up in --debug "
                "output and shell history. Next time, %s.", flag, safer)
        return


# Local file the data-plane `sre` CLI (separate deliverable, not an az
# extension -- see running notes section 1) is expected to read from, the
# same way `az aks get-credentials` writes kubeconfig for kubectl to pick
# up. Keeping the bridge file format here (not duplicated at the data-plane
# side) means this is the only place the on-disk schema is defined.
_CONNECTIONS_FILE = os.path.join(
    os.path.expanduser("~"), ".azure", "sreAgentConnections.json"
)


# Real API enum values confirmed from the merged stable/2026-07-01 TypeSpec
# source (agent.models.tsp DefaultModel.provider doc comment), the SRE Agent
# docs, and a live ARM PATCH round-trip against a real agent (2026-11-05),
# whose rejection error for an unsupported value is authoritative:
#   "Provider 'X' is not supported. Supported providers: Anthropic,
#    GitHubCopilot, MicrosoftFoundry"
# The portal UI shows friendly labels that do NOT match the wire values
# ("Azure OpenAI" -> MicrosoftFoundry, "GitHub Copilot" -> GitHubCopilot) --
# the CLI must always send/accept the real values below, surfacing the
# friendly names only in --help text. GitHubCopilot is portal-flagged
# "non-production only" but is a fully valid, API-accepted wire value.
MODEL_PROVIDERS = {
    "anthropic": "Anthropic",
    "githubcopilot": "GitHubCopilot",
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


def _arg_field(arg, name):
    """One field of an AAZ object argument as a plain value, or None when the
    argument or the field is unset or null (for example '--default-model null',
    the AAZ way to clear a property)."""
    value = _arg_value(arg) if arg is not None else None
    return value.get(name) if isinstance(value, dict) else None


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
                    "values are 'Anthropic', 'GitHubCopilot', and "
                    "'MicrosoftFoundry' -- note the Azure Portal shows "
                    "'Azure OpenAI' as a friendly label for MicrosoftFoundry "
                    "(GitHubCopilot is flagged non-production only in the "
                    "portal), but the API never accepts those friendly "
                    "strings. Case-insensitive."
                )
        # azdev linter requires an option of 22 characters or fewer.
        for arg_name, alias in (
            ("incident_management_configuration", "--incident-config"),
            ("knowledge_graph_configuration", "--knowledge-graph"),
        ):
            arg = getattr(schema, arg_name, None)
            if arg is not None and alias not in arg._options:
                arg._options = [*arg._options, alias]
        return schema

    def pre_operations(self):
        default_model = getattr(self.ctx.args, "default_model", None)
        provider = _arg_field(default_model, "provider")
        if provider is not None:
            default_model.provider = _normalize_model_provider(provider)
        super().pre_operations()


def _resolve_signed_in_tenant_id(cli_ctx):
    """Resolve the signed-in account's AAD tenant ID via 'az account show'.

    Used to gate GenevaMetrics (Microsoft-internal only, per Paul's
    2026-11-02 Teams feedback: "Geneva is good. we need that for 1p. 3p
    cannot use" -- the backend already rejects non-1p callers, but that's
    a confusing experience; this lets the CLI reject it up front with a
    clear message instead). One CLI, no separate 1p/3p build -- the
    behavior just adapts to whichever tenant the caller is signed into.
    """
    invoke = partial(_cli_invoke, cli_ctx)
    account = invoke("account", "show")
    tenant_id = (account or {}).get("tenantId") if isinstance(account, dict) else None
    if not tenant_id:
        raise CLIError("Could not resolve the signed-in account's tenant ID via 'az account show'.")
    return tenant_id


def _is_microsoft_first_party_tenant(tenant_id):
    """True if tenant_id is one of Microsoft's known first-party AAD tenants.

    Mirrors the real SRE Agent portal's own first-party gate exactly --
    confirmed live, 2026-11-02, in sreagent-runtime's
    src/Agent/Agent.Web/Client/src/src/Common/Helpers/FirstPartyHelper.ts:
    getTenantType() (lines 67-108) maps each of these 13 GUIDs to a named
    TenantType, and isFirstPartyAgent() (lines 177-208) treats every named
    type except "Other" as first-party -- i.e. all 13 below. The portal
    uses this same list to hide the GenevaMetrics/S360/DGrep/Limn/EngHub
    connector cards from the picker entirely for non-1p tenants, not just
    reject at submit time; this CLI check is the equivalent gate, matching
    the portal 1:1 instead of our earlier single-tenant-ID approximation.
    """
    return tenant_id is not None and tenant_id.lower() in MICROSOFT_FIRST_PARTY_TENANT_IDS


# The 13 Microsoft-internal AAD tenant IDs the real portal treats as
# first-party (public-cloud only; sovereign-cloud equivalents are omitted
# since this CLI targets Azure Public Cloud). Source: getTenantType() in
# FirstPartyHelper.ts (see docstring above) -- lowercased for
# case-insensitive comparison, matching the portal's own `equals(...,
# AntUxStringComparison.IgnoreCase)`.
MICROSOFT_FIRST_PARTY_TENANT_IDS = frozenset(
    tid.lower()
    for tid in (
        "33e01921-4d64-4f8c-a055-5bdaffd5e33d",  # AME
        "72f988bf-86f1-41af-91ab-2d7cd011db47",  # Corp
        "975f013f-7f24-47e8-a7d3-abc4752bf346",  # PME
        "cdc5aeea-15c5-4db6-b079-fcadd2505dc2",  # TORUS
        "ed5693bc-117f-4001-a14c-5f50a530d5df",  # MicrosoftHealthcareCloud
        "124edf19-b350-4797-aefc-3206115ffdb3",  # GME
        "68cd85cc-e0b3-43c8-ba3c-67686dbf8a67",  # MSFTGreen
        "c3ed4049-c06b-48f2-bdfa-fea0c818f1ee",  # DevicesMFG
        "5f032c4e-48ab-4c54-bdc8-067b8a575484",  # MPA
        "53dc36a4-5a8f-4b90-8851-fdfd99605427",  # MPD
        "05e6f886-e266-4486-a450-9bbb7e84da55",  # PKIHRE
        "b1a4f7cb-a159-44a6-ac48-6674e85c4ddc",  # TestTRS01
        "5806608c-07fd-4751-ab09-a60cb90409a2",  # PCECloud
    )
)


def _show_internal_features():
    """Whether help should mention Microsoft-internal features.

    Reads the default account's tenant from the local profile (no network),
    like the portal, which hides these for non-Microsoft tenants. Any doubt
    shows them; the run-time gates still apply.
    """
    try:
        from azure.cli.core._environment import get_config_dir
        with open(os.path.join(get_config_dir(), "azureProfile.json"), encoding="utf-8-sig") as profile_file:
            subscriptions = json.load(profile_file).get("subscriptions") or []
        default = next((s for s in subscriptions if s.get("isDefault")), None)
        tenant_id = (default or {}).get("tenantId")
    except Exception:  # pylint: disable=broad-except
        return True
    if not tenant_id:
        return True
    return _is_microsoft_first_party_tenant(tenant_id) or tenant_id.lower() in ICM_MANAGED_IDENTITY_TENANT_IDS


_SIGNED_IN_PRINCIPAL_TYPES = {"user": "User", "serviceprincipal": "ServicePrincipal"}


def _decode_jwt_claims(token):
    """Read a JWT's payload claims without verifying its signature. Only
    used on our own Azure Resource Manager token, so no trust decision rests
    on it. Never includes the token in errors."""
    parts = token.split(".") if isinstance(token, str) else []
    if len(parts) != 3:
        raise ValueError("not a JWT")
    payload = parts[1]
    payload += "=" * (-len(payload) % 4)
    claims = json.loads(base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8"))
    if not isinstance(claims, dict):
        raise ValueError("JWT payload is not an object")
    return claims


def _resolve_signed_in_principal(cli_ctx):
    """Return (object_id, principal_type) for the signed-in account without
    Microsoft Graph.

    The object ID is the `oid` claim of an Azure Resource Manager token, and
    the principal type comes from 'az account show'. Both nested commands get
    the caller's --subscription, so "me" is resolved in that subscription's
    tenant. Shared by --grant-access-to-me (agent create) and --assignee-me
    (access grant and access revoke).
    """
    invoke = partial(_cli_invoke, cli_ctx)
    token_result = invoke("account", "get-access-token")
    token = token_result.get("accessToken") if isinstance(token_result, dict) else None
    try:
        claims = _decode_jwt_claims(token)
    except Exception:  # pylint: disable=broad-except
        raise CLIError(  # pylint: disable=raise-missing-from
            "Could not read your object ID: the Azure Resource Manager access token from "
            "'az account get-access-token' could not be decoded.")
    object_id = claims.get("oid")
    if not isinstance(object_id, str) or not object_id.strip():
        raise CLIError(
            "Could not read your object ID: the Azure Resource Manager access token from "
            "'az account get-access-token' has no 'oid' claim.")

    account = invoke("account", "show")
    account = account if isinstance(account, dict) else {}
    tenant_id = account.get("tenantId")
    token_tenant = claims.get("tid")
    if tenant_id and token_tenant and str(tenant_id).lower() != str(token_tenant).lower():
        raise CLIError(
            f"Your access token is for tenant '{token_tenant}', but the subscription is in "
            f"tenant '{tenant_id}'. Sign in to that tenant and retry, or use --assignee.")
    user_type = ((account.get("user") or {}).get("type") or "")
    principal_type = _SIGNED_IN_PRINCIPAL_TYPES.get(str(user_type).lower())
    if not principal_type:
        raise CLIError(
            f"Unsupported signed-in account type '{user_type}' from 'az account show'. "
            "Use --assignee instead.")
    return object_id, principal_type


def _find_role_assignment(cli_ctx, object_id, role, scope):
    """Return an existing assignment of `role` to `object_id` at exactly
    `scope`, or None. Azure CLI's own "already exists" handling in 'role
    assignment create' looks up display names in Microsoft Graph, so check
    first without names."""
    existing = _cli_invoke(
        cli_ctx, "role", "assignment", "list",
        "--assignee-object-id", object_id, "--role", role, "--scope", scope,
        "--fill-principal-name", "false",
    )
    for assignment in existing or []:
        if (isinstance(assignment, dict)
                and str(assignment.get("principalId", "")).lower() == object_id.lower()
                and str(assignment.get("scope", "")).lower() == scope.lower()):
            return assignment
    return None


def _create_role_assignment_for_object_id(cli_ctx, object_id, principal_type, role, scope):
    """Create a role assignment for a known object ID without Microsoft Graph,
    returning the existing one if it's already there."""
    existing = _find_role_assignment(cli_ctx, object_id, role, scope)
    if existing is not None:
        return existing
    return _cli_invoke(
        cli_ctx, "role", "assignment", "create",
        "--role", role, "--assignee-object-id", object_id,
        "--assignee-principal-type", principal_type, "--scope", scope,
    )


class _GrantAccessToMeMixin:
    """Adds --grant-access-to-me to 'agent create', collapsing the
    create -> access grant --assignee-me steps into one flag. It runs
    'sre access grant --assignee-me' right after the agent finishes
    provisioning, so "me" is resolved the same Graph-free way.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.grant_access_to_me = AAZStrArg(
            options=["--grant-access-to-me"],
            help="Grant yourself a built-in role after creation. Cannot be used with --no-wait.",
            enum={key: key for key in GrantAccess._ROLES},
        )
        return schema

    def pre_operations(self):
        # AAZCommand's no-wait support (build_lro_poller) advances the
        # pre_operations -> yield PUT -> post_operations generator exactly
        # one step and returns, so post_operations() -- where the grant
        # below actually runs -- is never reached under --no-wait. That
        # would otherwise make --grant-access-to-me a silent no-op instead
        # of a clear error, so reject the combination up front, before
        # super().pre_operations() (which includes _DefaultSystemIdentityMixin's
        # auto-identity-creation side effect) runs.
        role_key = _arg_value(getattr(self.ctx.args, "grant_access_to_me", None))
        no_wait = bool(_arg_value(getattr(self.ctx.args, "no_wait", None)))
        if role_key and no_wait:
            raise CLIError(
                "--grant-access-to-me cannot be combined with --no-wait: the "
                "grant would silently never happen (it runs after the agent "
                "finishes provisioning, which --no-wait skips waiting for). "
                "Either omit --no-wait, or grant access separately afterward "
                "with 'az sre access grant'."
            )
        super().pre_operations()

    def post_operations(self):
        super().post_operations()
        role_key = _arg_value(getattr(self.ctx.args, "grant_access_to_me", None))
        if not role_key:
            return
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        try:
            assignment = _cli_invoke(
                self.cli_ctx,
                "sre", "access", "grant",
                "--agent-name", agent_name, "--resource-group", resource_group,
                "--role", role_key, "--assignee-me",
            )
        except Exception as ex:
            raise CLIError(
                f"Agent '{agent_name}' was created, but granting you the '{role_key}' role failed: {ex}\n"
                f"Retry with: az sre access grant --agent-name {agent_name} "
                f"--resource-group {resource_group} --role {role_key} --assignee-me"
            ) from ex
        principal_id = assignment.get("principalId") if isinstance(assignment, dict) else None
        logger.warning(
            "Granted '%s' role to the signed-in account (%s) on agent '%s'.",
            GrantAccess._ROLES[role_key], principal_id or "object ID unknown", agent_name,
        )


def _create_user_assigned_identity(cli_ctx, subscription_id, resource_group, location, agent_name):
    """Auto-creates a Microsoft.ManagedIdentity/userAssignedIdentities
    resource, returning its resource ID.

    Mirrors the Azure Portal's own "Create agent" wizard default: the real
    ARM template it deploys (SreAgentTemplateResource.ts) defaults
    'createUserIdentity' to true and sets 'identity.type' to
    "SystemAssigned, UserAssigned" -- i.e. the portal always creates a
    brand-new identity resource alongside the agent rather than only
    enabling system-assigned. api-version 2023-01-31 is the stable GA
    version for this resource type.
    """
    suffix = uuid.uuid4().hex[:8]
    identity_name = f"{agent_name}-identity-{suffix}"
    resource_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.ManagedIdentity/userAssignedIdentities/{identity_name}"
    )
    _arm_request(cli_ctx, "PUT", resource_id, "2023-01-31", body={"location": location})
    return resource_id


class _CleanupOnFailurePolling:
    """Wraps an LRO polling method so a failed run calls a cleanup callback with the error."""

    def __init__(self, polling, on_failure):
        self._polling = polling
        self._on_failure = on_failure

    def run(self):
        try:
            self._polling.run()
        except Exception as ex:
            self._on_failure(ex)
            raise

    def __getattr__(self, name):
        return getattr(self._polling, name)


def _service_reported_failure(error):
    """True if a long-running operation failed because the service reported it
    Failed or Canceled, not because a status poll or the final read failed.

    AAZ re-raises polling errors through the command's on_error callback, so
    azure-core's error is in the chain, caused by OperationFailed only when the
    service reported the operation as failed.
    """
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, OperationFailed):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


class _DefaultSystemIdentityMixin:
    """Defaults 'agent create' to match the Azure Portal's own identity
    default when neither --mi-system-assigned nor --mi-user-assigned is
    given: auto-creates a new user-assigned identity AND enables
    system-assigned, i.e. identity.type = "SystemAssigned, UserAssigned".

    WHY: live-confirmed the service rejects agent creation outright with
    (ManagedIdentityRequired) "At least one managed identity (SystemAssigned
    or UserAssigned) must be assigned to the agent" if neither is set -- the
    CLI previously let that request go all the way to ARM before failing.
    An earlier version of this mixin defaulted to system-assigned only,
    believing that to be the portal's own default; a real portal screenshot
    (2026-11-01) plus the portal's actual ARM template
    (Agent.Portal/.../SreAgentTemplateResource.ts: 'createUserIdentity:
    this._options.createUserIdentity ?? true', 'identity.type:
    "SystemAssigned, UserAssigned"') proved that wrong -- the portal always
    creates a brand-new user-assigned identity resource too. This mixin now
    reproduces that: 'az sre agent create --name x -g rg -l eastus2' (no
    --mi-* flags) creates a new Microsoft.ManagedIdentity/
    userAssignedIdentities resource and assigns both identity types to the
    agent, matching the portal exactly instead of the simpler
    system-assigned-only behavior.
    """

    _auto_identity_id = None
    _agent_created = False

    def _execute_operations(self):
        # If the agent create fails, delete the identity we made for it so
        # retries don't pile up orphaned identities. With --no-wait only the
        # synchronous part (pre_operations and the initial PUT) is covered.
        try:
            for polling in super()._execute_operations():
                yield _CleanupOnFailurePolling(polling, self._on_wait_failure)
        except Exception:
            self._delete_auto_identity()
            raise

    def _on_wait_failure(self, error):
        # The service accepted the create. Unless it then reported the
        # operation Failed or Canceled, the agent may exist and use the
        # identity: a status poll can fail transiently, and a read right after
        # success can still answer 404.
        if _service_reported_failure(error):
            self._delete_auto_identity()
            return
        identity_id = self._auto_identity_id
        if not identity_id or self._agent_created:
            return
        try:
            agent = _arm_request(self.cli_ctx, "GET", _ctx_agent_id(self.ctx), API_VERSION, missing_ok=True)
        except Exception:  # pylint: disable=broad-except
            agent = None
        state = ((agent.get("properties") or {}).get("provisioningState")
                 if isinstance(agent, dict) else None)
        if str(state).lower() in ("failed", "canceled"):
            self._delete_auto_identity()
            return
        self._auto_identity_id = None
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        identity_name = identity_id.rsplit("/", 1)[-1]
        if agent:
            logger.warning(
                "Agent '%s' exists (provisioningState: %s), but waiting for it to finish failed. "
                "Kept the identity '%s' made for it. Check the agent with: az sre agent show -g %s -n %s",
                agent_name, state, identity_name, resource_group, agent_name)
        else:
            logger.warning(
                "Couldn't confirm whether agent '%s' was created, so the identity '%s' made for it "
                "was kept. If 'az sre agent show -g %s -n %s' doesn't find the agent, delete the "
                "identity: az identity delete --ids %s",
                agent_name, identity_name, resource_group, agent_name, identity_id)

    def _delete_auto_identity(self):
        identity_id = self._auto_identity_id
        if not identity_id or self._agent_created:
            return
        self._auto_identity_id = None
        try:
            _arm_request(self.cli_ctx, "DELETE", identity_id, "2023-01-31", missing_ok=True)
            logger.warning("Agent creation failed; deleted the identity '%s' created for it.",
                           identity_id.rsplit("/", 1)[-1])
        except Exception as ex:  # pylint: disable=broad-except
            logger.warning("Agent creation failed and the identity created for it could not be "
                           "deleted (%s). Delete it manually: az identity delete --ids %s", ex, identity_id)

    def post_operations(self):
        self._agent_created = True
        super().post_operations()

    def pre_operations(self):
        args = self.ctx.args
        system_assigned = getattr(args, "mi_system_assigned", None)
        user_assigned = getattr(args, "mi_user_assigned", None)
        has_system = has_value(system_assigned)
        has_user = has_value(user_assigned) and len(user_assigned) > 0
        if not has_system and not has_user:
            agent_name = _arg_value(args.agent_name)
            resource_group = _arg_value(args.resource_group)
            location = _arg_value(args.location)
            identity_id = _create_user_assigned_identity(
                self.cli_ctx, self.ctx.subscription_id, resource_group, location, agent_name,
            )
            self._auto_identity_id = identity_id
            args.mi_system_assigned = "True"
            args.mi_user_assigned = [identity_id]
            logger.warning(
                "No managed identity specified; matching the Azure Portal's "
                "own default by creating a new user-assigned identity '%s' "
                "and enabling both system-assigned and user-assigned "
                "identities on the agent. Pass --mi-system-assigned/"
                "--mi-user-assigned explicitly to override.",
                identity_id.rsplit("/", 1)[-1],
            )
        super().pre_operations()


class _LogConfigurationWarningMixin:
    """Warns (never blocks) 'agent create' when --log-configuration is
    omitted.

    WHY: the Azure Portal marks "Application Insights" as a required field
    in its create wizard, but live-confirmed the ARM API itself has no such
    requirement -- a create with zero --log-configuration fully succeeds
    (provisioningState: Succeeded, logConfiguration: null). Confirmed
    directly with Dalibor Kovacevic (SRE Agent team, 2026-11-05): it's an
    un-enforced default, not a hard dependency -- "shouldn't be a hard
    block but we should warn." Follow-up clarified the actual tradeoff:
    agent threads remain available either way (you can still inspect/dump
    them), but without an Application Insights link you lose trace view
    and detailed tracing. This mixin implements exactly that: a non-fatal
    warning describing the real tradeoff, not a CLI-level requirement
    (which would be more restrictive than the real API).
    """

    def pre_operations(self):
        args = self.ctx.args
        if not has_value(getattr(args, "log_configuration", None)):
            logger.warning(
                "No --log-configuration specified; the agent will be "
                "created without an Application Insights link. This is not "
                "required by the service -- agent threads remain available "
                "either way -- but without it you won't get trace view or "
                "detailed tracing for the agent. Pass --log-configuration "
                "to link an Application Insights resource (see --help for "
                "the expected shape)."
            )
        super().pre_operations()


ICM_MANAGED_IDENTITY_TENANT_IDS = frozenset({
    "33e01921-4d64-4f8c-a055-5bdaffd5e33d",
    "975f013f-7f24-47e8-a7d3-abc4752bf346",
    "cdc5aeea-15c5-4db6-b079-fcadd2505dc2",
    "68cd85cc-e0b3-43c8-ba3c-67686dbf8a67",
    "70a90262-f46c-48aa-ac4c-37e37f8be1a2",
    "dc12cfcb-7c57-4e3e-92b9-6ea4cbc258e9",
    "20ac2fc4-effc-4f76-ba7d-63c5ae134f5f",
    "ec044cc1-d8de-4194-a9b6-f5abc1c30081",
})


class _IcmIncidentPlatformGateMixin:
    """Block type=Icm in --incident-management-configuration outside Microsoft tenants."""

    def pre_operations(self):
        platform = _arg_field(getattr(self.ctx.args, "incident_management_configuration", None), "type")
        if platform and str(platform).lower() == "icm":
            tenant_id = (_resolve_signed_in_tenant_id(self.cli_ctx) or "").lower()
            if tenant_id not in ICM_MANAGED_IDENTITY_TENANT_IDS and not _is_microsoft_first_party_tenant(tenant_id):
                raise CLIError("--incident-management-configuration type=Icm is Microsoft-internal only.")
        super().pre_operations()


def _add_experimental_settings_arg(schema):
    schema.experimental_settings = AAZFreeFormDictArg(
        options=["--experimental-settings"],
        arg_group="Properties",
        help="Preview feature flags as JSON or @file, e.g. '{\"EnableWorkspaceTools\": true}'. "
        "Merged into the agent's existing flags.",
    )
    schema.monthly_unit_limit = AAZIntArg(
        options=["--monthly-unit-limit"],
        arg_group="Properties",
        help="Monthly agent unit (AAU) cap for this agent. 0 restores the service default. "
        "The service enforces a minimum (currently 500).",
    )


def _monthly_unit_limit(args):
    limit = _arg_value(getattr(args, "monthly_unit_limit", None))
    if limit is not None and limit < 0:
        raise CLIError("--monthly-unit-limit cannot be negative.")
    return limit


def _extra_agent_properties(args):
    """Agent properties the generated create can't carry, applied with a PATCH afterward."""
    properties = {}
    settings = _experimental_settings(args)
    if settings:
        properties["experimentalSettings"] = settings
    limit = _monthly_unit_limit(args)
    if limit is not None:
        properties["monthlyAgentUnitLimit"] = limit
    return properties


def _experimental_settings(args):
    settings = _arg_value(getattr(args, "experimental_settings", None))
    if settings is not None and not isinstance(settings, dict):
        raise CLIError("--experimental-settings must be a JSON object.")
    return settings or None


class _ExperimentalSettingsOnCreateMixin:
    """Applies --experimental-settings and --monthly-unit-limit with a PATCH once the agent exists.

    The generated create can't carry these properties, and a PUT that does carry
    experimentalSettings replaces the service's own flags instead of adding to them.
    """

    def pre_operations(self):
        if _extra_agent_properties(self.ctx.args) and _arg_value(getattr(self.ctx.args, "no_wait", None)):
            raise CLIError(
                "--experimental-settings and --monthly-unit-limit cannot be combined with --no-wait: "
                "they are applied after the agent finishes provisioning. Run 'az sre agent update' "
                "with them afterward instead."
            )
        super().pre_operations()

    def post_operations(self):
        super().post_operations()
        properties = _extra_agent_properties(self.ctx.args)
        if not properties:
            return
        try:
            _arm_request(self.cli_ctx, "PATCH", _ctx_agent_id(self.ctx), API_VERSION,
                         body={"properties": properties})
        except Exception as ex:
            agent_name = _arg_value(self.ctx.args.agent_name)
            resource_group = _arg_value(self.ctx.args.resource_group)
            flags = " and ".join(flag for key, flag in (
                ("experimentalSettings", "--experimental-settings"),
                ("monthlyAgentUnitLimit", "--monthly-unit-limit"),
            ) if key in properties)
            raise CLIError(
                f"Agent '{agent_name}' was created, but applying {flags} failed: {ex}\n"
                f"Retry with 'az sre agent update --name {agent_name} --resource-group {resource_group}' "
                f"and the same {flags}."
            ) from ex


class _ActionModeEnum(AAZArgEnum):
    """The generated --action-configuration mode enum without 'ReadOnly'."""

    def __init__(self, generated):
        super().__init__({key: value for key, value in generated.items.items() if key.lower() != "readonly"})

    def __getitem__(self, data):
        if isinstance(data, str) and data.lower() == "readonly":
            raise InvalidArgumentValueError(
                f"--action-configuration mode '{data}' is not supported: the service rejects it "
                "with (InvalidActionMode) even though the API specification lists it. "
                f"Use one of: {', '.join(self.to_choices())}."
            )
        return super().__getitem__(data)


class _ActionModeArgMixin:
    """Rejects mode ReadOnly in --action-configuration on agent create/update.

    WHY: the generated enum (from Swagger) lists Autonomous/ReadOnly/Review,
    but the live service accepts only Autonomous and Review and rejects
    ReadOnly with (InvalidActionMode) -- see docs/operations.md. Dropping it
    from the choices fails while arguments are parsed, before 'agent create'
    auto-creates a managed identity and before any request is sent. Remove
    this mixin if the service starts accepting ReadOnly.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        mode = schema.action_configuration.mode
        mode.enum = _ActionModeEnum(mode.enum)
        return schema


class _SecretAgentWriteMixin:
    """Keeps an agent PUT or PATCH out of HTTP trace logs (--debug and az.log).

    The body can carry the incident platform's connection key and the App
    Insights connection string. Same as _SecretHttpOperationMixin, which is
    defined further down with the connector commands.
    """

    def __call__(self, *args, **kwargs):
        kwargs["logging_enable"] = False
        with _no_http_trace():
            return super().__call__(*args, **kwargs)


class _AgentSecretArgWarningMixin:
    """Warns when the incident connection key or the App Insights connection
    string was typed on the command line, where knack's --debug argument echo
    and shell history keep it."""

    def pre_operations(self):
        args = self.ctx.args
        if _arg_field(getattr(args, "incident_management_configuration", None), "connection_key"):
            for flag in ("--incident-management-configuration", "--incident-config"):
                _warn_if_secret_typed(flag, f"put the configuration in a JSON file and pass {flag} @file")
        app_insights = _arg_field(getattr(args, "log_configuration", None), "application_insights_configuration")
        if isinstance(app_insights, dict) and app_insights.get("connection_string"):
            _warn_if_secret_typed(
                "--log-configuration", "put the configuration in a JSON file and pass --log-configuration @file")
        super().pre_operations()


class _AgentExistenceGuardMixin:
    """Refuses 'agent create' for an agent that already exists.

    The create is a PUT, which replaces the agent: a PUT that leaves out
    logConfiguration or monthlyAgentUnitLimit clears them (see Update), and the
    default identity flow attaches a brand-new identity in place of the old one.
    Use 'agent update' to change an existing agent. An agent left Failed by an
    earlier create may reference an identity that rollback deleted, so 'agent
    update' can't repair it, while a working agent whose last update failed is
    Failed too. So a Failed agent still blocks the PUT, and the error offers
    both 'agent update' and deleting the agent first.
    """

    def pre_operations(self):
        existing = _arm_request(self.cli_ctx, "GET", _ctx_agent_id(self.ctx), API_VERSION, missing_ok=True)
        if existing is not None:
            agent_name = _arg_value(self.ctx.args.agent_name)
            resource_group = _arg_value(self.ctx.args.resource_group)
            state = ((existing.get("properties") or {}).get("provisioningState")
                     if isinstance(existing, dict) else None)
            if str(state).lower() in ("failed", "canceled"):
                raise ResourceExistsError(
                    f"An agent named '{agent_name}' already exists in resource group '{resource_group}' "
                    f"(provisioningState: {state}). If it's in use, change it with 'az sre agent update'. "
                    "If an earlier 'agent create' left it behind, delete it before creating it again: "
                    f"az sre agent delete --name {agent_name} --resource-group {resource_group}"
                )
            raise ResourceExistsError(
                f"An agent named '{agent_name}' already exists in resource group '{resource_group}'. "
                "Use 'az sre agent update' to change it, or choose another --name."
            )
        super().pre_operations()


class _RaiseOnWaitTimeoutMixin:
    """Fails a 'wait' command when it times out.

    azure-cli-core (2.92) returns the timeout error instead of raising it, so
    the command printed {} and exited 0 while the resource still wasn't ready.
    """

    def __call__(self, *args, **kwargs):
        result = super().__call__(*args, **kwargs)
        if isinstance(result, Exception):
            raise result
        return result


# Agent properties the CLI sets (--monthly-unit-limit, --experimental-settings)
# that the generated 2026-01-01 schema doesn't model, so its output drops them.
_UNMODELED_AGENT_PROPERTIES = ("monthlyAgentUnitLimit", "experimentalSettings")


def _add_removals(after, before):
    """Sets to null, in place, each key of `before` that `after` lacks or nulls,
    recursing into objects present in both, so a JSON merge patch removes what
    a PUT of `after` would."""
    for key, old in before.items():
        new = after.get(key)
        if new is None:
            after[key] = None
        elif isinstance(old, dict) and isinstance(new, dict):
            _add_removals(new, old)


def _remember_unmodeled_properties(operation, session):
    data = operation.deserialize_http_content(session)
    properties = data.get("properties") if isinstance(data, dict) else None
    if isinstance(properties, dict):
        operation.ctx.sre_unmodeled_properties = {
            key: properties[key] for key in _UNMODELED_AGENT_PROPERTIES if key in properties}


def _with_unmodeled_properties(ctx, result):
    extra = getattr(ctx, "sre_unmodeled_properties", None)
    if extra and isinstance(result, dict):
        if not isinstance(result.get("properties"), dict):
            result["properties"] = {}
        result["properties"].update(extra)
    return result


@register_command("sre agent create")
class Create(  # pylint: disable=too-many-ancestors
        _IcmIncidentPlatformGateMixin, _ModelProviderArgMixin, _ActionModeArgMixin, _AgentSecretArgWarningMixin,
        _GrantAccessToMeMixin, _ExperimentalSettingsOnCreateMixin, _AgentExistenceGuardMixin,
        _DefaultSystemIdentityMixin, _LogConfigurationWarningMixin, _GeneratedCreate):
    """Create an SRE Agent.

    :example: Create an agent with an Anthropic default model
        az sre agent create --name myagent --resource-group myrg \\
            --location eastus2 --default-model "{provider:anthropic,name:automatic}"

    :example: Create an agent with preview feature flags turned on
        az sre agent create --name myagent --resource-group myrg --location eastus2 \\
            --experimental-settings "{\\"EnableWorkspaceTools\\": true}"
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
        # Document the auto-identity-creation default (see
        # _DefaultSystemIdentityMixin) directly on these args, not just in
        # a runtime warning -- a new user reading --help before running the
        # command had no way to know this would happen otherwise.
        schema.mi_system_assigned._help["short-summary"] = (
            "Enable the system-assigned identity. Default: a user-assigned identity is created and both are enabled."
        )
        schema.mi_user_assigned._help["short-summary"] = (
            "User-assigned identities to attach."
        )
        schema.log_configuration._help["short-summary"] = (
            "Application Insights link for traces. Without it, a warning is shown and trace view is unavailable."
        )
        _add_experimental_settings_arg(schema)
        cls._args_schema = schema
        return cls._args_schema

    class AgentsCreateOrUpdate(_SecretAgentWriteMixin, _GeneratedCreate.AgentsCreateOrUpdate):
        pass


@register_command("sre agent update")
class Update(_IcmIncidentPlatformGateMixin, _ModelProviderArgMixin, _ActionModeArgMixin, _AgentSecretArgWarningMixin,
             _GeneratedUpdate):
    """Update an SRE Agent.

    PagerDuty and ServiceNow set the same agent property as the portal's
    Incidents > Connect an incident platform workflow, not the separate
    Connector Gateway used by Jira, Slack and SharePoint. The portal also
    saves which PagerDuty services or ServiceNow assignment group to index;
    set that in the portal. --connection-key is the PagerDuty REST API
    access key; --obo-user is the identity the agent acts under when
    resolving or commenting on incidents.

    ServiceNow uses Basic Auth: set --connection-url to the instance URL
    and --connection-key to the credentials.

    The connection key is a secret. Typed on the command line, it shows up in
    --debug output and shell history, so put the configuration in a JSON file
    and pass it with @file instead, for example a pagerduty.json holding
    `{"type": "PagerDuty", "connectionName": "pagerduty", "connectionKey":
    "<api-key>", "oboUser": "oncall@contoso.com"}`.

    Azure Monitor must also be connected before a response plan can use it.
    A new agent has no incident platform set.

    :example: Switch an agent's default model to MicrosoftFoundry
        az sre agent update --name myagent --resource-group myrg \\
            --default-model "{provider:MicrosoftFoundry,name:gpt-5}"

    :example: Connect Azure Monitor as the incident platform
        az sre agent update --name myagent --resource-group myrg \\
            --incident-management-configuration "{type:AzMonitor,connection-name:azmonitor}"

    :example: Connect PagerDuty as the incident platform, reading the configuration and its key from a file
        az sre agent update --name myagent --resource-group myrg \\
            --incident-management-configuration "@pagerduty.json"

    :example: Connect ServiceNow as the incident platform with Basic Auth
        az sre agent update --name myagent --resource-group myrg \\
            --incident-management-configuration "{type:ServiceNow,connection-name:servicenow,connection-url:'https://contoso.service-now.com',connection-key:<credentials>}"

    :example: Turn on preview feature flags from a file
        az sre agent update --name myagent --resource-group myrg \\
            --experimental-settings "@experimental.json"
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _add_experimental_settings_arg(schema)
        cls._args_schema = schema
        return cls._args_schema

    def pre_instance_update(self, instance):
        super().pre_instance_update(instance)
        # The agent as a request body before the update, to find what a PATCH
        # has to remove explicitly.
        self.ctx.sre_body_before = _arg_value(instance) or {}

    def post_instance_update(self, instance):
        super().post_instance_update(instance)
        # The service never returns the App Insights connection string, so
        # writing the agent back as-is sends an appId without it and the PUT
        # is rejected. Leaving logConfiguration out of a PUT clears it, so
        # drop it and PATCH instead, which keeps the existing link.
        data = instance.to_serialized_data() or {}
        log = (data.get("properties") or {}).get("logConfiguration") or {}
        app_insights = log.get("applicationInsightsConfiguration") or {}
        if app_insights and not app_insights.get("connectionString"):
            if len(log) > 1:
                del instance.properties.log_configuration.application_insights_configuration
            else:
                del instance.properties.log_configuration
            self.ctx.sre_use_patch = True
            self.ctx.sre_kept_log_configuration = True
        # A PUT replaces the whole experimentalSettings map; PATCH merges it.
        if _extra_agent_properties(self.ctx.args):
            self.ctx.sre_use_patch = True

    class AgentsGet(_GeneratedUpdate.AgentsGet):

        def on_200(self, session):
            # The generated model has no monthlyAgentUnitLimit, and a PUT that
            # leaves it out resets the agent to the default limit.
            data = self.deserialize_http_content(session)
            properties = data.get("properties") if isinstance(data, dict) else None
            if isinstance(properties, dict):
                self.ctx.sre_monthly_unit_limit = properties.get("monthlyAgentUnitLimit")
            super().on_200(session)

    class AgentsCreateOrUpdate(_SecretAgentWriteMixin, _GeneratedUpdate.AgentsCreateOrUpdate):

        @property
        def method(self):
            return "PATCH" if getattr(self.ctx, "sre_use_patch", False) else "PUT"

        @property
        def content(self):
            body = super().content
            extra = _extra_agent_properties(self.ctx.args)
            current_limit = getattr(self.ctx, "sre_monthly_unit_limit", None)
            if current_limit is not None and self.method == "PUT":
                extra.setdefault("monthlyAgentUnitLimit", current_limit)
            if self.method == "PATCH":
                # A PATCH merges, so what the update removed (a property set to
                # null or --remove'd, a field of a replaced object) is sent as
                # null, except the App Insights link left out on purpose above.
                before = getattr(self.ctx, "sre_body_before", None) or {}
                before_properties = dict(before.get("properties") or {})
                if getattr(self.ctx, "sre_kept_log_configuration", False):
                    before_properties.pop("logConfiguration", None)
                _add_removals(body.setdefault("properties", {}), before_properties)
                # A PATCH that leaves tags out keeps them; an empty map replaces them.
                if before.get("tags") and "tags" not in body:
                    body["tags"] = {}
            if extra:
                body.setdefault("properties", {}).update(extra)
            return body

        def on_200_201(self, session):
            _remember_unmodeled_properties(self, session)
            super().on_200_201(session)

    def _output(self, *args, **kwargs):
        return _with_unmodeled_properties(self.ctx, super()._output(*args, **kwargs))


# Real wire values confirmed via the control-plane source
# (src/ApiResources/DataModels/KnownDataConnectorTypes.cs and
# src/Services/Validators/DataConnectorValidator.cs): "Kusto" covers
# Azure Data Explorer/App Insights/Log Analytics (differentiated by
# --data-source endpoint, not a separate type value), "Mcp" covers generic
# MCP-compatible connectors (PagerDuty/ServiceNow/Datadog/Splunk/S360/Ev2/
# etc. -- these are *not* separate enum values, just Mcp connectors pointed
# at different endpoints), "Outlook" and "Teams" (rejected here, see
# PORTAL_MANAGED_CONNECTORS below), "Icm" (Incident Management --
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
    "icm": "Icm",
    "kustoclient": "KustoClient",
    "dgrep": "Dgrep",
    "knowledgetext": "KnowledgeText",
    "knowledgefile": "KnowledgeFile",
    "knowledgewebpage": "KnowledgeWebPage",
    "knowledgerepository": "KnowledgeRepository",
    # The 14 entries below were missing from this allowlist even though the
    # real backend (sreagent-runtime's Agent.Core/Configuration/
    # DataConnectorTypes.cs V1 list) has always accepted and implemented
    # them -- this CLI's own stricter client-side check was rejecting them
    # before the request ever reached the service. Confirmed live,
    # 2026-11-02, against a real throwaway agent: all 14 succeed with just
    # --data-source (already a supported flag); "genevametrics" additionally
    # needs extended-properties.monitoringAccount (confirmed by a real
    # downstream Geneva validation error, not a guess). No backend or
    # service change was involved -- this only removes a redundant,
    # out-of-date local restriction.
    "appinsights": "AppInsights",
    "loganalytics": "LogAnalytics",
    "kustouser": "KustoUser",
    "kustodataindexer": "KustoDataIndexer",
    "tsgcrawler": "TsgCrawler",
    "ev2mcp": "Ev2Mcp",
    "genevametrics": "GenevaMetrics",
    "s360": "S360",
    "connectorgateway": "ConnectorGateway",
    "documentation": "Documentation",
    "azuredevopsbuiltinmcp": "AzureDevOpsBuiltinMcp",
    "applicationinsights": "ApplicationInsights",
    "azuremonitor": "AzureMonitor",
    "monitorclient": "MonitorClient",
}

# Friendly-name aliases for the same wire values above, so users can type
# the name the portal/product actually shows instead of memorizing internal
# enum casing (Paul's shape-review feedback: "the developer should choose
# the backend they want to use, not decode implementation terminology").
# Confirmed against sreagent-runtime's own portal i18n strings (the
# authoritative source for what the product calls each connector), not
# invented: `Agent.Web/Client/src/src/Strings/SREAgentResources.ts` ->
# azureDataExplorer/azureMcpKusto: "Azure Data Explorer",
# userProvidedConnector: "User provided connector" (shown for the generic
# "Mcp" type -- Paul's suggested "Custom MCP" label), microsoftIcm:
# "Microsoft IcM", microsoftDGrep: "Microsoft DGrep".
#
# "Azure Data Explorer" maps to KustoClient, matching the portal exactly --
# confirmed directly against the portal's own picker list and persistence
# logic: `ConnectorType.ts`'s `connectorTypeOptions` has no separate picker
# entry for plain "Kusto" at all (only `AzureMcpKusto`, labeled "Azure Data
# Explorer"), and `getEffectiveConnectorType` confirms the portal always
# *persists* that selection to ARM as `dataConnectorType: "KustoClient"`
# ("KustoClient is the new persisted type for Kusto MCP parents"). Plain
# "Kusto" (a pinned single-cluster connection via --data-source) has no
# *direct* top-level portal picker entry, but the portal does create it
# indirectly: the "Azure Data Explorer" wizard's optional "Add clusters"
# step creates one "Kusto" child connector per cluster group (confirmed via
# ConnectorWizardFormik.tsx/DialogHelper.tsx's
# buildKustoConnectorsFromClusterGroups, dataConnectorType:
# ConnectorType.AzureDataExplorerQuery = 'Kusto'). Reachable here via its
# own raw name or the "azure data explorer cluster" alias, never the bare
# "Azure Data Explorer" name a real user would actually type for the
# parent connector.
DATA_CONNECTOR_TYPE_ALIASES = {
    "azure data explorer": "KustoClient",
    "azuredataexplorer": "KustoClient",
    "azure data explorer mcp": "KustoClient",
    "azure data explorer (mcp)": "KustoClient",
    "azure data explorer cluster": "Kusto",
    "azure data explorer (cluster)": "Kusto",
    "custom mcp": "Mcp",
    "custom mcp server": "Mcp",
    "mcp server": "Mcp",
    "user provided connector": "Mcp",
    "microsoft icm": "Icm",
    "icm connector": "Icm",
    "incident manager": "Icm",
    "microsoft dgrep": "Dgrep",
}

# Connector types the portal's connector picker offers, in help-list order,
# plus MonitorClient. Other accepted values (Kusto, Documentation,
# Knowledge*, ...) still work but are not advertised.
PORTAL_CONNECTOR_NAMES = {
    "KustoClient": "Azure Data Explorer",
    "KustoUser": "Database query connector (user)",
    "KustoDataIndexer": "Database indexing connector",
    "LogAnalytics": "Log Analytics Workspace",
    "AppInsights": "Application Insights",
    # No portal card; the portal adds it alongside the Log Analytics and App
    # Insights connectors, and labs create it directly.
    "MonitorClient": "MonitorClient",
    "Mcp": "MCP server",
    "Ev2Mcp": "EV2",
    "TsgCrawler": "Documentation connector",
    "AzureDevOpsBuiltinMcp": "Azure DevOps AI Search",
    "Icm": "IcM connector",
    "Dgrep": "DGrep",
    "GenevaMetrics": "Geneva Metrics",
    "S360": "S360 connector",
}
PORTAL_CONNECTOR_TYPES = tuple(PORTAL_CONNECTOR_NAMES)
# Being retired, so still accepted but not advertised in help or errors.
UNADVERTISED_CONNECTOR_TYPES = ("KustoDataIndexer", "TsgCrawler")
for _value, _portal_name in PORTAL_CONNECTOR_NAMES.items():
    DATA_CONNECTOR_TYPE_ALIASES.setdefault(_portal_name.lower(), _value)

# Managed connectors from the portal's default picker (Connectors > Add
# connector) as of 2026-11-10: each card's name first, then its product
# and managed API names. The portal handles their sign-in, so
# --data-connector-type points there instead. That includes the old
# Outlook and Teams wire values, which the service now creates as managed
# connectors: Outlook fails because no sign-in method is chosen, and Teams
# comes up signed out with no tools. GitLab is left out because the portal
# adds it under Code access.
PORTAL_MANAGED_CONNECTORS = (
    ("Office 365 Outlook", "Outlook", "Microsoft Outlook", "office365"),
    ("Microsoft Teams", "Teams"),
    ("Gmail", "Google Gmail"),
    ("Yammer", "Microsoft Viva Engage", "Viva Engage"),
    ("Microsoft Security Copilot", "securitycopilot"),
    ("Notion", "notionip"),
    ("OneDrive for Business", "onedriveforbusiness"),
    ("SharePoint", "Microsoft SharePoint", "sharepointonline"),
    ("Box",),
    ("Office 365 Users", "office365users"),
    ("Power BI", "Microsoft Power BI", "powerbi"),
    ("Confluence", "Atlassian Confluence"),
    ("Planner", "Microsoft Planner"),
    ("OneNote (Business)", "Microsoft OneNote", "onenote"),
    ("Microsoft Forms", "microsoftforms"),
    ("Google Sheets", "googlesheet"),
    ("Trello",),
    ("RSS",),
    ("Microsoft To-Do (Business)", "Microsoft To Do", "todo"),
    ("Microsoft Bookings", "microsoftbookings"),
    ("MS Graph Users and Groups", "Microsoft Graph", "msgraphgroupsanduser"),
    ("Google Drive", "googledrive"),
    ("Dropbox",),
    ("FTP",),
    ("Excel Online (Business)", "excelonlinebusiness"),
    ("Word Online (Business)", "Microsoft Word", "wordonlinebusiness"),
)
MANAGED_CONNECTOR_CARDS = {
    name.lower(): names[0] for names in PORTAL_MANAGED_CONNECTORS for name in names
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

# Connector types that create an ARM link to an external Azure resource the
# agent will query directly, but grant the agent's identity no data-plane
# read permission on that resource by themselves. Live-confirmed
# (mytestagent/dnci, 2026-11-05): the connector reports provisioningState
# Succeeded immediately, but a query through it fails with a Kusto 403
# ("Principal '...' is not authorized to read database ...") until the
# agent's identity is separately granted a role (e.g. Viewer) on the target
# Kusto database -- see docs/quickstart.md's "connector created is not
# connector working" section for the exact follow-up command.
RBAC_GAP_CONNECTOR_TYPES = {"Kusto", "KustoClient"}


def _connector_access_reminder(connector):
    """Warn after creating an RBAC-gap connector type that the ARM link
    alone does not grant query access yet."""
    if not isinstance(connector, dict):
        return
    properties = connector.get("properties")
    data_connector_type = (
        properties.get("dataConnectorType")
        if isinstance(properties, dict)
        else connector.get("dataConnectorType")
    )
    if data_connector_type in RBAC_GAP_CONNECTOR_TYPES:
        logger.warning(
            "Connector '%s' is created, but the agent's identity has not "
            "been granted access to query it yet -- queries will fail with "
            "a 403 until you grant it a role (e.g. Viewer) on the target "
            "Kusto database. Run 'az sre agent show --query identity' to "
            "find the identity actually used, then 'az kusto database-"
            "principal-assignment create' to grant it.",
            connector.get("name"),
        )


# Wire value -> real portal display name, for the subset of types with a
# confirmed portal picker entry. Confirmed live against the portal's
# "Connectors" dialog (screenshots reviewed 2026-11-03, plus a full catalog
# export from the user). Used only to label 'sre connector list'/'show'
# -o table output so it matches what a user actually sees in the portal
# instead of the internal wire value -- -o json/yaml always return the raw
# dataConnectorType unchanged, since scripts/automation rely on that exact
# value.
#
# Each portal card has a bold Title (the name shown prominently in the
# grid) and a smaller Subtitle underneath (often the full/branded product
# name). We map to the Title, since that's what's visually prominent, and
# note the subtitle in this comment for reference. Two earlier entries in
# this map were corrected from the subtitle to the real Title once the full
# catalog export clarified the distinction:
#   - Icm: card Title is "IcM connector" (was wrongly mapped to the
#     subtitle "Microsoft IcM").
#   - Dgrep: card Title is "DGrep" (was wrongly mapped to the subtitle
#     "Microsoft DGrep").
#   - Mcp: card Title is "MCP server" (was wrongly mapped to "Custom MCP",
#     which does not appear anywhere in the real catalog export; the real
#     subtitle is "User provided connector", already an accepted alias).
#
# Confirmed NOT present as their own portal picker card (live-checked, empty
# search results, and absent from the full catalog export): TsgCrawler,
# ConnectorGateway, AzureMonitor, MonitorClient. These accept creation via
# the CLI/API (the backend's V1 allowlist), but have no portal entry point
# today, so they're intentionally left out of this map and fall back to
# showing the wire value as-is. MonitorClient is the exception: it is
# listed under its wire value because labs and templates create it directly.
#
# High-confidence but NOT create-and-inspect-confirmed correlations (strong
# naming match between the wire value and a catalog card's Title/
# description, but the actual wire value that card persists as has not
# been verified by creating one and reading back dataConnectorType):
#   - KustoUser ~ "Database query connector (user)" (subtitle "Azure Data
#     Explorer"; "Query Azure Data Explorer using your own identity via
#     OAuth sign-in").
#   - KustoDataIndexer ~ "Database indexing connector" (subtitle "Azure
#     Data Explorer"; "generates queries by learning about your logs,
#     telemetry, and time series data").
#   - AzureDevOpsBuiltinMcp ~ "Azure DevOps AI Search" (subtitle "Azure
#     DevOps"; "AI-powered remote code search across Azure DevOps
#     repositories").
# Mapped below since the correlation is strong, but flagged here for a
# future live create+inspect test to fully confirm.
#
# Unresolved ambiguity: the portal shows exactly one "Application Insights"
# card, but the wire-type allowlist has two distinct accepted values,
# 'AppInsights' and 'ApplicationInsights'. Which one that card actually
# persists as has not been confirmed by an actual create-and-inspect test,
# so neither is mapped here yet -- do not guess.
#
# The 4 Knowledge* types are confirmed NOT reachable through this same
# "Connectors" picker at all (empty search, absent from the full catalog
# export) -- they live in a separate portal section, consistent with this
# CLI's separate 'sre knowledge' noun.
#
# Also found in the full portal catalog export but NOT present anywhere in
# this CLI's current DATA_CONNECTOR_TYPES wire-value allowlist -- these are
# real backend connector types this CLI does not yet expose at all, a gap
# for future investigation (same methodology as the 2026-11-02 discovery:
# confirm the exact wire value from sreagent-runtime's DataConnectorTypes.cs
# before adding): "Azure Managed Grafana", "Datadog", "Elasticsearch",
# "Dynatrace", "New Relic", "Splunk", "Hawkeye" (NeuBird), "Limn",
# "Engineering Hub", and a dedicated "GitHub" card (distinct from the
# existing --github shortcut on the Mcp type -- worth double-checking
# whether GitHub is really its own wire value or just another Mcp-backed
# card). NOTE: this also means the existing help text's claim that
# "PagerDuty/ServiceNow/Datadog/Splunk/S360/Ev2/etc." are all reached via
# the generic 'Mcp' type "differentiated by endpoint, not a separate type"
# may be stale/inaccurate for Datadog/Splunk/S360/Ev2 specifically, since
# the catalog shows them as distinct dedicated cards with their own
# descriptions -- needs re-verification, not yet corrected pending a
# backend source check.
CONNECTOR_TYPE_PORTAL_NAMES = {
    "KustoClient": "Azure Data Explorer",
    "Kusto": "Azure Data Explorer Cluster",
    "Mcp": "MCP server",
    # Create no longer accepts these, but agents may already have them.
    "Outlook": "Office 365 Outlook",
    "Teams": "Microsoft Teams",
    "Icm": "IcM connector",
    "Dgrep": "DGrep",
    "LogAnalytics": "Log Analytics Workspace",
    "Ev2Mcp": "EV2",
    "GenevaMetrics": "Geneva Metrics",
    "S360": "S360 connector",
    "Documentation": "Documentation connector",
    "KustoUser": "Database query connector (user)",
    "KustoDataIndexer": "Database indexing connector",
    "AzureDevOpsBuiltinMcp": "Azure DevOps AI Search",
}


def _listed_connector_types():
    types = tuple(t for t in PORTAL_CONNECTOR_TYPES if t not in UNADVERTISED_CONNECTOR_TYPES)
    if _show_internal_features():
        return types
    return tuple(t for t in types if t not in FIRST_PARTY_ONLY_CONNECTOR_TYPES and t != "Icm")


def _normalize_data_connector_type(value):
    if value is None:
        return value
    key = str(value).strip().lower()
    normalized = DATA_CONNECTOR_TYPES.get(key) or DATA_CONNECTOR_TYPE_ALIASES.get(key)
    if normalized is None:
        managed_card = MANAGED_CONNECTOR_CARDS.get(key)
        if managed_card:
            raise CLIError(f"Set up {managed_card} in the portal: Connectors > Add connector.")
        raise CLIError(
            "--data-connector-type must be one of: "
            + ", ".join(PORTAL_CONNECTOR_NAMES[t] for t in _listed_connector_types())
            + ". For knowledge sources use 'az sre knowledge create'"
            + f" (got '{value}')."
        )
    return normalized


@register_command_group("sre connector")
class _ConnectorGroup(AAZCommandGroup):
    """Connect an SRE Agent to an external data source it can query or act on."""


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
                "Connector type, by portal name (case-insensitive): "
                + ", ".join(PORTAL_CONNECTOR_NAMES[t] for t in _listed_connector_types()) + "."
                + " For knowledge sources use 'az sre knowledge create'."
                + " Set up Outlook, Teams and other managed connectors in the portal."
            )
        data_source = getattr(schema, "data_source", None)
        if data_source is not None and isinstance(getattr(data_source, "_help", None), dict):
            data_source._help["short-summary"] = (
                "Connection string or endpoint. For Kusto, include the database: "
                "`https://cluster.kusto.windows.net/database`."
            )
        for _name, _text in (
            ("endpoint", "Endpoint URL, used by endpoint-based connector types such as Mcp."),
            ("identity", "'system' for the agent's system-assigned identity, or a user-assigned identity "
             "resource ID. If omitted, no identity is set."),
            ("extended_properties", "Type-specific settings as JSON or shorthand."),
        ):
            _arg = getattr(schema, _name, None)
            if _arg is not None and isinstance(getattr(_arg, "_help", None), dict):
                _arg._help["short-summary"] = _text
        return schema

    def pre_operations(self):
        args = self.ctx.args
        data_connector_type = getattr(args, "data_connector_type", None)
        if has_value(data_connector_type):
            normalized = _normalize_data_connector_type(
                data_connector_type.to_serialized_data()
            )
            if normalized in FIRST_PARTY_ONLY_CONNECTOR_TYPES:
                _require_first_party(
                    self.cli_ctx, _arg_value(getattr(args, "agent_name", None)), _arg_value(getattr(args, "resource_group", None)),
                    f"--data-connector-type {normalized}", tenant_fallback=True,
                )
            if normalized == "Icm":
                _require_first_party(
                    self.cli_ctx, _arg_value(getattr(args, "agent_name", None)), _arg_value(getattr(args, "resource_group", None)),
                    "--data-connector-type Icm",
                )
            args.data_connector_type = normalized
        super().pre_operations()


# Real public GitHub Copilot MCP endpoint, confirmed live this session
# (provisioningState: Succeeded against a real agent) -- the SRE-Agent-side
# wiring for 'connector create --type Mcp'.
GITHUB_COPILOT_MCP_ENDPOINT = "https://api.githubcopilot.com/mcp/"


class _ConnectorConvenienceArgsMixin:
    """Adds --file-path/--mcp-endpoint/--github to 'connector create', so
    KnowledgeFile/KnowledgeText/Mcp connectors don't require a hand-built
    base64 payload or the (confirmed live, easy to get wrong) nested
    --extended-properties JSON shape Mcp actually needs. The service's real
    wire shape is unchanged -- this only builds it for the caller, the same
    spirit as 'sre repo connect'.
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
            help="Local file to ingest. For knowledge sources use 'az sre knowledge create'.",
        )
        schema.mcp_endpoint = AAZStrArg(
            options=["--mcp-endpoint"],
            arg_group="MCP",
            help="For Mcp: the MCP server's HTTP endpoint URL.",
        )
        schema.github = AAZBoolArg(
            options=["--github"],
            arg_group="MCP",
            help="For Mcp: connect the public GitHub Copilot MCP server (`https://api.githubcopilot.com/mcp/`).",
        )
        schema.tool_access = AAZBoolArg(
            options=["--tool-access"],
            arg_group="Properties",
            help="For KustoClient: let the agent use query tools from this connector (portal 'Allow agent to use query tools').",
        )
        # --bearer-token / --managed-identity-auth / --mi-token-scope /
        # --oauth-dcr / --oauth-scopes / --oauth-client-name: convenience
        # flags for the Mcp connector's 'extendedProperties.authType',
        # matching the real portal wizard's 4 "Authentication method"
        # choices (No authentication / Bearer token / Managed identity /
        # OAuth (dynamic client registration)). Wire shapes confirmed by
        # reading sreagent-runtime's McpDataConnector.cs
        # BuildAuthenticationConfig (authType values: "BearerToken",
        # "AzureARM", "SpecOAuth" -- dictionary keys are matched
        # case-insensitively there, so lowerCamelCase here is fine, same
        # as the pre-existing "transport"/"endpoint" keys above).
        schema.bearer_token = AAZStrArg(
            options=["--bearer-token"],
            arg_group="MCP",
            help="For Mcp: static bearer token, PAT or API key sent with every request.",
        )
        schema.managed_identity_auth = AAZBoolArg(
            options=["--managed-identity-auth"],
            arg_group="MCP",
            help="For Mcp: authenticate with the agent's managed identity. Use --identity for a user-assigned one.",
        )
        schema.mi_token_scope = AAZStrArg(
            options=["--mi-token-scope"],
            arg_group="MCP",
            help="For Mcp with --managed-identity-auth: token scope to request. Default: `https://management.azure.com/.default`.",
        )
        schema.oauth_dcr = AAZBoolArg(
            options=["--oauth-dcr"],
            arg_group="MCP",
            help="For Mcp: use OAuth with dynamic client registration. Finish consent in the portal.",
        )
        schema.oauth_scopes = AAZStrArg(
            options=["--oauth-scopes"],
            arg_group="MCP",
            help="For Mcp with --oauth-dcr: comma-separated OAuth scopes to request.",
        )
        schema.oauth_client_name = AAZStrArg(
            options=["--oauth-client-name"],
            arg_group="MCP",
            help="For Mcp with --oauth-dcr: client name to register. Optional.",
        )
        return schema

    # Set by pre_operations() when --file-path was used, so _output() (see
    # ConnectorCreate below) can warn if the service echoes back an empty
    # extendedProperties despite the PUT request body containing the real
    # fileContent/fileName -- confirmed live via --debug on 2026-01-01
    # api-version: the request correctly includes
    # {"fileContent": "...", "fileName": "..."}, but the 200 response (and
    # a subsequent 'connector show') comes back with
    # extendedProperties: {"fileContent": null, "fileName": null}. This is
    # a service-side bug (the CLI sends the right payload), not something
    # fixable client-side -- the warning just stops users from assuming
    # the file silently never got sent.
    _file_path_used = False

    def pre_operations(self):  # pylint: disable=too-many-branches
        args = self.ctx.args
        connector_type = _arg_value(getattr(args, "data_connector_type", None))
        file_path = _arg_value(getattr(args, "file_path", None))
        mcp_endpoint = _arg_value(getattr(args, "mcp_endpoint", None))
        github = _arg_value(getattr(args, "github", None))
        tool_access = _arg_value(getattr(args, "tool_access", None))

        if tool_access is not None:
            if connector_type != "KustoClient":
                raise CLIError(
                    "--tool-access requires --data-connector-type "
                    "KustoClient ('Azure Data Explorer')."
                )
            existing = _arg_value(getattr(args, "extended_properties", None)) or {}
            if not isinstance(existing, dict):
                existing = {}
            args.extended_properties = {
                **existing,
                "toolsVisibleToMetaAgent": ["*"] if tool_access else [],
            }

        if github or mcp_endpoint:
            if connector_type != "Mcp":
                raise CLIError("--github/--mcp-endpoint require --data-connector-type Mcp.")
            endpoint = GITHUB_COPILOT_MCP_ENDPOINT if github else mcp_endpoint
            if urlparse(endpoint).scheme.lower() != "https":
                raise InvalidArgumentValueError("--mcp-endpoint must be an https:// URL.")
            args.data_source = endpoint
            existing = _arg_value(getattr(args, "extended_properties", None)) or {}
            if not isinstance(existing, dict):
                existing = {}
            # Merge, don't overwrite: a caller combining --mcp-endpoint with their
            # own --extended-properties (e.g. {"headers": {...}} for a plugin's
            # MCP server auth, matching the portal's "Configure connector" custom
            # headers field) previously had that silently discarded here.
            args.extended_properties = {
                **existing,
                "transport": "Http",
                "endpoint": endpoint,
            }
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
                with open(file_path, "r", encoding="utf-8-sig") as handle:
                    text = handle.read()
                args.extended_properties = {"content": text}
            self._file_path_used = True

        bearer_token = _arg_value(getattr(args, "bearer_token", None))
        if bearer_token:
            _warn_if_secret_typed("--bearer-token", "read it from a file with --bearer-token @token.txt")
        managed_identity_auth = _arg_value(getattr(args, "managed_identity_auth", None))
        mi_token_scope = _arg_value(getattr(args, "mi_token_scope", None))
        oauth_dcr = _arg_value(getattr(args, "oauth_dcr", None))
        oauth_scopes = _arg_value(getattr(args, "oauth_scopes", None))
        oauth_client_name = _arg_value(getattr(args, "oauth_client_name", None))

        auth_flags_used = [
            bool(bearer_token),
            bool(managed_identity_auth or mi_token_scope),
            bool(oauth_dcr),
        ]
        if sum(auth_flags_used) > 1:
            raise CLIError(
                "Only one of --bearer-token, --managed-identity-auth/"
                "--mi-token-scope, or --oauth-dcr can be used at a time -- "
                "each sets a different extended-properties.authType."
            )
        if oauth_scopes or oauth_client_name:
            if not oauth_dcr:
                raise CLIError("--oauth-scopes/--oauth-client-name require --oauth-dcr true.")

        if any(auth_flags_used):
            if connector_type != "Mcp":
                raise CLIError(
                    "--bearer-token/--managed-identity-auth/--mi-token-scope/"
                    "--oauth-dcr require --data-connector-type Mcp."
                )
            existing = _arg_value(getattr(args, "extended_properties", None)) or {}
            if not isinstance(existing, dict):
                existing = {}
            if bearer_token:
                existing = {
                    **existing,
                    "authType": "BearerToken",
                    "bearerToken": bearer_token,
                }
            elif managed_identity_auth or mi_token_scope:
                if not mi_token_scope:
                    target = existing.get("endpoint") or _arg_value(getattr(args, "data_source", None)) or ""
                    logger.warning(
                        "--managed-identity-auth without --mi-token-scope sends the agent's managed "
                        "identity ARM token (https://management.azure.com/.default) to '%s'. Only use "
                        "this with an MCP server you trust, or pass --mi-token-scope for its own audience.",
                        urlparse(target).hostname or target or "the MCP endpoint",
                    )
                existing = {
                    **existing,
                    "authType": "AzureARM",
                    "armScope": mi_token_scope or "https://management.azure.com/.default",
                }
            elif oauth_dcr:
                existing = {**existing, "authType": "SpecOAuth"}
                if oauth_scopes:
                    existing["scopes"] = oauth_scopes
                if oauth_client_name:
                    existing["dcrClientName"] = oauth_client_name
            args.extended_properties = existing

        super().pre_operations()

    def _output(self, *args, **kwargs):
        result = super()._output(*args, **kwargs)
        if self._file_path_used:
            properties = (result or {}).get("properties", {}) or {}
            extended = properties.get("extendedProperties") or {}
            if not any(extended.values()):
                logger.warning(
                    "The connector was created, but the service didn't return "
                    "the file content or file name. This is a known "
                    "service-side gap, not a sign that the file wasn't sent. "
                    "Run 'az sre connector show' later to check whether the "
                    "content appears."
                )
        return result


class _ConnectorExistenceGuardMixin:
    """Guards 'connector create' against silently overwriting an existing
    connector of the same name. The generated PUT has no If-Match/If-None-
    Match support here, so a second 'create' with the same --name would
    otherwise replace the first one's configuration without any warning --
    this adds a GET-before-PUT check. Use 'connector update' to
    intentionally change an existing connector.

    Confirmed root cause of issue #4 (cosmetic "ERROR: ... Not Found" stderr
    noise on a successful 'connector create'/'knowledge create'): the
    previous version of this guard called '_cli_invoke(..., "connector",
    "show", ..., allow_missing=True)', which runs a *full* in-process
    'az sre connector show' via Azure CLI's own 'cli.invoke()'. On the
    overwhelmingly common path -- creating a brand-new connector that does
    not exist yet -- that inner 'show' genuinely 404s, and 'cli.invoke()'
    logs the resulting HTTP error to stderr via its own global exception
    handler *before* returning control to this caller, regardless of the
    fact that '_cli_invoke's allow_missing=True then silently swallows it.
    The 404 was always harmless (it's the expected, common case, not a
    real failure), but the noisy log line survived the swallowing.
    Switched to a direct, silent raw ARM GET via '_arm_request(...,
    missing_ok=True)' -- the same helper '_extension_resource_create'
    already uses for this exact existence-check pattern -- which goes
    straight through 'send_raw_request' and never touches 'cli.invoke()',
    so a 404 on a brand-new connector name no longer prints anything.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        if hasattr(schema, "overwrite"):
            return schema
        schema.overwrite = AAZBoolArg(
            options=["--overwrite"],
            help="Replace an existing connector with the same name instead of failing.",
            default=False,
        )
        return schema

    def pre_operations(self):
        if _arg_value(getattr(self.ctx.args, "overwrite", None)):
            super().pre_operations()
            return
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        connector_name = _arg_value(self.ctx.args.connector_name)
        agent_resource_id = _resolve_agent_resource_id(self.cli_ctx, agent_name, resource_group)
        resource_id = f"{agent_resource_id}/connectors/{connector_name}"
        existing = _arm_request(self.cli_ctx, "GET", resource_id, API_VERSION, missing_ok=True)
        if existing is not None:
            raise ResourceExistsError(
                f"A connector named '{connector_name}' already exists on agent "
                f"'{agent_name}'. Use 'az sre connector update' to change "
                "it, pass --overwrite to replace it, or choose another --name."
            )
        super().pre_operations()


class _ConnectorPartnerTypeMixin:
    """Adds --partner-type, stored as extendedProperties.partnerType on Mcp connectors."""

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        if not hasattr(schema, "partner_type"):
            schema.partner_type = AAZStrArg(
                options=["--partner-type"],
                arg_group="MCP",
                help="For Mcp: the partner integration this server belongs to, for example DynatraceMcp. "
                     "On update, also pass --data-source and --extended-properties, since the service "
                     "doesn't return the endpoint or credentials.",
            )
        return schema

    def pre_operations(self):
        args = self.ctx.args
        partner_type = _arg_value(getattr(args, "partner_type", None))
        connector_type = _arg_value(getattr(args, "data_connector_type", None))
        if partner_type and connector_type is not None and connector_type != "Mcp":
            raise CLIError("--partner-type requires --data-connector-type Mcp.")
        if partner_type and isinstance(self, _GeneratedConnectorUpdate) and (
                _arg_value(getattr(args, "data_source", None)) is None
                or _arg_value(getattr(args, "extended_properties", None)) is None):
            # GET never returns the endpoint or bearer token, so a PUT built
            # from it alone would wipe them from the connector.
            raise CLIError(
                "--partner-type on update also needs --data-source and --extended-properties "
                "(including the endpoint and credentials), because the service doesn't return "
                "them and they would otherwise be cleared."
            )
        if partner_type and not isinstance(self, _GeneratedConnectorUpdate):
            existing = _arg_value(getattr(args, "extended_properties", None)) or {}
            if not isinstance(existing, dict):
                existing = {}
            args.extended_properties = {**existing, "partnerType": partner_type}
        super().pre_operations()

    def post_instance_update(self, instance):
        super().post_instance_update(instance)
        partner_type = _arg_value(getattr(self.ctx.args, "partner_type", None))
        if not partner_type:
            return
        if instance.properties.data_connector_type.to_serialized_data() != "Mcp":
            raise CLIError("--partner-type only applies to Mcp connectors.")
        instance.properties.extended_properties["partnerType"] = partner_type


class _SecretHttpOperationMixin:
    def __call__(self, *args, **kwargs):
        kwargs["logging_enable"] = False
        with _no_http_trace():
            return super().__call__(*args, **kwargs)


@register_command("sre connector create")
class ConnectorCreate(
    _DataConnectorTypeArgMixin,
    _ConnectorPartnerTypeMixin,
    _ConnectorConvenienceArgsMixin,
    _ConnectorExistenceGuardMixin,
    _GeneratedConnectorCreate,
):
    """Create an Agent Connector.

    :example: Connect Azure Data Explorer
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name adx --data-connector-type "Azure Data Explorer"

    :example: Connect the GitHub MCP server
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name github --data-connector-type Mcp --github true

    :example: Connect a custom MCP server with a bearer token read from a file
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name mcp --data-connector-type Mcp \\
            --mcp-endpoint "https://myserver.contoso.com/mcp" \\
            --bearer-token @token.txt

    :example: Connect a Dynatrace MCP server
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name dynatrace --data-connector-type Mcp \\
            --mcp-endpoint "https://myenv.apps.dynatrace.com/platform-reserved/mcp-gateway/v0.1/servers/dynatrace-mcp/mcp" \\
            --bearer-token "$DT_TOKEN" --partner-type DynatraceMcp

    :example: Connect a custom MCP server with the agent's managed identity
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name mcp --data-connector-type Mcp \\
            --mcp-endpoint "https://myserver.contoso.com/mcp" \\
            --managed-identity-auth true

    :example: Connect one Kusto cluster and database
        az sre connector create --agent-name myagent --resource-group myrg \\
            --name kusto --data-connector-type "Azure Data Explorer" \\
            --data-source "https://mycluster.westus.kusto.windows.net/mydatabase"
    """

    _args_schema = None

    class AgentsConnectorsCreateOrUpdate(
        _SecretHttpOperationMixin,
        _GeneratedConnectorCreate.AgentsConnectorsCreateOrUpdate,
    ):
        pass

    def _output(self, *args, **kwargs):
        result = super()._output(*args, **kwargs)
        _connector_access_reminder(result)
        return _annotate_connector_consent_status(result)


@register_command("sre connector update")
class ConnectorUpdate(_DataConnectorTypeArgMixin, _ConnectorPartnerTypeMixin, _GeneratedConnectorUpdate):
    """Update an Agent Connector.

    :example: Point a Kusto connector at a different database
        az sre connector update -g myrg --agent-name myagent -n conn-kusto \\
            --data-connector-type "Azure Data Explorer" \\

    :example: Mark an MCP connector as a Dynatrace integration. The service doesn't return the endpoint or token, so pass them again.
        az sre connector update -g myrg --agent-name myagent -n dynatrace --partner-type DynatraceMcp \\
            --data-source "$DT_MCP_URL" --extended-properties @dynatrace-mcp.json
    """

    _args_schema = None

    class AgentsConnectorsCreateOrUpdate(
        _SecretHttpOperationMixin,
        _GeneratedConnectorUpdate.AgentsConnectorsCreateOrUpdate,
    ):
        pass

    def _output(self, *args, **kwargs):
        result = super()._output(*args, **kwargs)
        return _annotate_connector_consent_status(result)


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


def _connector_consent_guidance(connector):
    """Build an actionable message for a connector stuck in PendingConsent.

    The SRE Agent control plane has no public ARM action to start or
    complete OAuth consent from the CLI -- confirmed by inspecting
    AAPT-SREAgent-ControlPlane src/WebApi (the ARM-facing REST surface):
    there is no "getLoginLinks"-style operation there.
    The only endpoints that construct/validate the Entra OAuth handshake for
    connectors (src/AuthenticationEndpoint/Controllers/EntraSSOController.cs)
    are Mise-authenticated, service-to-service routes meant for the portal's
    own browser session -- not callable with a bearer token from the CLI.
    So the CLI can only detect PendingConsent and point the user at the
    one place that *can* complete it: the connector's blade in the portal.
    """
    resource_id = connector.get("id") if isinstance(connector, dict) else None
    name = connector.get("name") if isinstance(connector, dict) else None
    where = (
        f"https://portal.azure.com/#@/resource{resource_id}/overview"
        if isinstance(resource_id, str) and resource_id
        else "the connector's blade in the Azure portal"
    )
    label = f"Connector '{name}'" if name else "This connector"
    return (
        f"{label} is PendingConsent: the OAuth sign-in step has not been "
        "completed yet. The CLI cannot complete this step for you -- Azure "
        "SRE Agent only exposes it as an interactive browser consent flow, "
        f"not as a public ARM action. Open {where} and complete the "
        "sign-in prompt, then re-run this command to confirm consentStatus "
        "has changed to Consented."
    )


def _annotate_connector_consent_status(connector):
    """Add a CLI-only consentStatus field to a connector response dict,
    computed from properties.extendedProperties.{authType,entraOAuth}.
    No-ops (leaves the dict unchanged) for connectors that are not
    EntraOAuth-authenticated -- e.g. Kusto connectors, or Mcp connectors
    using a different auth type. Outlook and Teams connectors do need a
    sign-in, but its status is on their managed connection, not on the
    ARM resource, so they get no consentStatus either.

    When the computed status is PendingConsent, also logs actionable
    guidance (see _connector_consent_guidance) since the CLI itself has no
    way to drive the OAuth consent step to completion.
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
        if status == "PendingConsent":
            logger.warning(_connector_consent_guidance(connector))
    return connector


@register_command("sre connector show")
class ConnectorShow(_GeneratedConnectorShow):
    """Show a connector, including OAuth consent status.

    consentStatus is shown for EntraOAuth-backed Mcp connectors.

    :example: Show one connector
        az sre connector show -g myrg --agent-name myagent -n conn-kusto
    """

    _args_schema = None

    def _output(self, *args, **kwargs):
        result = super()._output(*args, **kwargs)
        return _annotate_connector_consent_status(result)


@register_command("sre connector list")
class ConnectorList(_GeneratedConnectorList):
    """List connectors, including OAuth consent status.

    consentStatus (Consented/PendingConsent) is shown for EntraOAuth-backed
    Mcp connectors.

    :example: List an agent's connectors
        az sre connector list -g myrg --agent-name myagent
    """

    _args_schema = None

    EMPTY_GUIDANCE = (
        "No connectors found. Add one with 'az sre connector create "
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


def _require_arm_resource(cli_ctx, resource_id, missing_message):
    """Raise ResourceNotFoundError unless ARM has this resource. ARM answers a
    DELETE of a resource that doesn't exist with success, so deletes check first."""
    if _arm_request(cli_ctx, "GET", resource_id, API_VERSION, missing_ok=True) is None:
        raise ResourceNotFoundError(missing_message)


def _ctx_agent_id(ctx):
    """ARM ID of the agent named by a command's --resource-group and --agent-name."""
    return (
        f"/subscriptions/{ctx.subscription_id}/resourceGroups/{_arg_value(ctx.args.resource_group)}"
        f"/providers/Microsoft.App/agents/{_arg_value(ctx.args.agent_name)}"
    )


@register_command("sre connector delete")
class ConnectorDelete(_GeneratedConnectorDelete):
    """Delete an Agent Connector.

    :example: Delete a connector without a prompt
        az sre connector delete -g myrg --agent-name myagent -n conn-kusto --yes
    """

    _args_schema = None

    def pre_operations(self):
        agent_name = _arg_value(self.ctx.args.agent_name)
        name = _arg_value(self.ctx.args.connector_name)
        _require_arm_resource(
            self.cli_ctx, f"{_ctx_agent_id(self.ctx)}/connectors/{quote(name, safe='')}",
            f"Connector '{name}' not found on agent '{agent_name}'.")
        super().pre_operations()


@register_command("sre connector wait")
class ConnectorWait(_RaiseOnWaitTimeoutMixin, _GeneratedConnectorWait):
    """Wait for a connector to reach a desired state.

    :example: Wait until a connector created with --no-wait exists
        az sre connector wait -g myrg --agent-name myagent -n conn-kusto --created
    """

    _args_schema = None


class _ConnectorNameAliasMixin:
    """Adds the usual '-n'/'--name' aliases to --connector-name, matching
    show/update/delete -- the generated ListSecret recipe is missing them
    (the swagger operation just didn't carry the same x-ms-client-name
    alias the other connector operations have), which would otherwise make
    this one command inconsistent with every other 'sre connector ...'
    command's argument names.
    """

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        connector_name = getattr(schema, "connector_name", None)
        if connector_name is not None:
            connector_name._options = ["-n", "--name", "--connector-name"]
        return schema


@register_command("sre connector list-secret")
class ConnectorListSecret(_ConnectorNameAliasMixin, _GeneratedConnectorListSecret):
    """Show a connector with its secrets in plain text.

    Unlike 'sre connector show'/'sre connector list', which redact secret
    fields server-side, this command returns them unredacted. HTTP request
    and response tracing is disabled for this command, including with --debug.
    Store the output securely and never commit it. The service only returns
    secrets to callers with an admin role on the agent; other callers get an
    authorization error.

    :example: Read back a Kusto connector's secret after creating it
        az sre connector list-secret --agent-name myagent --resource-group myrg --name conn-kusto
    """

    _args_schema = None

    class AgentsConnectorsListSecrets(
        _SecretHttpOperationMixin,
        _GeneratedConnectorListSecret.AgentsConnectorsListSecrets,
    ):
        pass


# --------------------------------------------------------------------------------------------
# "sre identity" -- matches the portal's Identity tab/blade: assign or
# remove the agent resource's own system/user-assigned managed identity
# (the identity the agent's data plane runs as, used for its own Azure
# RBAC-gated calls -- distinct from 'sre access', which controls who can
# manage/use the agent, and from 'sre repo connect', which is about repo
# auth). Generated as the top-level 'sre identity' group rather than nested
# under 'sre agent', since manager feedback was explicit that 'agent' should
# stay a pure CRUD/lifecycle noun and not carry extra nested subgroups.
# --------------------------------------------------------------------------------------------
@register_command_group("sre identity")
class _IdentityGroup(AAZCommandGroup):
    """Manage the agent's own managed identity.

    Used for the agent's Azure RBAC-gated calls. Not to be confused with 'sre access' (who can manage/use the agent) or
    'sre repo connect' (repo auth).
    """


def _requested_identities(args, remove):
    """(system-assigned requested, user-assigned IDs or None) from the identity flags."""
    system = _arg_value(args.mi_system_assigned)
    system = system is not None and str(system).strip().lower() not in ("", "false")
    user_assigned = _arg_value(args.mi_user_assigned)
    if not system and user_assigned is None:
        raise CLIError("Specify --system-assigned, --user-assigned, or both.")
    if not remove and user_assigned == []:
        raise CLIError("--user-assigned needs one or more identity resource IDs.")
    return system, user_assigned


def _identity_patch(current, system, user_assigned, remove, agent_name):
    """The identity block of a PATCH that assigns or removes managed identities.

    Removed user-assigned identities are sent as null, as an ARM PATCH expects.
    When none remain, the type alone drops them (as 'az vm identity remove'
    does). '--user-assigned' with no IDs on remove removes them all.
    """
    types = {part.strip().lower() for part in str(current.get("type") or "").split(",")}
    has_system = "systemassigned" in types
    kept = list(current.get("userAssignedIdentities") or {}) if "userassigned" in types else []
    removed = []
    if remove:
        has_system = has_system and not system
        if user_assigned is not None:
            attached = {identity_id.lower() for identity_id in kept}
            missing = [identity_id for identity_id in user_assigned if identity_id.lower() not in attached]
            if missing:
                raise CLIError(
                    f"Agent '{agent_name}' doesn't have these user-assigned identities: {', '.join(missing)}")
            targets = {identity_id.lower() for identity_id in user_assigned} or attached
            removed = [identity_id for identity_id in kept if identity_id.lower() in targets]
            kept = [identity_id for identity_id in kept if identity_id.lower() not in targets]
    else:
        has_system = has_system or system
        attached = {identity_id.lower() for identity_id in kept}
        for identity_id in user_assigned or []:
            if identity_id.lower() not in attached:
                kept.append(identity_id)
                attached.add(identity_id.lower())
    if has_system and kept:
        identity_type = "SystemAssigned,UserAssigned"
    elif has_system:
        identity_type = "SystemAssigned"
    else:
        identity_type = "UserAssigned" if kept else "None"
    if remove and identity_type == "None":
        # The service rejects this (ManagedIdentityRequired), but the rejected
        # PATCH still deletes the system-assigned identity's service principal,
        # leaving the agent pointing at a principal that no longer exists.
        raise CLIError(
            f"Agent '{agent_name}' needs at least one managed identity, and this would remove the last one. "
            "Nothing was changed. Assign another identity first ('az sre identity assign'), then remove this one.")
    patch = {"type": identity_type}
    if kept:
        patch["userAssignedIdentities"] = {
            **{identity_id: {} for identity_id in kept}, **{identity_id: None for identity_id in removed}}
    return patch


class _IdentityPatchMixin:
    """Sends 'identity assign' and 'identity remove' as a PATCH of only the
    identity block.

    The generated commands read the agent and PUT all of it back. The service
    never returns the App Insights connection string or the incident
    connection key, so on an agent linked to App Insights that PUT was rejected
    (InvalidApplicationInsightsConfiguration), and on other agents it dropped
    what the generated schema doesn't model, such as monthlyAgentUnitLimit,
    which a PUT resets to the default. The identity block is computed here, not
    by the generated merge: in azure-cli-core 2.92 that merge removes every
    user-assigned identity when 'identity remove' names just one.
    """

    _removes_identities = False

    def pre_operations(self):
        self.ctx.sre_requested_identities = _requested_identities(self.ctx.args, self._removes_identities)
        super().pre_operations()

    def pre_instance_update(self, instance):
        super().pre_instance_update(instance)
        current = instance.to_serialized_data()
        system, user_assigned = self.ctx.sre_requested_identities
        self.ctx.sre_identity_patch = _identity_patch(
            current if isinstance(current, dict) else {}, system, user_assigned,
            self._removes_identities, _arg_value(self.ctx.args.agent_name))

    def _output(self, *args, **kwargs):
        # Runs after the poller has passed the final result to on_200_201; a
        # result without a body never gets there, so read the agent back.
        if not getattr(self.ctx, "sre_identity_written", False):
            self.AgentsGet(ctx=self.ctx)()
        return super()._output(*args, **kwargs)


class _IdentityPatchOperationMixin:

    @property
    def method(self):
        return "PATCH"

    @property
    def content(self):
        return {"identity": self.ctx.sre_identity_patch}

    def on_200_201(self, session):
        super().on_200_201(session)
        self.ctx.sre_identity_written = True


@register_command("sre identity assign")
class IdentityAssign(_IdentityPatchMixin, _GeneratedIdentityAssign):
    """Assign a managed identity to an agent.

    :example: Turn on the agent's system-assigned identity
        az sre identity assign --agent-name myagent --resource-group myrg --system-assigned

    :example: Assign one or more user-assigned identities
        az sre identity assign --agent-name myagent --resource-group myrg \\
            --user-assigned "/subscriptions/.../resourceGroups/myrg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myid"
    """

    _args_schema = None

    class AgentsCreateOrUpdate(_IdentityPatchOperationMixin, _GeneratedIdentityAssign.AgentsCreateOrUpdate):
        pass


@register_command("sre identity remove")
class IdentityRemove(_IdentityPatchMixin, _GeneratedIdentityRemove):
    """Remove a managed identity from an agent.

    :example: Turn off the agent's system-assigned identity
        az sre identity remove --agent-name myagent --resource-group myrg --system-assigned

    :example: Remove one user-assigned identity
        az sre identity remove --agent-name myagent --resource-group myrg \\
            --user-assigned "/subscriptions/.../resourceGroups/myrg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myid"
    """

    _args_schema = None
    _removes_identities = True

    class AgentsCreateOrUpdate(_IdentityPatchOperationMixin, _GeneratedIdentityRemove.AgentsCreateOrUpdate):
        pass


@register_command("sre identity show")
class IdentityShow(_GeneratedIdentityShow):
    """Show the managed identities assigned to an agent.

    :example: Show an agent's identities
        az sre identity show -g myrg --agent-name myagent
    """

    _args_schema = None


@register_command("sre identity wait")
class IdentityWait(_RaiseOnWaitTimeoutMixin, _GeneratedIdentityWait):
    """Wait for an agent's identity update to finish.

    :example: Wait for an identity assignment started with --no-wait
        az sre identity wait -g myrg --agent-name myagent --updated
    """

    _args_schema = None


# --------------------------------------------------------------------------------------------
# "sre agent list-models" -- lists which default-model providers/names are
# available in a given Azure region, i.e. the real values accepted by
# 'sre agent create --default-model'. Originally its own top-level
# 'sre supported-agent-model' noun; folded into 'sre agent' and renamed to
# 'list-models' per live naming feedback ("supported-agent-model" read as
# too long/awkward, and the command is really just "what models can I use
# when creating an agent" -- same pattern as 'az account list-locations').
# Overridden here because the generated schema does not match the real wire
# field names (see _handler below).
# --------------------------------------------------------------------------------------------
def _version_info():
    """Installed extension version and the Azure API versions it calls."""
    from importlib import metadata

    try:
        extension_version = metadata.version("sre")
    except metadata.PackageNotFoundError as ex:
        raise CLIError(
            "Unable to determine the installed sre extension version: Python package "
            "metadata for 'sre' is unavailable. Reinstall the extension from a valid wheel."
        ) from ex
    return {
        "extensionName": "sre",
        "extensionVersion": extension_version,
        "apiVersions": {
            "agents": API_VERSION,
            "networking": NETWORK_API_VERSION,
            "extensions": EXTENSION_API_VERSION,
        },
    }


@register_command("sre version")
class Version(AAZCommand):
    """Show the installed extension version and the Azure API versions it uses.

    Reads installed package metadata only, so it works without signing in.
    Include the output when you report a bug.

    :example: Show version information
        az sre version
    :example: Print only the extension version
        az sre version --query extensionVersion -o tsv
    """

    def _handler(self, command_args):
        super()._handler(command_args)
        return _version_info()


@register_command("sre agent list-models")
class SupportedAgentModelList(_GeneratedListModels):
    """List the models supported for new agents in a region.

    Use this before 'sre agent create' to confirm --default-model is
    supported in the region you're deploying to.

    :example: See which models are available in East US 2
        az sre agent list-models --location eastus2
    """

    _args_schema = None

    def _handler(self, command_args):
        # Deliberately calls the BASE AAZCommand._handler (argument parsing
        # only), not _GeneratedListModels._handler (which would
        # also execute the generated AAZ-schema-deserializing HTTP call) --
        # this command does its own raw ARM GET below instead, because the
        # generated schema's 'properties.provider'/'properties.model' fields
        # don't match the real API's actual wire field names. Live-confirmed
        # via --debug: the real response uses 'providerName'/'modelName',
        # not 'provider'/'model', so the generated AAZ deserializer silently
        # drops them to None on every item (usability finding, live-graded:
        # 'list-models --output table' showed real ModelDisplayName/
        # ProviderDisplayName columns fine, but a prior fix attempt that
        # flattened 'properties.provider'/'properties.model' to top-level
        # 'provider'/'name' produced only nulls until this was caught by
        # re-checking the raw --debug response).
        AAZCommand._handler(self, command_args)
        location = _arg_value(self.ctx.args.location)
        subscription_id = self.ctx.subscription_id
        resource_id = (
            f"/subscriptions/{subscription_id}/providers/Microsoft.App/"
            f"locations/{location}/supportedAgentModels"
        )
        flattened = []
        next_url = resource_id
        while next_url:
            page = _arm_request(self.cli_ctx, "GET", next_url, API_VERSION)
            for item in (page or {}).get("value") or []:
                if not isinstance(item, dict):
                    flattened.append(item)
                    continue
                properties = item.get("properties") or {}
                # 'provider'/'name' match --default-model's own input shape
                # 1:1 (--default-model "{provider:<Provider>,name:<Name>}"),
                # so a caller can round-trip a row from this list straight
                # into 'agent create --default-model' without any string
                # splitting (usability finding, live-graded).
                flattened.append({
                    "provider": properties.get("providerName"),
                    "name": properties.get("modelName"),
                    "default": properties.get("default"),
                    "providerDisplayName": properties.get("providerDisplayName"),
                    "modelDisplayName": properties.get("modelDisplayName"),
                })
            next_url = (page or {}).get("nextLink")
        return flattened


# --------------------------------------------------------------------------------------------
# "sre agent settings" -- the agent-wide 'globalSettings' extension type
# (portal: Build + setup > Settings, preview). This is a true ARM singleton
# -- always extension type "globalSettings", always name "default"
# (confirmed via the control plane's own real round-trip integration test,
# GlobalSettingsExtensionTests.cs: `envelope = { name = "default", type =
# "GlobalSettings", properties }`, and its GET/PUT/list all operate on that
# one fixed name) -- so, unlike 'sre tool'/'sre skill'/etc., there is no
# --name to pass: show/update always target the one settings object this
# agent has. This is the only extension type exposed as its own noun
# without going through the generic _Pinned* self-invoke pattern used
# elsewhere, since it's nested two levels under 'agent' rather than being a
# top-level noun.
# --------------------------------------------------------------------------------------------
@register_command_group("sre agent settings")
class _AgentSettingsGroup(AAZCommandGroup):
    """Manage an SRE Agent's global settings (preview).

    A single, agent-wide settings object covering tool/skill allow-ask-deny
    permissions, custom instructions, and approval-expiration behavior.
    """


@register_command("sre agent settings show")
class AgentSettingsShow(AAZCommand):
    """Show an SRE Agent's global settings.

    :example: Show an agent's global settings
        az sre agent settings show --agent-name myagent --resource-group myrg
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)

        try:
            return _extension_resource_show(
                self.cli_ctx, agent_name, resource_group, "globalSettings", "default",
            )
        except ResourceNotFoundError:
            logger.warning(
                "Agent '%s' has no custom global settings configured yet "
                "(all fields default). Use 'az sre agent settings update' "
                "to set some.",
                agent_name,
            )
            return {"toolPermissions": {}, "toolStatuses": [], "skillStatuses": []}


@register_command("sre agent settings update")
class AgentSettingsUpdate(AAZCommand):
    """Create or update an SRE Agent's global settings.

    Always targets the agent's single settings object (there is no --name).
    Each call replaces the whole object, so include every field you want
    to keep. Sets the portal's "Custom instructions" box via
    --value.customInstructions (unrelated to 'sre instructions create').

    :example: Set the portal's "Custom instructions" text box
        az sre agent settings update -g myrg --agent-name myagent \\
            --value '{"customInstructions": "Always cite the runbook section you used."}'

    :example: Allow, ask for approval, or deny specific tools
        az sre agent settings update -g myrg --agent-name myagent \\
        --value '{"toolPermissions": {"allow": ["kusto-query"], "ask": [], "deny": ["run-shell"]}}'
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.value = AAZStrArg(
            options=["--value"],
            help=(
                "Settings as JSON. Optional fields: customInstructions, toolPermissions, "
                "toolStatuses, skillStatuses, approvalExpirationSetting. If you set "
                "toolPermissions, include all of allow, ask and deny (use [] if unused)."
            ),
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        raw_value = _arg_value(self.ctx.args.value)

        return _extension_resource_create(
            self.cli_ctx, agent_name, resource_group, "globalSettings", "default",
            raw_value, overwrite=True,
        )


# --------------------------------------------------------------------------------------------
# "sre managed-resource" -- matches the portal's Build + setup > Context >
# Managed resources page (tabs: Management groups / Subscriptions /
# Resource groups). Confirmed directly from the portal's "Add management
# groups" dialog text: "The agent will be granted Reader and Azure Monitor
# Monitoring Contributor roles on the selected management groups. These
# roles are inherited by all subscriptions and resources within them."
#
# This is the EXACT MIRROR IMAGE of 'sre access grant/revoke':
#   - 'sre access'          : assignee = a user/group/SP : scope = THIS agent
#                             (who can manage/use the agent)
#   - 'sre managed-resource': assignee = the agent's OWN managed identity
#                             (selected via 'sre identity show') : scope =
#                             an EXTERNAL subscription/resource-group/
#                             management-group (what the agent can read/
#                             monitor out in the world)
# Built on the same 'az role assignment create/delete/list' primitives as
# _RoleAssignmentScopeCommand above, just with assignee and scope reversed.
#
# The two built-in roles are NOT user-selectable in the portal -- the
# dialog always grants both together, so that pair is the default here.
# --roles overrides it for setups that want a different set (the
# zava-aks-postgres lab, for example, also grants Contributor and uses
# Monitoring Reader). The portal's friendly label
# "Azure Monitor Monitoring Contributor" is NOT the real role name -- the
# actual built-in RBAC role is just "Monitoring Contributor", confirmed
# live via 'az role definition list'.
# --------------------------------------------------------------------------------------------
MANAGED_RESOURCE_ROLES = ["Reader", "Monitoring Contributor"]


def _resolve_subscription_id(cli_ctx, subscription):
    """Normalize a subscription name or ID to its real subscription ID via
    'az account show', the same way portal scope-pickers resolve a
    human-picked subscription to its ARM ID."""
    invoke = partial(_cli_invoke, cli_ctx)
    account = invoke("account", "show", "--subscription", subscription)
    sub_id = (account or {}).get("id") if isinstance(account, dict) else None
    if not sub_id:
        raise CLIError(f"Could not resolve subscription '{subscription}' via 'az account show'.")
    return sub_id


def _resolve_managed_resource_scope(cli_ctx, scope, target_subscription, target_resource_group, management_group):
    """Build the ARM scope string for the 3 portal tabs (management
    groups/subscriptions/resource groups), or pass through a raw --scope
    resource ID for power users / other scope types the portal doesn't expose."""
    convenience_flags_used = any((target_subscription, target_resource_group, management_group))
    if scope and convenience_flags_used:
        raise CLIError(
            "Specify --scope on its own, or use --target-subscription/--target-rg/"
            "--management-group instead -- not both."
        )
    if scope:
        return scope
    if management_group:
        if target_subscription or target_resource_group:
            raise CLIError(
                "--management-group cannot be combined with --target-subscription/--target-rg."
            )
        return f"/providers/Microsoft.Management/managementGroups/{management_group}"
    if target_resource_group and not target_subscription:
        raise CLIError("--target-rg requires --target-subscription.")
    if target_subscription:
        sub_id = _resolve_subscription_id(cli_ctx, target_subscription)
        if target_resource_group:
            return f"/subscriptions/{sub_id}/resourceGroups/{target_resource_group}"
        return f"/subscriptions/{sub_id}"
    raise CLIError(
        "Specify a target scope: --scope, --target-subscription, --target-subscription with "
        "--target-rg, or --management-group."
    )


def _resolve_agent_principal_id(cli_ctx, agent_name, resource_group, identity="system"):
    """Resolve a selected identity from the agent's attached ARM metadata.

    The default remains system-assigned, regardless of the identities
    selected in the agent's runtime configuration.
    """
    if not isinstance(identity, str) or not identity.strip():
        raise CLIError(
            "--identity must be 'system' or the full ARM resource ID of a "
            "user-assigned identity assigned to the agent."
        )
    selector = identity.strip()
    is_system = selector.casefold() == "system"
    if not is_system and not re.fullmatch(
        r"/subscriptions/[^/\s?#]+/resourceGroups/[^/\s?#]+/providers/"
        r"Microsoft\.ManagedIdentity/userAssignedIdentities/[^/\s?#]+",
        selector, re.IGNORECASE,
    ):
        raise CLIError(
            f"Invalid --identity '{selector}'. Use 'system' or the full ARM "
            "resource ID of a user-assigned identity assigned to the agent."
        )

    invoke = partial(_cli_invoke, cli_ctx)
    assigned = invoke("sre", "identity", "show", "--agent-name", agent_name, "--resource-group", resource_group)
    if not isinstance(assigned, dict):
        raise CLIError(
            f"Could not read managed identities for agent '{agent_name}' via 'az sre identity show'."
        )
    if is_system:
        selected = assigned
        description = "system-assigned identity"
    else:
        user_assigned = assigned.get("userAssignedIdentities", {})
        if not isinstance(user_assigned, dict):
            raise CLIError(f"Could not read assigned user-assigned identities for agent '{agent_name}'.")
        assigned_id = next(
            (resource_id for resource_id in user_assigned
             if isinstance(resource_id, str) and resource_id.casefold() == selector.casefold()),
            None,
        )
        if assigned_id is None:
            raise CLIError(
                f"User-assigned identity '{selector}' is not assigned to agent '{agent_name}'. "
                "Use 'az sre identity show' to find an assigned identity."
            )
        selected = user_assigned[assigned_id]
        description = f"user-assigned identity '{assigned_id}'"

    principal_id = selected.get("principalId") if isinstance(selected, dict) else None
    if not isinstance(principal_id, str) or not principal_id.strip():
        if is_system:
            raise CLIError(
                f"Agent '{agent_name}' has no system-assigned managed identity principal ID. Run "
                "'az sre identity assign --agent-name ... --resource-group ... --system-assigned' "
                "first, or select an assigned user-assigned identity with --identity <ARM resource ID>."
            )
        raise CLIError(
            f"The {description} assigned to agent '{agent_name}' has no principal ID "
            "in 'az sre identity show'."
        )
    logger.warning("Using agent '%s' %s (principal ID: %s).", agent_name, description, principal_id)
    return principal_id


def _resolve_agent_resource_id(cli_ctx, agent_name, resource_group):
    """Resolve an agent's full ARM resource ID via 'sre agent show' -- the
    scope every 'sre access ...' command operates on (the agent itself,
    not something it has been granted access to)."""
    invoke = partial(_cli_invoke, cli_ctx)
    agent = invoke("sre", "agent", "show", "--name", agent_name, "--resource-group", resource_group)
    if not isinstance(agent, dict):
        raise ResourceNotFoundError(
            f"Could not resolve SRE Agent '{agent_name}' in resource group '{resource_group}'."
        )
    resource_id = agent.get("id")
    if not resource_id:
        raise CLIError(f"Could not resolve the resource ID of agent '{agent_name}'.")
    return resource_id


class _ManagedResourceIdentityMixin:
    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.identity = AAZStrArg(
            options=["--identity"],
            help="Agent identity to target: 'system' (default), or the full ARM resource ID "
            "of an assigned user-assigned identity. Does not change the agent's runtime identity.",
            default="system",
        )
        return schema

    def _resolve_principal_id(self):
        args = self.ctx.args
        return _resolve_agent_principal_id(
            self.cli_ctx, _arg_value(args.agent_name), _arg_value(args.resource_group),
            _arg_value(getattr(args, "identity", "system")),
        )


class _ManagedResourceScopeCommand(_ManagedResourceIdentityMixin, AAZCommand):
    """Shared base for 'managed-resource grant'/'managed-resource revoke':
    resolves the selected agent identity's principal ID and the target external scope,
    so each subclass only has to loop 'role assignment create'/'delete'
    over MANAGED_RESOURCE_ROLES with (principal_id, scope) already in hand."""

    _args_schema = None
    _VERB = None  # set by subclasses: "grant" or "revoke"

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(
            help="Resource group of the SRE Agent (NOT the target scope -- use "
            "--target-rg for that).",
            required=True,
        )
        schema.scope = AAZStrArg(
            options=["--scope"],
            help=f"Full resource ID of the scope to {cls._VERB} access on/from. "
            "Alternative to --target-subscription/--target-rg/--management-group.",
        )
        schema.target_subscription = AAZStrArg(
            options=["--target-subscription"],
            help="Target subscription name or ID. Alone: subscription scope. With --target-rg: resource-group scope.",
        )
        schema.target_resource_group = AAZStrArg(
            options=["--target-rg"],
            help="Target resource group name (requires --target-subscription). Distinct "
            "from --resource-group, which locates the agent itself.",
        )
        schema.management_group = AAZStrArg(
            options=["--management-group"],
            help="Target management group name/ID.",
        )
        schema.roles = AAZListArg(
            options=["--roles"],
            help=f"Roles to {cls._VERB} instead of the default Reader and Monitoring Contributor, "
            "e.g. --roles Reader \"Monitoring Reader\" Contributor. Names or role definition IDs.",
        )
        schema.roles.Element = AAZStrArg()
        cls._args_schema = schema
        return schema

    def _roles(self):
        roles = [r for r in (_arg_value(getattr(self.ctx.args, "roles", None)) or []) if r and r.strip()]
        return roles or list(MANAGED_RESOURCE_ROLES)

    def _resolve(self):
        principal_id = self._resolve_principal_id()
        scope = _resolve_managed_resource_scope(
            self.cli_ctx,
            _arg_value(getattr(self.ctx.args, "scope", None)),
            _arg_value(getattr(self.ctx.args, "target_subscription", None)),
            _arg_value(getattr(self.ctx.args, "target_resource_group", None)),
            _arg_value(getattr(self.ctx.args, "management_group", None)),
        )
        return principal_id, scope


@register_command_group("sre managed-resource")
class _ManagedResourceGroup(AAZCommandGroup):
    """Let the agent monitor resources outside its resource group.

    Grants/revokes the built-in 'Reader' + 'Monitoring Contributor' roles
    together on a subscription, resource group, or management group. Use
    --roles to pick different roles, e.g. Contributor or Monitoring Reader.
    Defaults to the system-assigned identity. Use --identity with an
    assigned user-assigned identity's ARM resource ID to target it instead.
    """


@register_command("sre managed-resource grant")
class ManagedResourceGrant(_ManagedResourceScopeCommand):
    """Give the agent Reader and Monitoring Contributor on a scope.

    Targets the system-assigned identity by default. Use --identity to
    select an assigned user-assigned identity without changing runtime settings.
    Use --roles to grant a different set of roles.

    :example: Grant on a subscription
        az sre managed-resource grant --agent-name myagent --resource-group myrg \\
            --target-subscription my-sub

    :example: Grant Reader, Monitoring Reader and Contributor on a resource group
        az sre managed-resource grant --agent-name myagent --resource-group myrg \\
            --target-subscription my-sub --target-rg monitored-rg \\
            --roles Reader "Monitoring Reader" Contributor

    :example: Grant on a resource group
        az sre managed-resource grant --agent-name myagent --resource-group myrg \\
            --target-subscription my-sub --target-rg monitored-rg

    :example: Grant on a management group
        az sre managed-resource grant --agent-name myagent --resource-group myrg \\
            --management-group my-mg

    :example: Grant an assigned user-assigned identity access to a resource group
        az sre managed-resource grant -g myrg --agent-name myagent \\
            --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime \\
            --target-subscription my-sub --target-rg monitored-rg
    """

    _args_schema = None
    _VERB = "grant"

    def _handler(self, command_args):
        super()._handler(command_args)
        principal_id, scope = self._resolve()
        return [
            _create_role_assignment_for_object_id(
                self.cli_ctx, principal_id, "ServicePrincipal", role, scope)
            for role in self._roles()
        ]


@register_command("sre managed-resource revoke")
class ManagedResourceRevoke(_ManagedResourceScopeCommand):
    """Remove the agent's Reader and Monitoring Contributor on a scope.

    Only removes these two roles (or the ones given with --roles) for the
    selected identity on the exact requested scope. Other identities, roles,
    and scopes are unaffected. Defaults to the system-assigned identity.

    :example: Revoke access to a resource group
        az sre managed-resource revoke --agent-name myagent --resource-group myrg \\
            --target-subscription my-sub --target-rg monitored-rg

    :example: Revoke an assigned user-assigned identity's access
        az sre managed-resource revoke -g myrg --agent-name myagent \\
            --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime \\
            --target-subscription my-sub --target-rg monitored-rg
    """

    _args_schema = None
    _VERB = "revoke"

    def _handler(self, command_args):
        super()._handler(command_args)
        principal_id, scope = self._resolve()
        invoke = partial(_cli_invoke, self.cli_ctx)
        for role in self._roles():
            invoke(
                "role", "assignment", "delete",
                "--role", role, "--assignee-object-id", principal_id, "--scope", scope,
            )


@register_command("sre managed-resource list")
class ManagedResourceList(_ManagedResourceIdentityMixin, AAZCommand):
    """List the scopes the agent's managed identity can access.

    Shows role assignments under the current subscription for the selected
    identity, not just Reader and Monitoring Contributor. Defaults to the
    system-assigned identity. Use --identity to select an assigned
    user-assigned identity.

    :example: List what an agent can currently monitor
        az sre managed-resource list --agent-name myagent --resource-group myrg

    :example: List an assigned user-assigned identity's role assignments
        az sre managed-resource list -g myrg --agent-name myagent \\
            --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(
            help="Resource group of the SRE Agent.", required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        principal_id = self._resolve_principal_id()

        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(
            "role", "assignment", "list", "--assignee-object-id", principal_id, "--all",
            "--fill-principal-name", "false",
        )


# --------------------------------------------------------------------------------------------
# "sre knowledge" -- matches the portal's Build + setup > Context > Knowledge
# sources page ("Add file" / "Add web page"), confirmed from its live nav
# and banner text ("Repository connections have moved to Code access" --
# i.e. KnowledgeRepository is being phased out of this page in favor of
# 'sre repo connect').
#
# WHY A FACADE, NOT A NEW ARM RESOURCE TYPE: knowledge items are NOT a
# separate extension type like tools/skills/hooks -- they are ordinary
# AgentConnector resources (Microsoft.App/agents/connectors) whose
# dataConnectorType happens to be one of KnowledgeFile/KnowledgeText/
# KnowledgeWebPage/KnowledgeRepository (see DATA_CONNECTOR_TYPES above).
# The portal just renders those specific connector types on their own page
# for UX reasons. So, same pattern as 'sre tool'/'sre skill': this is a
# thin front door that pins --data-connector-type and self-invokes the
# already-registered 'sre connector ...' commands -- no new ARM logic.
#
# --file-path (KnowledgeFile/KnowledgeText) reuses the already-confirmed
# _ConnectorConvenienceArgsMixin behavior via 'sre connector create'. --url
# (KnowledgeWebPage) is now also live-confirmed: extended-properties
# url=<url> alone (NOT --data-source) is the correct wire shape -- sending
# --data-source for this type causes a service-side 500.
# --------------------------------------------------------------------------------------------
KNOWLEDGE_TYPES = {
    "file": "KnowledgeFile",
    "text": "KnowledgeText",
    "webpage": "KnowledgeWebPage",
    "repository": "KnowledgeRepository",
}


@register_command_group("sre knowledge")
class _KnowledgeGroup(AAZCommandGroup):
    """Add files or web pages the agent can read and reason over.

    Use 'sre knowledge create --type file' or '--type webpage' to add one.
    Repository knowledge sources use 'sre repo connect' instead.
    """


@register_command("sre knowledge create")
class KnowledgeCreate(AAZCommand):
    """Add a knowledge source (file or web page) to an SRE Agent.

    :example: Add a local file as a knowledge source
        az sre knowledge create --agent-name myagent --resource-group myrg \\
            --name runbook-md --type file --file-path ./runbook.md

    :example: Add a web page as a knowledge source
        az sre knowledge create --agent-name myagent --resource-group myrg \\
            --name docs-site --type webpage --url https://learn.microsoft.com/azure/
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.name = AAZStrArg(
            options=["--name", "-n"], help="Name of this knowledge source.", required=True,
        )
        schema.type = AAZStrArg(
            options=["--type"],
            help="Kind of knowledge source. One of: " + ", ".join(sorted(KNOWLEDGE_TYPES)) + ".",
            required=True,
            enum={k: k for k in KNOWLEDGE_TYPES},
        )
        schema.file_path = AAZStrArg(
            options=["--file-path"],
            help="Local file to ingest. Required for --type file/text.",
        )
        schema.url = AAZStrArg(
            options=["--url"],
            help="Web page URL to ingest. Required for --type webpage. "
            "Cannot be combined with --data-source.",
        )
        schema.data_source = AAZStrArg(
            options=["--data-source"],
            help="Raw --data-source passthrough, for --type repository or any case "
            "--file-path/--url don't cover.",
        )
        schema.overwrite = AAZBoolArg(
            options=["--overwrite"],
            help="Allow replacing an existing knowledge source of the same name.",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        name = _arg_value(self.ctx.args.name)
        kind = _arg_value(self.ctx.args.type)
        file_path = _arg_value(self.ctx.args.file_path)
        url = _arg_value(self.ctx.args.url)
        data_source = _arg_value(self.ctx.args.data_source)
        overwrite = _arg_value(getattr(self.ctx.args, "overwrite", None))

        connector_type = KNOWLEDGE_TYPES[kind]
        if connector_type in ("KnowledgeFile", "KnowledgeText") and not file_path:
            raise CLIError(f"--file-path is required for --type {kind}.")
        if connector_type == "KnowledgeWebPage" and not (url or data_source):
            raise CLIError("--url (or --data-source) is required for --type webpage.")

        argv = [
            "sre", "connector", "create",
            "--agent-name", agent_name, "--resource-group", resource_group,
            "--name", name, "--data-connector-type", connector_type,
        ]
        if file_path:
            argv += ["--file-path", file_path]
        if url:
            # NOTE: sending --data-source *and* extended-properties together
            # was live-confirmed to make the service return a 500
            # (InternalServerError) for KnowledgeWebPage. extended-properties
            # url=<url> alone is the correct, live-confirmed shape --
            # KnowledgeWebPage is one of the --data-source-exempt types (see
            # KNOWLEDGE_DATA_CONNECTOR_TYPES above), so --data-source must
            # never be sent for it. Passed as JSON, not key=value shorthand --
            # shorthand syntax mis-parses the "://" in a URL as structure
            # ("Redundant tail"), live-confirmed.
            argv += ["--extended-properties", json.dumps({"url": url})]
        elif data_source:
            argv += ["--data-source", data_source]
        if overwrite:
            argv.append("--overwrite")

        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(*argv)


@register_command("sre knowledge show")
class KnowledgeShow(AAZCommand):
    """Show a knowledge source.

    :example: Show one knowledge source
        az sre knowledge show -g myrg --agent-name myagent --name docs-site
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.name = AAZStrArg(
            options=["--name", "-n"], help="Name of the knowledge source.", required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        name = _arg_value(self.ctx.args.name)

        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(
            "sre", "connector", "show",
            "--agent-name", agent_name, "--resource-group", resource_group, "--name", name,
        )


@register_command("sre knowledge list")
class KnowledgeList(AAZCommand):
    """List an SRE Agent's knowledge sources (files and web pages).

    :example: List knowledge sources
        az sre knowledge list -g myrg --agent-name myagent
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)

        invoke = partial(_cli_invoke, self.cli_ctx)
        result = invoke(
            "sre", "connector", "list",
            "--agent-name", agent_name, "--resource-group", resource_group,
        )
        items = result if isinstance(result, list) else []
        knowledge_items = [
            item for item in items
            if isinstance(item, dict)
            and item.get("properties", {}).get("dataConnectorType") in KNOWLEDGE_DATA_CONNECTOR_TYPES
        ]
        if not knowledge_items:
            logger.warning(
                "No knowledge sources found on agent '%s'. Add one with "
                "'az sre knowledge create --type file --file-path <path>' "
                "(or --type webpage --url <url>).",
                agent_name,
            )
        return knowledge_items


@register_command(
    "sre knowledge delete",
    confirmation="Are you sure you want to perform this operation?",
)
class KnowledgeDelete(AAZCommand):
    """Remove a knowledge source.

    :example: Remove a knowledge source
        az sre knowledge delete -g myrg --agent-name myagent --name docs-site
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.name = AAZStrArg(
            options=["--name", "-n"], help="Name of the knowledge source.", required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        name = _arg_value(self.ctx.args.name)
        _require_arm_resource(
            self.cli_ctx, f"{_ctx_agent_id(self.ctx)}/connectors/{quote(name, safe='')}",
            f"Knowledge source '{name}' not found on agent '{agent_name}'.")

        # Forward --yes to the inner "sre connector delete" self-invocation
        # (already confirmed once at this command's own prompt above).
        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(
            "sre", "connector", "delete",
            "--agent-name", agent_name, "--resource-group", resource_group, "--name", name,
            "--yes",
        )


@register_command("sre agent show")
class Show(_GeneratedShow):
    """Show the details of an SRE Agent.

    :example: Show one agent's details
        az sre agent show --name myagent --resource-group myrg
    """

    class AgentsGet(_GeneratedShow.AgentsGet):

        def on_200(self, session):
            _remember_unmodeled_properties(self, session)
            super().on_200(session)

    def _output(self, *args, **kwargs):
        return _with_unmodeled_properties(self.ctx, super()._output(*args, **kwargs))


@register_command("sre agent list")
class List(_GeneratedList):
    """List SRE Agents in a subscription or resource group.

    :example: List all agents in a resource group
        az sre agent list --resource-group myrg

    :example: List all agents in the current subscription
        az sre agent list
    """


@register_command("sre agent delete")
class Delete(_GeneratedDelete):
    """Delete an SRE Agent.

    :example: Delete an agent after confirming interactively
        az sre agent delete --name myagent --resource-group myrg

    :example: Delete an agent without an interactive confirmation prompt
        az sre agent delete --name myagent --resource-group myrg --yes
    """

    def pre_operations(self):
        _require_arm_resource(
            self.cli_ctx, _ctx_agent_id(self.ctx),
            f"Agent '{_arg_value(self.ctx.args.agent_name)}' not found in resource group "
            f"'{_arg_value(self.ctx.args.resource_group)}'.")
        super().pre_operations()


class _EmptyOperationResultMixin:
    """'agent start' and 'agent stop' print the operation's final result. When
    that result has no body, the generated output step raised an unexpected
    error although the agent did start or stop; print nothing instead."""

    def _output(self, *args, **kwargs):
        try:
            _ = self.ctx.vars.instance
        except AAZUnknownFieldError:
            return None
        return super()._output(*args, **kwargs)


@register_command("sre agent start")
class Start(_EmptyOperationResultMixin, _GeneratedStart):
    """Start a stopped SRE Agent.

    :example: Start a stopped agent
        az sre agent start --name myagent --resource-group myrg
    """


@register_command("sre agent stop")
class Stop(_EmptyOperationResultMixin, _GeneratedStop):
    """Stop a running SRE Agent.

    :example: Stop a running agent
        az sre agent stop --name myagent --resource-group myrg
    """


@register_command("sre agent wait")
class Wait(_RaiseOnWaitTimeoutMixin, _GeneratedWait):
    """Wait for an SRE Agent to reach a desired state.

    :example: Wait until an agent created with --no-wait finishes provisioning
        az sre agent wait -g myrg --agent-name myagent --created
    """

    _args_schema = None


@register_command("sre endpoint show")
class GetConnection(AAZCommand):
    """Save an agent's data-plane endpoint for other tools.

    Like 'az aks get-credentials', it writes the connection details that
    data-plane tools read.

    :example: Resolve and save the data-plane endpoint for an agent
        az sre endpoint show --agent-name myagent --resource-group myrg
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
                "Audience for the data-plane access token."
            ),
            default="https://azuresre.dev",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        # str(...) here is required, not cosmetic: when --data-plane-audience
        # is left at its declared default, AAZ resolves it to a
        # knack.validators.DefaultStr (a str subclass carrying an
        # `is_default` flag for CLI recommendation messages). That subclass
        # round-trips fine through json.dump() (used below for the on-disk
        # connections file) but az's own command-output formatter does NOT
        # treat it as a plain string -- it gets introspected via vars() and
        # rendered as "{\"isDefault\": true}" in the command's JSON output.
        # Coercing to a real str here avoids that misrender without
        # affecting the on-disk file, which already worked correctly.
        audience = str(_arg_value(self.ctx.args.data_plane_audience))

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
                f"Agent '{name}' has no 'agentEndpoint' yet. It may still be "
                "provisioning. Check 'provisioningState' in 'az sre agent show'."
            )

        connections = {}
        if os.path.exists(_CONNECTIONS_FILE):
            try:
                with open(_CONNECTIONS_FILE, "r", encoding="utf-8") as handle:
                    connections = json.load(handle)
            except (OSError, ValueError) as ex:
                raise CLIError(
                    f"Could not read existing {_CONNECTIONS_FILE} ({ex}). "
                    "The file was left unchanged; fix or delete it and retry."
                ) from ex
            if not isinstance(connections, dict):
                raise CLIError(
                    f"{_CONNECTIONS_FILE} does not contain a JSON object. "
                    "The file was left unchanged; fix or delete it and retry."
                )
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


@register_command("sre usage list")
class ListUsage(AAZCommand):
    """List monthly or daily agent-unit usage for an SRE Agent.

    :example: List this month's usage for an agent
        az sre usage list --agent-name myagent --resource-group myrg
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

        agent_id = (
            f"/subscriptions/{self.ctx.subscription_id}/resourceGroups/{resource_group}"
            f"/providers/Microsoft.App/agents/{name}"
        )
        _require_arm_resource(
            self.cli_ctx, agent_id, f"Agent '{name}' not found in resource group '{resource_group}'.")

        # Return the items, not the raw page, so -o table can show them, and
        # follow nextLink like 'agent list-models' does.
        suffix = "dailyusages" if daily else "usages"
        items = []
        page = _arm_request(self.cli_ctx, "GET", f"{agent_id}/{suffix}", API_VERSION)
        while True:
            items.extend((page or {}).get("value") or [])
            next_link = (page or {}).get("nextLink")
            if not next_link:
                return items
            page = _arm_request(self.cli_ctx, "GET", next_link, API_VERSION)


@register_command_group("sre agent")
class _AgentGroup(AAZCommandGroup):
    """Manage the core lifecycle of an SRE Agent resource.

    Create, show, list, update, delete, start, and stop an agent.
    """


@register_command_group("sre access")
class _AccessGroup(AAZCommandGroup):
    """Control who can manage or use an SRE Agent.

    This is the mirror image of 'sre managed-resource': that group grants
    the agent's own identity access to things outside itself, while this
    group grants other people/principals access to the agent itself.
    """


@register_command_group("sre endpoint")
class _EndpointGroup(AAZCommandGroup):
    """Resolve the URL used to actually talk to an SRE Agent's data plane.

    Use 'sre endpoint show' to look up and save that live endpoint.
    """


@register_command_group("sre usage")
class _UsageGroup(AAZCommandGroup):
    """Read an SRE Agent's usage and billing stats.

    Token counts and request counts, for a month or broken down by day.
    Use 'sre usage list' to see how much an agent has used.
    """


@register_command_group("sre network")
class _NetworkGroup(AAZCommandGroup):
    """Control an SRE Agent's sandbox networking (preview).

    Configures VNet injection and outbound egress for the agent's own
    sandboxed tool and code execution. It doesn't control inbound access to
    the agent resource.
    """


@register_command_group("sre repo")
class _RepoGroup(AAZCommandGroup):
    """Connect a code repository so the agent can read source during investigations.

    Supports GitHub and Azure DevOps. GitLab isn't exposed by this CLI yet.
    """


class _RoleAssignmentScopeCommand(AAZCommand):
    """Shared base for 'access grant'/'access revoke': builds the agent's
    full resource-ID scope and turns --assignee/--assignee-me into
    'role assignment' arguments.
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
    _VERB = None  # set by subclasses: "grant" or "revoke"

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help=f"Name of the SRE Agent to {cls._VERB} access on.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.role = AAZStrArg(
            options=["--role"],
            help=f"Built-in role to {cls._VERB}: 'admin', 'user', 'author', or 'reader'.",
            required=True,
            enum={key: key for key in cls._ROLES},
        )
        schema.assignee = AAZStrArg(
            options=["--assignee"],
            help=f"User, group, or service principal object ID/UPN to {cls._VERB} the role "
            "for. Required unless --assignee-me is passed instead.",
        )
        schema.assignee_me = AAZBoolArg(
            options=["--assignee-me"],
            help="Use the signed-in account as the assignee. Reads your object ID from "
            "your Azure access token, without Microsoft Graph. Alternative to --assignee.",
        )
        cls._args_schema = schema
        return schema

    def _resolve_assignee(self, for_create):
        """Return (role-assignment args, object_id). object_id is set only
        for --assignee-me; --assignee is passed through unchanged (Azure CLI
        resolves emails/UPNs with Microsoft Graph). 'role assignment delete'
        has no --assignee-principal-type option."""
        assignee = _arg_value(getattr(self.ctx.args, "assignee", None))
        assignee_me = bool(_arg_value(getattr(self.ctx.args, "assignee_me", None)))
        if assignee and assignee_me:
            raise CLIError("Specify either --assignee or --assignee-me, not both.")
        if assignee_me:
            object_id, principal_type = _resolve_signed_in_principal(self.cli_ctx)
            args = ("--assignee-object-id", object_id)
            if for_create:
                args += ("--assignee-principal-type", principal_type)
            return args, object_id
        if not assignee:
            raise CLIError("Specify --assignee <object-id/UPN> or --assignee-me.")
        return ("--assignee", assignee), None

    def _resolve_resource_id(self, name, resource_group):
        return _resolve_agent_resource_id(self.cli_ctx, name, resource_group)


@register_command("sre access grant")
class GrantAccess(_RoleAssignmentScopeCommand):
    """Grant an agent role to a user, group or principal.

    :example: Grant yourself admin access to an agent
        az sre access grant --name myagent --resource-group myrg --role admin --assignee-me

    :example: Grant a user read-only access
        az sre access grant --name myagent --resource-group myrg --role reader --assignee someone@contoso.com
    """

    _args_schema = None
    _VERB = "grant"

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        role_key = _arg_value(self.ctx.args.role)
        role_name = self._ROLES[role_key]
        assignee_args, object_id = self._resolve_assignee(for_create=True)
        resource_id = self._resolve_resource_id(name, resource_group)

        if object_id:
            existing = _find_role_assignment(self.cli_ctx, object_id, role_name, resource_id)
            if existing is not None:
                return existing
        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(
            "role", "assignment", "create",
            "--role", role_name,
            *assignee_args,
            "--scope", resource_id,
        )


@register_command("sre access revoke")
class RevokeAccess(_RoleAssignmentScopeCommand):
    """Revoke an agent role from a user, group or principal.

    :example: Revoke a user's access to an agent
        az sre access revoke --name myagent --resource-group myrg --role user --assignee someone@contoso.com
    """

    _args_schema = None
    _VERB = "revoke"

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        role_key = _arg_value(self.ctx.args.role)
        role_name = self._ROLES[role_key]
        assignee_args, _ = self._resolve_assignee(for_create=False)
        resource_id = self._resolve_resource_id(name, resource_group)

        invoke = partial(_cli_invoke, self.cli_ctx)
        return invoke(
            "role", "assignment", "delete",
            "--role", role_name,
            *assignee_args,
            "--scope", resource_id,
        )


@register_command("sre access list")
class AccessList(AAZCommand):
    """List who has access to an SRE Agent.

    Shows every role assignment scoped to the agent itself, by object ID.
    Use --show-names to add display names from Microsoft Graph.

    :example: List everyone with access to an agent
        az sre access list --name myagent --resource-group myrg

    :example: Include display names
        az sre access list --name myagent --resource-group myrg --show-names
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to list access on.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.show_names = AAZBoolArg(
            options=["--show-names"],
            help="Add principal display names from Microsoft Graph. Some organizations' "
            "policies block Graph for Azure CLI on macOS.",
            default=False,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        resource_id = _resolve_agent_resource_id(self.cli_ctx, name, resource_group)

        args = ["role", "assignment", "list", "--scope", resource_id]
        if not bool(_arg_value(getattr(self.ctx.args, "show_names", None))):
            args += ["--fill-principal-name", "false"]
        return _cli_invoke(self.cli_ctx, *args)


@register_command("sre network update")
class UpdateNetwork(AAZCommand):
    """Configure VNet injection and sandbox egress (preview).

    :example: Limit the agent's sandbox egress to one allowed host
        az sre network update --name myagent --resource-group myrg \\
            --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}"
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
            nullable=True, options=["subnet-resource-id"],
            help="Resource ID of a delegated subnet (Microsoft.Network/virtualNetworks/subnets) for the agent.",
        )

        schema.sandbox_configuration = AAZObjectArg(
            options=["--sandbox-configuration"],
            help=(
                "Sandbox egress and packages. Shorthand, e.g. \"{egress:{mode:Limited,allowed-hosts:[example.com]}}\"."
            ),
        )
        sandbox_configuration = schema.sandbox_configuration
        sandbox_configuration.egress = AAZObjectArg(
            nullable=True, options=["egress"],
            help="Egress configuration for the agent's sandbox.",
        )
        sandbox_configuration.packages = AAZListArg(
            nullable=True, options=["packages"],
            help="Packages to pre-install in the sandbox.",
        )
        sandbox_configuration.packages.Element = AAZObjectArg()
        package_element = sandbox_configuration.packages.Element
        package_element.name = AAZStrArg(nullable=True, options=["name"], help="Package name.")
        package_element.version = AAZStrArg(nullable=True, options=["version"], help="Package version.")
        package_element.package_manager = AAZStrArg(
            nullable=True, options=["package-manager"],
            help="Package manager: pip, npm, or nuget.",
        )

        egress = sandbox_configuration.egress
        egress.mode = AAZStrArg(
            nullable=True, options=["mode"],
            help="Sandbox egress mode.",
            enum={"Unrestricted": "Unrestricted", "Limited": "Limited", "AzureVNet": "AzureVNet"},
        )
        egress.allow_http_mcp_server_network_access = AAZBoolArg(
            nullable=True, options=["allow-http-mcp-server-network-access"],
            help="Allow the sandbox to reach HTTP MCP servers over the network.",
        )
        egress.allowed_hosts = AAZListArg(
            nullable=True, options=["allowed-hosts"],
            help="Hosts the sandbox is allowed to reach when in Limited mode.",
        )
        egress.allowed_hosts.Element = AAZStrArg()
        egress.allowed_registries = AAZListArg(
            nullable=True, options=["allowed-registries"],
            help="Package registries the sandbox is allowed to reach (e.g. pypi, npmjs, nuget-org, ubuntu).",
        )
        egress.allowed_registries.Element = AAZStrArg()
        egress.allowed_code_repositories = AAZListArg(
            nullable=True, options=["allowed-code-repositories"],
            help="Code repository hosts the sandbox is allowed to reach (e.g. Github, GithubEnterprise, AzureDevOps, GitLab).",
        )
        egress.allowed_code_repositories.Element = AAZStrArg()
        egress.vnet_configuration = AAZObjectArg(
            nullable=True, options=["vnet-configuration"],
            help="VNet-specific egress configuration (distinct from the top-level --vnet-configuration, which is for the agent itself).",
        )
        egress.vnet_configuration.use_private_dns_resolution = AAZBoolArg(
            nullable=True, options=["use-private-dns-resolution"],
            help="Use private DNS resolution for sandbox VNet egress.",
        )
        egress.http_proxy = AAZObjectArg(
            nullable=True, options=["http-proxy"],
            help="Forward-proxy endpoints for sandbox outbound HTTP/HTTPS traffic.",
        )
        egress.http_proxy.http_url = AAZStrArg(nullable=True, options=["http-url"], help="Proxy URL for plain HTTP.")
        egress.http_proxy.https_url = AAZStrArg(nullable=True, options=["https-url"], help="Proxy URL for HTTPS.")
        egress.http_proxy.no_proxy = AAZListArg(
            nullable=True, options=["no-proxy"],
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

        # PATCH only the networking properties. A GET-then-PUT of the whole
        # agent fails on agents with App Insights logging, because the GET
        # hides the connection string and the PUT then sends an appId alone.
        # `network show` prints unset fields as null; drop them so its output
        # can be passed back here unchanged.
        properties = {}
        for flag, key, value in (
            ("--vnet-configuration", "vnetConfiguration", vnet_configuration),
            ("--sandbox-configuration", "sandboxConfiguration", sandbox_configuration),
        ):
            if value is None:
                continue
            properties[key] = _drop_nulls(_camelize_keys(value))
            if not _has_network_setting(properties[key]):
                raise CLIError(
                    f"{flag} has nothing to set. Fields set to null are ignored, so this command "
                    "can't clear a setting.")
        proxy = ((sandbox_configuration or {}).get("egress") or {}).get("http_proxy") or {}
        if any("@" in urlparse(url).netloc for url in (proxy.get("http_url"), proxy.get("https_url"))
               if isinstance(url, str)):
            _warn_if_secret_typed(
                "--sandbox-configuration",
                "put the configuration in a JSON file and pass --sandbox-configuration @file")

        # Proxy URLs can carry credentials, in this request and in the agent the
        # service sends back, so keep the bodies out of --debug and az.log.
        with _no_http_trace():
            resource_id = _resolve_agent_resource_id(self.cli_ctx, name, resource_group)
            updated = _arm_request(
                self.cli_ctx, "PATCH", resource_id, NETWORK_API_VERSION, body={"properties": properties},
            )
            if not (isinstance(updated, dict) and updated.get("properties")):
                updated = _arm_request(self.cli_ctx, "GET", resource_id, NETWORK_API_VERSION)

        # The PATCH targets the agent resource itself, so trim the response to
        # the networking fields like the other extension commands do.
        return _network_view(updated)


def _has_network_setting(value):
    """True if a null-free network configuration still sets something. A list
    counts, even an empty one: it replaces the stored list."""
    if isinstance(value, dict):
        return any(_has_network_setting(item) for item in value.values())
    return value is not None


def _network_view(agent):
    if not isinstance(agent, dict):
        return agent
    properties = agent.get("properties") or {}
    return {
        "id": agent.get("id"),
        "name": agent.get("name"),
        # ARM never returns resourceGroup, and a key set to None also stops the
        # Azure CLI output transform from filling it in, so derive it from the ID.
        "resourceGroup": parse_resource_id(agent.get("id")).get("resource_group"),
        "type": agent.get("type"),
        "provisioningState": properties.get("provisioningState"),
        "vnetConfiguration": properties.get("vnetConfiguration"),
        "sandboxConfiguration": properties.get("sandboxConfiguration"),
    }


@register_command("sre network show")
class ShowNetwork(AAZCommand):
    """Show VNet injection and sandbox egress settings (preview).

    'az sre agent show' omits these because it uses an older API version.

    :example: Show an agent's networking settings
        az sre network show --name myagent --resource-group myrg
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.name = AAZStrArg(
            options=["-n", "--name", "--agent-name"],
            help="Name of the SRE Agent to show networking settings for.",
            required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        name = _arg_value(self.ctx.args.name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        resource_id = _resolve_agent_resource_id(self.cli_ctx, name, resource_group)
        current = _arm_request(self.cli_ctx, "GET", resource_id, NETWORK_API_VERSION, missing_ok=True)
        if not isinstance(current, dict):
            raise ResourceNotFoundError(
                f"Could not find SRE Agent '{name}' in resource group '{resource_group}' at api-version {NETWORK_API_VERSION}."
            )
        return _network_view(current)


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
# Hand-written the same way 'network update' is: no codegen, _arm_request
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


# Per-extension-type inner JSON shape, confirmed where noted. The control-
# plane repo's own route (AgentExtensionsApiController.cs) is a pure
# base64 pass-through with zero shape validation -- it never tells us if
# a payload is malformed until the data-plane cluster rejects it. We
# tighten client-side only for shapes we've actually confirmed from real
# source (see issue #13 -- 15 of 15 extension types confirmed via
# sreagent-runtime authoritative source + live round-trips, including
# 'subagents': a CORRECTION of an earlier, WRONG conclusion that it was
# "not creatable this way". That earlier test used the portal's own
# kubectl-apply-style YAML document shape (api_version: azuresre.ai/v1,
# kind: AgentConfiguration, snake_case fields) against this ARM-proxied
# route -- the wrong payload shape for this route, not proof the route
# itself rejects subagents. A live benchmark test (2026-11-05) against a
# real test agent, using the plain JSON shape below (instructions/
# handoffDescription/tools/mcpTools/commonTools/allowedSkills/
# allowParallelToolCalls/hooks), round-tripped successfully through this
# exact ARM-proxied route -- see _validate_subagents_shape below and
# 'sre subagent create'.
#
# commonPrompts: CORRECTED after live verification against a real test
# agent's data-plane (2026-10-25). The earlier reading of
# DebugApp/Client/ModelPromptsViewer.tsx's TS prop type
# (`commonPrompts?: string | Array<{ name: string; content: string }>`) was
# WRONG for the per-resource wire shape -- that type describes an
# aggregated, multi-resource UI display value, not what a single PUT
# accepts. Live testing (PUT with --debug + raw `az rest` probes against
# a real test agent) proved: the real data-plane requires the decoded root value
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
            "--value must be a JSON object of the form {\"prompt\": \"...\"}."
        )
    if "prompt" not in parsed or not isinstance(parsed["prompt"], str):
        raise CLIError(
            "--value must include a string 'prompt' field."
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
            "--value must be a JSON object that describes the agent settings."
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
            raise CLIError("--value.toolPermissions must be a JSON object with 'allow'/'ask'/'deny' arrays.")
        for key in ("allow", "ask", "deny"):
            _require_str_list(tp, key, "--value.toolPermissions")
        # All-or-nothing, live-confirmed this session: the real API rejects
        # --value.toolPermissions if it's present but missing any of
        # allow/ask/deny, with a generic "contains an invalid or
        # unrecognized property" error that actually means the opposite --
        # a sibling property is MISSING, not unrecognized. Isolated by
        # testing '{}' (succeeds) vs. '{"toolPermissions":{"deny":[...]}}'
        # (fails) against a real agent. Caught here client-side with an
        # accurate message instead of surfacing that misleading 400.
        missing = [key for key in ("allow", "ask", "deny") if key not in tp]
        if missing:
            raise CLIError(
                "--value.toolPermissions is missing "
                f"{', '.join(repr(k) for k in missing)}. When toolPermissions "
                "is set, it needs all three lists: 'allow', 'ask' and 'deny'. "
                "Use [] for any list you don't need."
            )

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
        raise CLIError("--value must be a JSON object that describes the plugin marketplace.")
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
        raise CLIError("--value must be a JSON object that describes the plugin to install.")
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
    """Validate incident-filter properties before sending them to the service."""
    if not isinstance(parsed, dict):
        raise CLIError("--value must be a JSON object that describes the incident filter.")
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
    if "handlingAgent" in parsed and not isinstance(parsed["handlingAgent"], str):
        raise CLIError("--value.handlingAgent must be a string (the name of an existing subagent).")
    if "impactedService" in parsed and not isinstance(parsed["impactedService"], str):
        raise CLIError("--value.impactedService must be a string.")
    if "mergeEnabled" in parsed and not isinstance(parsed["mergeEnabled"], bool):
        raise CLIError("--value.mergeEnabled must be a boolean.")
    if "mergeWindowHours" in parsed and (
            isinstance(parsed["mergeWindowHours"], bool) or not isinstance(parsed["mergeWindowHours"], int)):
        raise CLIError("--value.mergeWindowHours must be an integer.")
    if "maxAutomatedInvestigationAttempts" in parsed and (
            isinstance(parsed["maxAutomatedInvestigationAttempts"], bool)
            or not isinstance(parsed["maxAutomatedInvestigationAttempts"], int)):
        raise CLIError("--value.maxAutomatedInvestigationAttempts must be an integer.")
    for list_field in ("owningTeamIds", "handlingAgents"):
        if list_field in parsed:
            value = parsed[list_field]
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise CLIError(f"--value.{list_field} must be a JSON array of strings.")
    _require_str(parsed, "alertId", "--value")
    if "azMonitorFilterSettings" in parsed:
        settings = parsed["azMonitorFilterSettings"]
        if not isinstance(settings, dict):
            raise CLIError("--value.azMonitorFilterSettings must be a JSON object.")
        for key in ("targetResourceType", "targetResource"):
            _require_str(settings, key, "--value.azMonitorFilterSettings")


def _validate_incident_handlers_shape(parsed):
    """Validate the flat incident-handler document."""
    if not isinstance(parsed, dict):
        raise CLIError("--value must be a JSON object that describes the incident handler.")
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
def _validate_tools_shape(parsed):  # pylint: disable=too-many-branches
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value must be a JSON object that describes the tool."
        )
    valid_types = ("KustoTool", "LinkTool", "PythonFunctionTool", "PythonTool", "HttpClientTool")
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
    elif tool_type in ("PythonFunctionTool", "PythonTool"):
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


# subagents: live-confirmed end-to-end against a real test agent (benchmark
# session, 2026-11-05) -- a PUT to this ARM-proxied extension type with this
# exact field set round-trips successfully and the server echoes back a much
# richer canonical shape (handoffs, connectors, agentsAsTools,
# maxReflectionCount, criticPromptPath, criticOnHandOff,
# customReflectionNote, commonPrompts, disableDocumentRetrieval,
# enableHandoffPromptOverride, userPromptOverride, handoffPromptOverride,
# instructionsOverride, temperature, llmModelName, enableVanillaMode,
# enableSkills, addSystemSkills, outputType, hooks, permissions -- all
# server-defaulted to null when omitted). An EARLIER conclusion recorded in
# this file's EXTENSION_TYPES comment ("'subagents' is now CONFIRMED not
# creatable this way") was WRONG -- it was based on a flawed experiment
# (either the wrong extension-type path segment, e.g. "agents" instead of
# "subagents", or the portal's YAML-apply shape sent to the wrong route).
# Embedding a per-agent hook (the portal's "Manage Hooks" button inside the
# "Create a custom agent" dialog) is just the "hooks" field on this same
# resource -- confirmed live with
# hooks: {"PreToolUse": [{"type": "command", "matcher": "...", "timeout": 30,
# "failMode": "block", "script": "..."}]}.
def _validate_subagents_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value must be a JSON object that describes the sub-agent."
        )
    _require_str(parsed, "instructions", "--value")
    instructions = parsed.get("instructions")
    if instructions and instructions.strip() and len(instructions) < 50:
        raise CLIError(
            "--value.instructions must be at least 50 characters. "
            "Expand the sub-agent instructions with meaningful guidance and retry."
        )
    _require_str(parsed, "handoffDescription", "--value")
    _require_str_list(parsed, "tools", "--value")
    _require_str_list(parsed, "mcpTools", "--value")
    _require_str_list(parsed, "commonTools", "--value")
    _require_str_list(parsed, "allowedSkills", "--value")
    _require_bool(parsed, "allowParallelToolCalls", "--value")
    if "hooks" in parsed:
        hooks = parsed["hooks"]
        if not isinstance(hooks, dict):
            raise CLIError("--value.hooks must be a JSON object.")
        for event_type in ("Start", "PreToolUse", "PostToolUse", "Stop"):
            if event_type not in hooks:
                continue
            entries = hooks[event_type]
            if not isinstance(entries, list):
                raise CLIError(f"--value.hooks.{event_type} must be a JSON array.")
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    raise CLIError(f"--value.hooks.{event_type}[{idx}] must be a JSON object.")
                _require_str(entry, "type", f"--value.hooks.{event_type}[{idx}]")
                _require_str(entry, "matcher", f"--value.hooks.{event_type}[{idx}]")
                _require_str(entry, "script", f"--value.hooks.{event_type}[{idx}]")
                _require_str(entry, "failMode", f"--value.hooks.{event_type}[{idx}]")
                if "timeout" in entry and not isinstance(entry["timeout"], (int, float)):
                    raise CLIError(f"--value.hooks.{event_type}[{idx}].timeout must be a number.")


# skills: confirmed via sreagent-runtime Agent.Cli/Models/ExtendedSkillV2.cs
# (SkillSpecV2). The CLI's primary authoring format is SKILL.md with
# frontmatter (name/description/tools), but the API-facing fields map to
# description/tools/skillContent -- only description and tools are
# settable-looking JSON fields; skillContent is markdown body text.
def _validate_skills_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value must be a JSON object that describes the skill."
        )
    _require_str(parsed, "description", "--value")
    _require_str_list(parsed, "tools", "--value")
    _require_str(parsed, "skillContent", "--value")


# hooks: confirmed via sreagent-runtime Agent.Cli/Models/HookV2.cs
# (HookSpecV2/HookDefinitionModel) -- these fields carry explicit
# [JsonPropertyName] attributes confirming camelCase wire field names
# distinct from (but matching) the YAML aliases, the strongest evidence
# available for any type this session.
#
# eventType: the official docs (sre.azure.com/docs/capabilities/agent-hooks)
# confirm FOUR lifecycle events -- Start, PreToolUse, PostToolUse, Stop --
# all configurable via the REST API v2 (which is what this CLI calls). The
# portal UI currently only exposes PostToolUse/Stop in its own "Create hook"
# dialog, but that's a portal UI limitation, not an API one -- restricting
# this CLI's client-side validation to match the portal's subset would
# incorrectly reject valid Start/PreToolUse hooks that the API accepts.
def _validate_hooks_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value must be a JSON object that describes the hook."
        )
    if "eventType" in parsed:
        if not isinstance(parsed["eventType"], str) or parsed["eventType"] not in (
            "Start", "PreToolUse", "PostToolUse", "Stop",
        ):
            raise CLIError(
                "--value.eventType must be one of \"Start\", \"PreToolUse\", "
                "\"PostToolUse\", \"Stop\"."
            )
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
        # failMode governs what happens if the hook itself errors/times out
        # (NOT the hook's allow/deny decision output) -- live-probed against
        # a real agent: "Allow"/"Block" (case-insensitive) are accepted,
        # "Deny"/"fail"/"continue" are rejected by the real API with a
        # generic "extension configuration is invalid" error.
        if "failMode" in hook:
            if not isinstance(hook["failMode"], str) or hook["failMode"].lower() not in ("allow", "block"):
                raise CLIError("--value.hook.failMode must be \"Allow\" or \"Block\".")
        # matcher is effectively required for PreToolUse/PostToolUse --
        # live-confirmed this session: an otherwise-identical, client-side-
        # valid payload for these two event types is rejected by the real
        # API with the same opaque "The extension configuration is invalid"
        # error when --value.hook.matcher is missing, but the IDENTICAL
        # payload succeeds once --value.hook.matcher (a tool-name regex,
        # e.g. "Bash.*") is added. Start/Stop hooks (which aren't scoped to
        # a specific tool) do NOT need matcher -- confirmed accepted without
        # it. Caught here client-side instead of surfacing as that same
        # opaque 400 from ARM.
        event_type = parsed.get("eventType")
        if event_type in ("PreToolUse", "PostToolUse") and not hook.get("matcher"):
            raise CLIError(
                "--value.hook.matcher is required when --value.eventType is "
                "\"PreToolUse\" or \"PostToolUse\". Set it to a regular "
                "expression that matches tool names, for example \"Bash.*\"."
            )
        for str_field in ("prompt", "command", "script", "matcher", "model"):
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
            "--value must be a JSON object that describes the scheduled task."
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
    _require_bool(parsed, "isEnabled", "--value")
    if "status" in parsed and parsed["status"] not in SCHEDULED_TASK_STATUSES:
        raise CLIError(
            "--value.status must be one of: " + ", ".join(f'"{s}"' for s in SCHEDULED_TASK_STATUSES) + ".")
    if "isEnabled" in parsed and "status" in parsed and parsed["status"] != (
            "Active" if parsed["isEnabled"] else "Paused"):
        raise CLIError("--value.isEnabled and --value.status disagree; set only one of them.")


SCHEDULED_TASK_STATUSES = ("Active", "Paused", "Completed", "Failed", "Expired")


def _scheduled_task_enabled_to_status(parsed):
    """The service has no isEnabled field on scheduled tasks; it pauses them through status."""
    if isinstance(parsed, dict) and "isEnabled" in parsed:
        enabled = parsed.pop("isEnabled")
        parsed.setdefault("status", "Active" if enabled else "Paused")
        return True
    return False


# repositories: confirmed via sreagent-runtime
# Agent.Cli/Models/RepositoryV2.cs's own RepositoryV2.Validate() method,
# the most direct evidence available (actual shipped validation logic,
# not just a model shape guess).
def _validate_repositories_shape(parsed):
    if not isinstance(parsed, dict):
        raise CLIError(
            "--value must be a JSON object that describes the repository."
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
            "--value must be a JSON object that describes the GitHub credentials."
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
            "--value must be a JSON object that describes the Azure DevOps credentials."
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
            "--value must be a JSON object that describes the HTTP trigger."
        )
    for str_field in ("name", "description", "agentPrompt", "agent", "modelTier", "threadId"):
        _require_str(parsed, str_field, "--value")
    if "agentMode" in parsed:
        if not isinstance(parsed["agentMode"], str) or parsed["agentMode"].lower() not in (
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
    "subagents": _validate_subagents_shape,
    "hooks": _validate_hooks_shape,
    "scheduledTasks": _validate_scheduled_tasks_shape,
    "repositories": _validate_repositories_shape,
    "githubAuths": _validate_github_auths_shape,
    "azureDevOpsAuths": _validate_azure_devops_auths_shape,
    "httpTriggers": _validate_http_triggers_shape,
}


def _normalize_extension_value(raw_value, extension_type=None):
    """Parse and validate a user-supplied --value, returning the JSON text to
    send. Applies a per-type shape check for any extension_type we have a
    confirmed real shape for (see EXTENSION_VALUE_VALIDATORS) -- unconfirmed
    types only get the baseline JSON-syntax check. The legacy PythonTool name
    is normalized to the runtime's PythonFunctionTool discriminator. Shared by
    the ARM and direct (agent endpoint) create paths.
    """

    try:
        parsed = json.loads(raw_value)
    except (TypeError, ValueError) as ex:
        raise CLIError(
            f"--value must be a JSON document (it is base64-encoded and sent "
            f"as-is to the agent's data plane): {ex}"
        ) from ex
    if extension_type == "tools" and isinstance(parsed, dict) and parsed.get("type") == "PythonTool":
        parsed["type"] = "PythonFunctionTool"
        raw_value = json.dumps(parsed)
    # The service matches agent modes case-insensitively and stores them lowercase.
    if (extension_type in ("httpTriggers", "scheduledTasks") and isinstance(parsed, dict)
            and isinstance(parsed.get("agentMode"), str) and parsed["agentMode"] != parsed["agentMode"].lower()):
        parsed["agentMode"] = parsed["agentMode"].lower()
        raw_value = json.dumps(parsed)
    validator = EXTENSION_VALUE_VALIDATORS.get(extension_type)
    if validator is not None:
        validator(parsed)
    if extension_type == "scheduledTasks" and _scheduled_task_enabled_to_status(parsed):
        raw_value = json.dumps(parsed)
    return raw_value


def _encode_extension_value(raw_value, extension_type=None):
    """Base64-encode a validated --value for properties.value, the wire format
    confirmed in Agents.http (e.g. pluginMarketplaces' example body)."""
    raw_value = _normalize_extension_value(raw_value, extension_type)
    return base64.b64encode(raw_value.encode("utf-8")).decode("ascii")


def _is_http_client_tool(extension_type, raw_value):
    if extension_type != "tools":
        return False
    parsed = json.loads(raw_value)
    return isinstance(parsed, dict) and parsed.get("type") == "HttpClientTool"


def _require_existing_http_client_tool(existing_tool):
    if not isinstance(existing_tool, dict) or existing_tool.get("type") != "HttpClientTool":
        raise CLIError(
            "Creating new HttpClientTool tools is no longer supported. "
            "--overwrite can update an existing HttpClientTool of the same name, "
            "but cannot create one or replace a different tool type. "
            "Use PythonFunctionTool or an MCP server for new HTTP integrations."
        )


def _decode_extension_envelope(envelope):
    """Best-effort base64-decode (and, if it parses, JSON-parse) an
    extension envelope's properties.value for human-readable display.
    Falls back to leaving the raw base64 untouched if it's not valid
    UTF-8/JSON -- some extension types may carry opaque/binary payloads.
    """
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


# There is intentionally no public "sre extension ..." command group. There
# used to be one (a direct, flat mirror of the ARM resource shape,
# Microsoft.App/agents/<extensionType>/<name>), but it was removed per
# design-review feedback ("I find it confusing there is both plugin and
# extension -- why? what is the main concept in the portal?"): the portal
# has no "extension" concept at all, it was purely this CLI's internal ARM-
# proxy abstraction leaking into the user-facing surface. The functions
# below are the same logic, kept as plain internal helpers that every
# noun-specific facade (tool/skill/subagent/hook/instructions/automation/
# plugin/repo/agent settings/response-plan) calls
# directly -- there is no user-reachable path to an arbitrary
# --extension-type anymore. 'globalSettings' is exposed via
# 'sre agent settings' below instead. 'incidentHandlers' previously had no
# dedicated noun -- corrected: it is the response-plan half of the current
# Microsoft Learn "Set Up Incident Response" tutorial, not legacy, so it
# is covered by 'sre response-plan', together with 'incidentFilters'.
EXTENSION_TYPE_CREATE_NOUN = {
    "tools": "az sre tool create",
    "skills": "az sre skill create",
    "subagents": "az sre subagent create",
    "hooks": "az sre hook create",
    "commonPrompts": "az sre instructions create",
    "scheduledTasks": "az sre automation scheduled-task create",
    "httpTriggers": "az sre automation http-trigger create",
    "incidentFilters": "az sre response-plan create",
    "incidentHandlers": "az sre response-plan create",
    "pluginMarketplaces": "az sre plugin marketplace create",
    "pluginInstallations": "az sre plugin install create",
    "repositories": "az sre repo connect",
    "githubAuths": "az sre repo connect",
    "azureDevOpsAuths": "az sre repo connect",
    "globalSettings": "az sre agent settings update",
}


INTERNAL_TENANT_ONLY_MARKER = "restricted to internal tenants only"
DIRECT_EXTENSION_ROUTES = {
    "tools": ("/api/v2/extendedAgent/tools", "ExtendedAgentTool"),
    "skills": ("/api/v2/extendedAgent/skills", "Skill"),
    "hooks": ("/api/v2/extendedAgent/hooks", "GlobalHook"),
    "commonPrompts": ("/api/v2/extendedAgent/commonprompts", "CommonPrompt"),
    "scheduledTasks": ("/api/v2/extendedAgent/scheduledtasks", "ScheduledTask"),
    "repositories": ("/api/v2/repos", "CodeRepo"),
    "httpTriggers": ("/api/v2/extendedAgent/httpTriggers", "HttpTrigger"),
    "pluginMarketplaces": ("/api/v2/extendedAgent/pluginMarketplaces", "Marketplace"),
    "pluginInstallations": ("/api/v2/extendedAgent/pluginInstallations", "PluginInstallation"),
    "globalSettings": ("/api/v2/extendedAgent/globalSettings", "GlobalSettings"),
    "incidentFilters": ("/api/v2/incidentManagement/incidentFilters", "IncidentFilter"),
    "githubAuths": ("/api/v2/github/domains", None),
    "azureDevOpsAuths": ("/api/v2/azuredevops/orgs", None),
}
DIRECT_SKIP_EXISTS_CHECK = {"repositories"}
DIRECT_NO_LIST_OR_DELETE = {"globalSettings"}


class InternalTenantOnlyError(CLIError):
    """The ARM extension route refused the agent's tenant."""


def _extension_arm_request(cli_ctx, extension_type, *args, **kwargs):
    """_arm_request for agent extensions, turning the service's tenant gate
    into a plain message instead of a raw HTTP error."""
    try:
        return _arm_request(cli_ctx, *args, **kwargs)
    except Exception as ex:
        response_text = getattr(getattr(ex, "response", None), "text", "") or ""
        if INTERNAL_TENANT_ONLY_MARKER in f"{ex} {response_text}".lower():
            raise InternalTenantOnlyError(
                f"This tenant can't use '{extension_type}' yet. The service only "
                "allows agent extensions in Microsoft internal tenants right now. "
                "Nothing is wrong with your command or your agent. If you need "
                "this in your tenant, please ask the SRE Agent team to open it up."
            ) from ex
        raise


def _direct_extension_path(extension_type, extension_name=None):
    base = DIRECT_EXTENSION_ROUTES[extension_type][0]
    return f"{base}/{quote(extension_name, safe='')}" if extension_name else base


def _direct_extension_request(cli_ctx, agent_name, resource_group, method, path, **kwargs):
    try:
        return _data_plane_request(cli_ctx, agent_name, resource_group, method, path, **kwargs)
    except Exception as ex:
        if getattr(getattr(ex, "response", None), "status_code", None) == 403:
            raise CLIError(
                "The agent's own API refused this request (403). Your account may lack "
                "permission on the agent; creating or changing items needs the "
                "'SRE Agent Author' or 'SRE Agent Administrator' role."
            ) from ex
        raise


def _direct_extension_to_arm_shape(extension_type, envelope):
    if not isinstance(envelope, dict):
        return envelope
    return {
        "name": envelope.get("name"),
        "type": f"microsoft.app/agents/{extension_type}",
        "properties": {"value": envelope.get("properties")},
    }


def _direct_extension_create(cli_ctx, agent_name, resource_group, extension_type, name, raw_value, overwrite):
    raw_value = _normalize_extension_value(raw_value, extension_type)
    properties = json.loads(raw_value)
    properties.pop("name", None)
    path = _direct_extension_path(extension_type, name)
    envelope_type = DIRECT_EXTENSION_ROUTES[extension_type][1]
    if envelope_type is None:
        result = _direct_extension_request(cli_ctx, agent_name, resource_group, "PUT", path, body=properties)
        return _direct_extension_to_arm_shape(extension_type, {"name": name, "properties": result})
    check_exists = not overwrite and extension_type not in DIRECT_SKIP_EXISTS_CHECK
    http_client_tool = _is_http_client_tool(extension_type, raw_value)
    existing = None
    if check_exists or http_client_tool:
        existing = _direct_extension_request(cli_ctx, agent_name, resource_group, "GET", path, missing_ok=True)
    if check_exists and existing is not None:
        raise ResourceExistsError(
            f"An extension named '{name}' of type '{extension_type}' already exists on "
            f"agent '{agent_name}'. Pass --overwrite to replace it intentionally, or "
            "choose another name."
        )
    if http_client_tool:
        _require_existing_http_client_tool(existing.get("properties") if isinstance(existing, dict) else None)
    envelope = {"name": name, "type": envelope_type, "properties": properties}
    result = _direct_extension_request(cli_ctx, agent_name, resource_group, "PUT", path, body=envelope)
    return _direct_extension_to_arm_shape(
        extension_type, result if isinstance(result, dict) and result.get("properties") else envelope)


def _direct_auth_items(cli_ctx, agent_name, resource_group, extension_type):
    result = _direct_extension_request(
        cli_ctx, agent_name, resource_group, "GET", _direct_extension_path(extension_type))
    items = result.get("values") if isinstance(result, dict) else None
    return items or []


def _direct_auth_to_arm_shape(extension_type, item):
    return _direct_extension_to_arm_shape(extension_type, {"name": item.get("name"), "properties": item})


def _direct_extension_show(cli_ctx, agent_name, resource_group, extension_type, name):
    if DIRECT_EXTENSION_ROUTES[extension_type][1] is None:
        match = next((i for i in _direct_auth_items(cli_ctx, agent_name, resource_group, extension_type)
                      if i.get("name") == name), None)
        if match is None:
            raise ResourceNotFoundError(
                f"Extension '{name}' of type '{extension_type}' not found on agent '{agent_name}'.")
        return _direct_auth_to_arm_shape(extension_type, match)
    result = _direct_extension_request(
        cli_ctx, agent_name, resource_group, "GET", _direct_extension_path(extension_type, name), missing_ok=True)
    if result is None:
        raise ResourceNotFoundError(
            f"Extension '{name}' of type '{extension_type}' not found on agent '{agent_name}'.")
    return _direct_extension_to_arm_shape(extension_type, result)


def _direct_extension_list(cli_ctx, agent_name, resource_group, extension_type):
    if DIRECT_EXTENSION_ROUTES[extension_type][1] is None:
        items = _direct_auth_items(cli_ctx, agent_name, resource_group, extension_type)
        return {"value": [_direct_auth_to_arm_shape(extension_type, i) for i in items]}
    result = _direct_extension_request(
        cli_ctx, agent_name, resource_group, "GET", _direct_extension_path(extension_type))
    items = result.get("value") if isinstance(result, dict) else result
    return {"value": [_direct_extension_to_arm_shape(extension_type, item) for item in items or []]}


def _direct_extension_delete(cli_ctx, agent_name, resource_group, extension_type, name):
    if extension_type == "azureDevOpsAuths":
        path = f"{_direct_extension_path(extension_type)}?org={quote(name, safe='')}"
    else:
        path = _direct_extension_path(extension_type, name)
    return _direct_extension_request(cli_ctx, agent_name, resource_group, "DELETE", path, missing_ok=True)


def _is_safe_extension_name(name):
    return (isinstance(name, str) and name not in (".", "..")
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name) is not None)


def _arm_extension_resource_id(agent_resource_id, extension_type, extension_name):
    """Quote the name so '/' or '..' can't retarget the request to another resource."""
    if not extension_name or extension_name in (".", ".."):
        raise CLIError(f"'{extension_name}' isn't a valid extension name.")
    return f"{agent_resource_id}/{extension_type}/{quote(extension_name, safe='')}"


def _arm_extension_create(
    cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False
):
    """Create or update an agent extension resource. Shared by every noun-
    specific 'create'/'update' facade (tool/skill/hook/instructions/
    automation/plugin/repo connect/agent settings)."""
    agent_resource_id = _resolve_agent_resource_id(cli_ctx, agent_name, resource_group)
    resource_id = _arm_extension_resource_id(agent_resource_id, extension_type, extension_name)
    existing = None
    if not overwrite:
        existing = _extension_arm_request(cli_ctx, extension_type, "GET", resource_id, EXTENSION_API_VERSION, missing_ok=True)
        if existing is not None:
            raise ResourceExistsError(
                f"An extension named '{extension_name}' of type "
                f"'{extension_type}' already exists on agent '{agent_name}'. "
                "Pass --overwrite to replace it intentionally, or choose "
                "another name."
            )
    raw_value = _normalize_extension_value(raw_value, extension_type)
    encoded_value = _encode_extension_value(raw_value)
    if _is_http_client_tool(extension_type, raw_value):
        if overwrite:
            existing = _arm_request(cli_ctx, "GET", resource_id, EXTENSION_API_VERSION, missing_ok=True)
        existing = _decode_extension_envelope(existing)
        properties = existing.get("properties") if isinstance(existing, dict) else None
        _require_existing_http_client_tool(properties.get("value") if isinstance(properties, dict) else None)
    body = {
        "type": f"microsoft.app/agents/{extension_type}",
        "properties": {"value": encoded_value},
    }
    result = _extension_arm_request(cli_ctx, extension_type, "PUT", resource_id, EXTENSION_API_VERSION, body=body)
    return _decode_extension_envelope(result)


def _arm_extension_show(cli_ctx, agent_name, resource_group, extension_type, extension_name):
    """Show an agent extension resource. Shared by every noun-specific
    'show' facade."""
    agent_resource_id = _resolve_agent_resource_id(cli_ctx, agent_name, resource_group)
    resource_id = _arm_extension_resource_id(agent_resource_id, extension_type, extension_name)
    result = _extension_arm_request(cli_ctx, extension_type, "GET", resource_id, EXTENSION_API_VERSION, missing_ok=True)
    if result is None:
        raise ResourceNotFoundError(
            f"Extension '{extension_name}' of type '{extension_type}' not found on agent '{agent_name}'."
        )
    return _decode_extension_envelope(result)


def _arm_extension_list(cli_ctx, agent_name, resource_group, extension_type):
    """List an agent's extension resources of a given type. Shared by every
    noun-specific 'list' facade."""
    agent_resource_id = _resolve_agent_resource_id(cli_ctx, agent_name, resource_group)
    resource_id = f"{agent_resource_id}/{extension_type}"
    result = _extension_arm_request(cli_ctx, extension_type, "GET", resource_id, EXTENSION_API_VERSION)
    if isinstance(result, dict) and isinstance(result.get("value"), list):
        result["value"] = [_decode_extension_envelope(item) for item in result["value"]]
    return result


def _warn_no_extensions(extension_type, agent_name):
    create_noun = EXTENSION_TYPE_CREATE_NOUN.get(extension_type)
    hint = f" Add one with '{create_noun}'." if create_noun else ""
    logger.warning("No '%s' extensions found on agent '%s'.%s", extension_type, agent_name, hint)


def _arm_extension_delete(cli_ctx, agent_name, resource_group, extension_type, extension_name):
    """Delete an agent extension resource. Shared by every noun-specific
    'delete' facade."""
    agent_resource_id = _resolve_agent_resource_id(cli_ctx, agent_name, resource_group)
    resource_id = _arm_extension_resource_id(agent_resource_id, extension_type, extension_name)
    return _extension_arm_request(cli_ctx, extension_type, "DELETE", resource_id, EXTENSION_API_VERSION, missing_ok=True)


FEATURE_STATUS_PATH = "/api/v1/feature/status"
FEATURE_CACHE_TTL_SECONDS = 24 * 60 * 60
FEATURE_CACHE_FILE = "sre_agent_features.json"
EXTENSION_FEATURE_FLAGS = {
    "scheduledTasks": ("scheduledTasks", "scheduled tasks"),
    "httpTriggers": ("httpTriggers", "HTTP triggers"),
}
_FEATURES_MEMORY = {}


def _feature_cache_path():
    from azure.cli.core._environment import get_config_dir

    return os.path.join(get_config_dir(), FEATURE_CACHE_FILE)


def _feature_cache_key(cli_ctx, agent_name, resource_group):
    subscription = (getattr(cli_ctx, "data", None) or {}).get("subscription_id") or ""
    if not subscription:
        try:
            from azure.cli.core._profile import Profile

            subscription = Profile(cli_ctx=cli_ctx).get_subscription_id()
        except Exception:  # pylint: disable=broad-except
            subscription = ""
    return f"{subscription}/{resource_group}/{agent_name}".lower()


def _feature_cache_read(key):
    import time

    try:
        with open(_feature_cache_path(), encoding="utf-8") as handle:
            entry = json.load(handle).get(key)
    except (OSError, ValueError):
        return None
    if not isinstance(entry, dict) or time.time() - entry.get("cachedAt", 0) > FEATURE_CACHE_TTL_SECONDS:
        return None
    return entry.get("features") if isinstance(entry.get("features"), dict) else None


def _feature_cache_write(key, features):
    import time

    try:
        try:
            with open(_feature_cache_path(), encoding="utf-8") as handle:
                cache = json.load(handle)
        except (OSError, ValueError):
            cache = {}
        cache[key] = {"cachedAt": time.time(), "features": features}
        with open(_feature_cache_path(), "w", encoding="utf-8") as handle:
            json.dump(cache, handle)
    except OSError:
        logger.debug("Could not write the agent feature cache.")


def _agent_features(cli_ctx, agent_name, resource_group):
    """The agent's own feature flags, which say whether it is a first-party agent.

    Cached per agent. An empty dict means unknown, so callers keep the ARM-first path.
    """
    override = os.environ.get("AZSRE_EXTENSION_ROUTE", "").strip().lower()
    if override == "direct":
        return {"isFirstParty": False}
    if override == "arm":
        return {}
    key = _feature_cache_key(cli_ctx, agent_name, resource_group)
    if key in _FEATURES_MEMORY:
        return _FEATURES_MEMORY[key]
    features = _feature_cache_read(key)
    if features is None:
        try:
            response = _data_plane_request(cli_ctx, agent_name, resource_group, "GET", FEATURE_STATUS_PATH)
            raw = response.get("features") if isinstance(response, dict) else None
            features = raw if isinstance(raw, dict) else {}
        except Exception as ex:  # pylint: disable=broad-except
            logger.debug("Could not read agent feature status: %s", ex)
            features = {}
        if features:
            _feature_cache_write(key, features)
    _FEATURES_MEMORY[key] = features
    return features


def _require_feature(features, extension_type):
    flag = EXTENSION_FEATURE_FLAGS.get(extension_type)
    if flag and features.get(flag[0]) is False:
        raise CLIError(f"This agent doesn't have {flag[1]} enabled, so it can't be configured here.")


FIRST_PARTY_ONLY_CONNECTOR_TYPES = frozenset({"GenevaMetrics", "S360", "Dgrep"})


def _require_first_party(cli_ctx, agent_name, resource_group, what, tenant_fallback=False):
    """Block Microsoft-internal features on agents that report they are not first-party.

    When the agent's status is unknown, tenant_fallback checks the signed-in tenant instead.
    """
    first_party = _agent_features(cli_ctx, agent_name, resource_group).get("isFirstParty")
    if first_party is None and tenant_fallback:
        first_party = _is_microsoft_first_party_tenant(_resolve_signed_in_tenant_id(cli_ctx))
    if first_party is False:
        raise CLIError(f"{what} is Microsoft-internal only and is not available on this agent.")


def _with_direct_fallback(arm_func, direct_func, cli_ctx, agent_name, resource_group, extension_type, *args, **kwargs):
    features = _agent_features(cli_ctx, agent_name, resource_group)
    if extension_type in DIRECT_EXTENSION_ROUTES and features.get("isFirstParty") is False and not (
            extension_type in DIRECT_NO_LIST_OR_DELETE
            and direct_func in (_direct_extension_list, _direct_extension_delete)):
        if direct_func is _direct_extension_create:
            _require_feature(features, extension_type)
        direct_kwargs = {k: v for k, v in kwargs.items() if k == "overwrite"} if direct_func is _direct_extension_create else {}
        return direct_func(cli_ctx, agent_name, resource_group, extension_type, *args, **direct_kwargs)
    try:
        return arm_func(cli_ctx, agent_name, resource_group, extension_type, *args, **kwargs)
    except InternalTenantOnlyError:
        if extension_type not in DIRECT_EXTENSION_ROUTES or (
                extension_type in DIRECT_NO_LIST_OR_DELETE
                and direct_func in (_direct_extension_list, _direct_extension_delete)):
            raise
        logger.info("ARM route refused this tenant; using the agent's own API for '%s'.", extension_type)
        direct_kwargs = {k: v for k, v in kwargs.items() if k == "overwrite"} if direct_func is _direct_extension_create else {}
        return direct_func(cli_ctx, agent_name, resource_group, extension_type, *args, **direct_kwargs)


def _extension_resource_create(cli_ctx, agent_name, resource_group, extension_type, extension_name, raw_value, overwrite=False):
    with _no_http_trace():
        return _with_direct_fallback(
            _arm_extension_create, _direct_extension_create, cli_ctx, agent_name, resource_group,
            extension_type, extension_name, raw_value, overwrite=overwrite)


def _extension_resource_show(cli_ctx, agent_name, resource_group, extension_type, extension_name):
    return _with_direct_fallback(
        _arm_extension_show, _direct_extension_show, cli_ctx, agent_name, resource_group,
        extension_type, extension_name)


def _extension_resource_list(cli_ctx, agent_name, resource_group, extension_type):
    return _with_direct_fallback(
        _arm_extension_list, _direct_extension_list, cli_ctx, agent_name, resource_group, extension_type)


def _extension_resource_delete(cli_ctx, agent_name, resource_group, extension_type, extension_name):
    return _with_direct_fallback(
        _arm_extension_delete, _direct_extension_delete, cli_ctx, agent_name, resource_group,
        extension_type, extension_name)


# --------------------------------------------------------------------------------------------
# Noun-specific extension facades -- "sre tool", "sre skill", "sre hook",
# "sre instructions", "sre plugin marketplace"/"sre plugin install".
#
# WHY: the raw ARM resource shape behind all of these is a direct, flat
# mirror (Microsoft.App/agents/<extensionType>/<name>). That matches the
# backend, but it does NOT match the Azure SRE Agent portal's own
# navigation, which splits these extension types into separate first-class
# pages under Build + setup > Extensions: Connectors, Tools, Skills, Skill
# builder, Plugins, Hooks, Custom instructions (each with its own "Add"/
# "Create" button, not a shared "pick a type" dropdown). Confirmed directly
# from the portal's left nav (SRE Agent product, Build + setup section).
#
# Each command below is a thin front door that pins the extension type to
# the matching value and calls the shared _extension_resource_create/show/
# list/delete() helpers above directly (no "sre extension ..." command
# exists anymore -- see the comment above those helpers for why). This
# only renames the noun so a user who has seen the portal's "Tools" page
# can type "az sre tool create" instead of having to know the internal
# extension type string "tools".
# --------------------------------------------------------------------------------------------
class _PinnedExtensionCreate(AAZCommand):
    """Base for a noun-specific 'create' facade. Subclasses set
    _EXTENSION_TYPE (and optionally _VALUE_HELP) and are decorated with
    their own @register_command(...)."""

    _EXTENSION_TYPE = None
    _VALUE_HELP = "Configuration as a JSON document (the CLI base64-encodes it for you)."
    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_name = AAZStrArg(
            options=["--name", "-n", "--extension-name"],
            help="Name of this instance.",
            required=True,
        )
        schema.value = AAZStrArg(options=["--value"], help=cls._VALUE_HELP, required=True)
        schema.overwrite = AAZBoolArg(
            options=["--overwrite"],
            help="Allow replacing an existing one of the same name. Without "
            "this flag, creation refuses to overwrite an existing instance.",
        )
        cls._args_schema = schema
        return schema

    def _prepare_value(self):
        """Hook for subclasses that offer a convenience way to build --value
        (e.g. SkillCreate's --file-path SKILL.md parsing) instead of requiring
        a hand-built JSON string. Called after self.ctx.args is populated but
        before --value is read, so overrides can freely read other args and
        assign self.ctx.args.value. No-op by default."""

    def _handler(self, command_args):
        super()._handler(command_args)
        self._prepare_value()
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_name = _arg_value(self.ctx.args.extension_name)
        raw_value = _arg_value(self.ctx.args.value)
        overwrite = bool(_arg_value(getattr(self.ctx.args, "overwrite", None)))

        return _extension_resource_create(
            self.cli_ctx, agent_name, resource_group, self._EXTENSION_TYPE,
            extension_name, raw_value, overwrite=overwrite,
        )


class _PinnedExtensionShow(AAZCommand):
    """Base for a noun-specific 'show' facade."""

    _EXTENSION_TYPE = None
    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_name = AAZStrArg(
            options=["--name", "-n", "--extension-name"],
            help="Name of this instance.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_name = _arg_value(self.ctx.args.extension_name)

        return _extension_resource_show(
            self.cli_ctx, agent_name, resource_group, self._EXTENSION_TYPE, extension_name,
        )


class _PinnedExtensionList(AAZCommand):
    """Base for a noun-specific 'list' facade."""

    _EXTENSION_TYPE = None
    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["-n", "--name", "--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)

        result = _extension_resource_list(
            self.cli_ctx, agent_name, resource_group, self._EXTENSION_TYPE,
        )
        # Return a bare array like the other list commands, so
        # --query "[].name" works.
        if isinstance(result, dict) and isinstance(result.get("value"), list):
            if not result["value"]:
                _warn_no_extensions(self._EXTENSION_TYPE, agent_name)
            return result["value"]
        return result


class _PinnedExtensionDelete(AAZCommand):
    """Base for a noun-specific 'delete' facade."""

    _EXTENSION_TYPE = None
    _NOUN = "Item"
    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.agent_name = AAZStrArg(
            options=["--agent-name"], help="Name of the SRE Agent.", required=True,
        )
        schema.resource_group = AAZResourceGroupNameArg(required=True)
        schema.extension_name = AAZStrArg(
            options=["--name", "-n", "--extension-name"],
            help="Name of this instance.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        extension_name = _arg_value(self.ctx.args.extension_name)

        # Deleting an item that doesn't exist still reports success, so look it up first.
        try:
            _extension_resource_show(
                self.cli_ctx, agent_name, resource_group, self._EXTENSION_TYPE, extension_name,
            )
        except ResourceNotFoundError as ex:
            raise ResourceNotFoundError(
                f"{self._NOUN} '{extension_name}' not found on agent '{agent_name}'."
            ) from ex
        # The user already confirmed via this command's own confirmation
        # prompt (see its @register_command(confirmation=...)). Like other
        # deletes, print nothing.
        _extension_resource_delete(
            self.cli_ctx, agent_name, resource_group, self._EXTENSION_TYPE, extension_name,
        )


def _parse_skill_md(file_path):
    """Parse a SKILL.md-style file into (description, skill_content)."""
    frontmatter, content = _read_skill_md(file_path)
    return frontmatter.get("description"), content


def _read_skill_md(file_path):
    """Parse a SKILL.md-style file into (frontmatter, skill_content).

    Matches the portal's "Skill builder" > "Create skill" dialog's own file
    template: an optional '---'-delimited YAML frontmatter block containing
    'name:'/'description:' lines, followed by the skill's markdown
    instructions body. The service's skill shape has no 'name' field; a
    skill's name is the resource name, so the frontmatter 'name:' can only
    stand in for --name. The body becomes 'skillContent' verbatim. A plain
    file with no frontmatter is treated as the body only.
    """
    if not os.path.isfile(file_path):
        raise CLIError(f"--file-path '{file_path}' does not exist.")
    with open(file_path, "r", encoding="utf-8-sig") as handle:
        text = handle.read()

    frontmatter = {}
    content = text
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end_idx = None
        for idx in range(1, len(lines)):
            if lines[idx].strip() == "---":
                end_idx = idx
                break
        if end_idx is not None:
            for line in lines[1:end_idx]:
                if ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip().lower()
                value = value.strip().strip("'\"")
                if key in ("name", "description") and value:
                    frontmatter[key] = value
            content = "\n".join(lines[end_idx + 1:]).strip("\n")
    return frontmatter, content


# ---- sre tool (portal: Extensions > Tools > Custom tools) ----
@register_command_group("sre tool")
class _ToolGroup(AAZCommandGroup):
    """Manage custom tools the agent can call.

    Built-in tools and MCP servers/services are configured separately and
    are not yet exposed by this CLI.
    """


@register_command("sre tool create")
class ToolCreate(_PinnedExtensionCreate):
    """Create a custom tool, or update one with --overwrite.

    :example: Create a link tool
        az sre tool create -g myrg --agent-name myagent --name docs-link \\
            --value '{"type": "LinkTool", "name": "docs", "description": "Link to docs", "template": "https://learn.microsoft.com/azure/"}'
    """

    _EXTENSION_TYPE = "tools"
    _args_schema = None
    _VALUE_HELP = (
        "Tool configuration as JSON. New tools: KustoTool, LinkTool or PythonFunctionTool. "
        "PythonTool is a legacy alias for PythonFunctionTool. "
        "HttpClientTool is update-only: pass --overwrite for an existing HttpClientTool of the same name. "
        "Use PythonFunctionTool or an MCP server for new HTTP integrations."
    )


@register_command("sre tool show")
class ToolShow(_PinnedExtensionShow):
    """Show a custom tool.

    :example: Show one custom tool
        az sre tool show -g myrg --agent-name myagent --name docs-link
    """

    _EXTENSION_TYPE = "tools"
    _args_schema = None


@register_command("sre tool list")
class ToolList(_PinnedExtensionList):
    """List custom tools.

    :example: List an agent's custom tools
        az sre tool list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "tools"
    _args_schema = None


@register_command(
    "sre tool delete",
    confirmation="Are you sure you want to perform this operation?",
)
class ToolDelete(_PinnedExtensionDelete):
    """Delete a custom tool.

    :example: Delete a custom tool
        az sre tool delete -g myrg --agent-name myagent --name docs-link
    """

    _EXTENSION_TYPE = "tools"
    _NOUN = "Tool"
    _args_schema = None


# ---- sre automation (portal: Automation tab -- renamed from "workflow" to
# match the portal's own top-level naming; the portal's separate "Workflows"
# heading is unrelated and currently only holds Agent Canvas) ----
@register_command_group("sre automation")
class _AutomationGroup(AAZCommandGroup):
    """Manage agent automations.

    Covers scheduled tasks and HTTP triggers. Response plans live under
    'az sre response-plan' instead.
    """


@register_command_group("sre automation scheduled-task")
class _AutomationScheduledTaskGroup(AAZCommandGroup):
    """Manage scheduled tasks that run the agent on a cron timer.

    Runs the agent against a prompt, optionally bounded to a time window or
    a maximum run count.
    """


@register_command("sre automation scheduled-task create")
class AutomationScheduledTaskCreate(_PinnedExtensionCreate):
    """Create or update a scheduled task.

    :example: Run the agent on a timer against a prompt
        az sre automation scheduled-task create -g myrg --agent-name myagent --name daily-digest \\
            --value '{"cronExpression": "0 9 * * 1-5", "agentPrompt": "Summarize overnight alerts"}'
    """

    _EXTENSION_TYPE = "scheduledTasks"
    _args_schema = None
    _VALUE_HELP = (
        "Task configuration as JSON. Fields: cronExpression, agentPrompt, description, agent, threadId, startTime, endTime, maxExecutions, "
        "agentMode (readonly, review or autonomous), and isEnabled or status (Active or Paused)."
    )


@register_command("sre automation scheduled-task show")
class AutomationScheduledTaskShow(_PinnedExtensionShow):
    """Show a scheduled task.

    :example: Show one scheduled task
        az sre automation scheduled-task show -g myrg --agent-name myagent --name daily-digest
    """

    _EXTENSION_TYPE = "scheduledTasks"
    _args_schema = None


@register_command("sre automation scheduled-task list")
class AutomationScheduledTaskList(_PinnedExtensionList):
    """List scheduled tasks.

    :example: List an agent's scheduled tasks
        az sre automation scheduled-task list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "scheduledTasks"
    _args_schema = None


class _ScheduledTaskSetStatus(_PinnedExtensionShow):
    _EXTENSION_TYPE = "scheduledTasks"
    _STATUS = None

    def _handler(self, command_args):
        current = super()._handler(command_args)
        properties = current.get("properties") if isinstance(current, dict) else None
        value = properties.get("value") if isinstance(properties, dict) else None
        if not isinstance(value, dict):
            raise CLIError("Could not read the scheduled task's current configuration.")
        value = {k: v for k, v in value.items() if v is not None}
        value["status"] = self._STATUS
        return _extension_resource_create(
            self.cli_ctx, _arg_value(self.ctx.args.agent_name), _arg_value(self.ctx.args.resource_group),
            self._EXTENSION_TYPE, _arg_value(self.ctx.args.extension_name), json.dumps(value), overwrite=True,
        )


@register_command("sre automation scheduled-task pause")
class AutomationScheduledTaskPause(_ScheduledTaskSetStatus):
    """Pause a scheduled task so it stops running until resumed.

    :example: Pause a scheduled task
        az sre automation scheduled-task pause -g myrg --agent-name myagent --name daily-digest
    """

    _STATUS = "Paused"
    _args_schema = None


@register_command("sre automation scheduled-task resume")
class AutomationScheduledTaskResume(_ScheduledTaskSetStatus):
    """Resume a paused scheduled task.

    :example: Resume a paused scheduled task
        az sre automation scheduled-task resume -g myrg --agent-name myagent --name daily-digest
    """

    _STATUS = "Active"
    _args_schema = None


@register_command(
    "sre automation scheduled-task delete",
    confirmation="Are you sure you want to perform this operation?",
)
class AutomationScheduledTaskDelete(_PinnedExtensionDelete):
    """Delete a scheduled task.

    :example: Delete a scheduled task
        az sre automation scheduled-task delete -g myrg --agent-name myagent --name daily-digest
    """

    _EXTENSION_TYPE = "scheduledTasks"
    _NOUN = "Scheduled task"
    _args_schema = None


@register_command_group("sre automation http-trigger")
class _AutomationHttpTriggerGroup(AAZCommandGroup):
    """Manage HTTP triggers that run the agent on a webhook call.

    Runs the agent against a prompt when an inbound webhook call arrives,
    instead of on a schedule.
    """


@register_command("sre automation http-trigger create")
class AutomationHttpTriggerCreate(_PinnedExtensionCreate):
    """Create or update an HTTP trigger.

    :example: Create a webhook that runs the agent against a prompt
        az sre automation http-trigger create -g myrg --agent-name myagent --name alert-webhook \\
            --value '{"agentPrompt": "Investigate the attached alert payload"}'
    """

    _EXTENSION_TYPE = "httpTriggers"
    _args_schema = None
    _VALUE_HELP = (
        "Trigger configuration as JSON. Fields: agentPrompt, description, agent, threadId, "
        "agentMode (readonly, review or autonomous)."
    )


@register_command("sre automation http-trigger show")
class AutomationHttpTriggerShow(_PinnedExtensionShow):
    """Show an HTTP trigger.

    :example: Show one HTTP trigger
        az sre automation http-trigger show -g myrg --agent-name myagent --name alert-webhook
    """

    _EXTENSION_TYPE = "httpTriggers"
    _args_schema = None


@register_command("sre automation http-trigger invoke")
class AutomationHttpTriggerInvoke(_PinnedExtensionShow):
    """Call an HTTP trigger now, the same way an external webhook would.

    Uses your Azure CLI sign-in for the call, so you need data-plane access to the agent.

    :example: Fire a trigger with no payload
        az sre automation http-trigger invoke -g myrg --agent-name myagent --name alert-webhook

    :example: Fire a trigger with a JSON payload from a file
        az sre automation http-trigger invoke -g myrg --agent-name myagent --name alert-webhook \\
            --payload @alert.json
    """

    _EXTENSION_TYPE = "httpTriggers"
    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.payload = AAZStrArg(
            options=["--payload"],
            help="JSON body to send with the call. The agent sees it alongside the trigger's prompt.",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        trigger = super()._handler(command_args)
        properties = trigger.get("properties") if isinstance(trigger, dict) else None
        value = properties.get("value") if isinstance(properties, dict) else None
        trigger_url = value.get("triggerUrl") if isinstance(value, dict) else None
        if not trigger_url:
            raise CLIError("This HTTP trigger has no triggerUrl yet, so it can't be called.")
        if not _is_azuresre_https_url(trigger_url):
            raise CLIError(f"Refusing to send a token to unexpected trigger URL '{trigger_url}'.")
        if value.get("triggerEnabled") is False:
            raise CLIError("This HTTP trigger is disabled.")
        payload = _arg_value(getattr(self.ctx.args, "payload", None))
        if payload:
            try:
                json.loads(payload)
            except ValueError as ex:
                raise CLIError(f"--payload must be a JSON document: {ex}") from ex
        response = send_raw_request(
            self.cli_ctx, "POST", trigger_url,
            headers=["Content-Type=application/json"],
            body=payload or None,
            resource=DATA_PLANE_AUDIENCE,
        )
        return response.json() if response.content else {}


@register_command("sre automation http-trigger list")
class AutomationHttpTriggerList(_PinnedExtensionList):
    """List HTTP triggers.

    :example: List an agent's HTTP triggers
        az sre automation http-trigger list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "httpTriggers"
    _args_schema = None


@register_command(
    "sre automation http-trigger delete",
    confirmation="Are you sure you want to perform this operation?",
)
class AutomationHttpTriggerDelete(_PinnedExtensionDelete):
    """Delete an HTTP trigger.

    :example: Delete an HTTP trigger
        az sre automation http-trigger delete -g myrg --agent-name myagent --name alert-webhook
    """

    _EXTENSION_TYPE = "httpTriggers"
    _NOUN = "HTTP trigger"
    _args_schema = None


# ---- incident filter helpers (portal: Incidents > Triggers & response plans --
# NOT Automation; confirmed by walking the live portal nav: Automation only
# ever shows Scheduled tasks/HTTP triggers, Incidents has its own separate
# "Triggers & response plans" tab) ----


def _incident_filter_path(extension_name=None):
    base = "/api/v2/incidentManagement/incidentFilters"
    return f"{base}/{quote(extension_name, safe='')}" if extension_name else base


def _incident_handler_path(extension_name=None):
    base = "/api/v2/extendedAgent/incidentHandlers"
    return f"{base}/{quote(extension_name, safe='')}" if extension_name else base


def _incident_handlers_list(cli_ctx, agent_name, resource_group, agent_url=None):
    handlers = _data_plane_request(
        cli_ctx, agent_name, resource_group, "GET", _incident_handler_path(), agent_url=agent_url)
    if not isinstance(handlers, list) or any(not isinstance(handler, dict) for handler in handlers):
        raise CLIError("The agent returned an unexpected incident-handler collection.")
    return handlers


GENERIC_ARM_EXTENSION_ERROR = "extension configuration is invalid"


def _incident_unwrap(kind, envelope):
    """Convert an ARM extension envelope to the shape the data plane returns."""
    envelope = _decode_extension_envelope(envelope)
    properties = envelope.get("properties") if isinstance(envelope, dict) else None
    value = properties.get("value") if isinstance(properties, dict) else None
    if not isinstance(value, dict):
        return envelope
    if kind == "filter":
        return {"name": envelope.get("name"), "type": "IncidentFilter", "properties": value}
    return value


def _incident_unwrap_list(kind, result):
    if not (isinstance(result, dict) and isinstance(result.get("value"), list)):
        return result
    items = [_incident_unwrap(kind, item) for item in result["value"]]
    return {"value": items} if kind == "filter" else items


QUICKSTART_PLAN_NAME = "quickstart_response_plan"


def _warn_if_quickstart_plan(filters, agent_name):
    """Warn when the portal's quickstart response plan is present: it runs
    alongside custom plans and can double-process or misroute incidents."""
    names = {f.get("name") for f in filters if isinstance(f, dict)}
    if QUICKSTART_PLAN_NAME in names:
        logger.warning(
            "Agent '%s' still has the quickstart response plan '%s'. It runs alongside "
            "your custom plans and can route incidents to the wrong agent or process "
            "them twice. Remove it with 'az sre response-plan delete --name %s'.",
            agent_name, QUICKSTART_PLAN_NAME, QUICKSTART_PLAN_NAME,
        )


def _http_error_text(ex):
    response = getattr(ex, "response", None)
    text = getattr(response, "text", "") if response is not None else ""
    return text or str(ex)


def _incident_resource_create(cli_ctx, agent_name, resource_group, extension_type, name,
                              arm_value, data_plane_path, data_plane_body, overwrite):
    """Save handlers through the agent API and filters through ARM."""
    kind = "filter" if extension_type == "incidentFilters" else "handler"
    # The deployed ARM incidentHandlers proxy returns 404, including for list.
    # The agent's v2 API supports the linked instructions directly.
    if extension_type == "incidentHandlers":
        if not overwrite and any(
                handler.get("id") == name
                for handler in _incident_handlers_list(cli_ctx, agent_name, resource_group)):
            raise ResourceExistsError(
                f"Incident handler '{name}' already exists on agent '{agent_name}'. "
                "Pass --overwrite to replace it intentionally.")
        return _data_plane_request(
            cli_ctx, agent_name, resource_group, "PUT", data_plane_path, body=data_plane_body)
    try:
        result = _extension_resource_create(
            cli_ctx, agent_name, resource_group, extension_type, name,
            json.dumps(arm_value), overwrite,
        )
    except ResourceExistsError as ex:
        raise ResourceExistsError(
            f"Incident {kind} '{name}' already exists on agent '{agent_name}'. "
            "Pass --overwrite to replace it intentionally."
        ) from ex
    except Exception as ex:  # pylint: disable=broad-except
        if GENERIC_ARM_EXTENSION_ERROR not in _http_error_text(ex):
            raise
        try:
            result = _data_plane_request(
                cli_ctx, agent_name, resource_group, "PUT", data_plane_path, body=data_plane_body,
            )
        except Exception as dp_ex:  # pylint: disable=broad-except
            if getattr(getattr(dp_ex, "response", None), "status_code", None) in (401, 403):
                raise ex
            raise CLIError(
                f"The agent rejected the incident {kind}: {_http_error_text(dp_ex)}"
            ) from ex
        logger.warning("ARM rejected the request with a generic error; the data plane accepted it.")
        return result
    return _incident_unwrap(kind, result)


def _set_incident_filter_enabled(command, enabled):
    return _response_plan_apply_filter_changes(
        command.cli_ctx, _arg_value(command.ctx.args.agent_name),
        _arg_value(command.ctx.args.resource_group),
        _arg_value(command.ctx.args.extension_name), {"isEnabled": enabled})


def _incident_filter_toggle_schema(cls, schema):
    schema.agent_name = AAZStrArg(
        options=["--agent-name"], help="Name of the SRE Agent.", required=True,
    )
    schema.resource_group = AAZResourceGroupNameArg(required=True)
    schema.extension_name = AAZStrArg(
        options=["--name", "-n", "--extension-name"],
        help="Name of this incident filter.",
        required=True,
    )
    cls._args_schema = schema
    return schema


# ---- incident handler helpers ----


# ---- sre response-plan (portal: Incidents > Triggers & response plans) ----
# A response plan is an incident filter (the match rules and the handling
# subagent) plus an optional incident handler (instructions) that points at
# the filter through incidentFilterId. The portal grid lists the filter.
@register_command_group("sre response-plan")
class _ResponsePlanGroup(AAZCommandGroup):
    """Route incidents to a subagent (portal: Triggers & response plans).

    Match criteria use ARM; linked instructions use the agent API.
    """


RESPONSE_PLAN_PLATFORMS = ("AzMonitor", "PagerDuty", "ServiceNow", "Icm")
RESPONSE_PLAN_MODES = ("autonomous", "review")


def _response_plan_target_schema(schema, with_name=True):
    schema.agent_name = AAZStrArg(
        options=["--agent-name"], help="Name of the SRE Agent.", required=True,
    )
    schema.resource_group = AAZResourceGroupNameArg(required=True)
    if with_name:
        schema.extension_name = AAZStrArg(
            options=["--name", "-n", "--extension-name"],
            help="Name of the response plan.",
            required=True,
        )


def _response_plan_handlers_for(cli_ctx, agent_name, resource_group, plan_name, agent_url=None):
    try:
        handlers = _incident_handlers_list(cli_ctx, agent_name, resource_group, agent_url=agent_url)
    except DataPlaneRouteUnavailableError:
        logger.warning(
            "This agent doesn't expose response-plan instructions, so they were skipped for '%s'.",
            plan_name)
        return []
    return [handler for handler in handlers if handler.get("incidentFilterId") == plan_name]


def _add_response_plan_criteria_args(schema):
    """Match criteria and handler options shared by response-plan create/update."""
    schema.priorities = AAZListArg(
        options=["--priority"],
        help="Space-separated priority or severity levels to match (for example Sev0 Sev1 or P1 P2"
        + ("; IcM severities are plain numbers such as 3 4" if _show_internal_features() else "")
        + "). Default: all.",
    )
    schema.priorities.Element = AAZStrArg()
    schema.title_contains = AAZStrArg(
        options=["--title-contains"], help="Only match incidents whose title contains this text.",
    )
    schema.title_not_contains = AAZListArg(
        options=["--title-not-contains"],
        help="Space-separated texts; skip incidents whose title contains any of them.",
    )
    schema.title_not_contains.Element = AAZStrArg()
    schema.incident_types = AAZListArg(
        options=["--incident-type"],
        help="Space-separated incident types to match (for example LiveSite)"
        + (". Required with --platform Icm" if _show_internal_features() else "") + ". Portal: Incident type.",
    )
    schema.incident_types.Element = AAZStrArg()
    schema.impacted_service = AAZStrArg(
        options=["--impacted-service"], help="Only match incidents for this service. Portal: Owning service.",
    )
    schema.owning_teams = AAZListArg(
        options=["--owning-team"],
        help="Space-separated owning team IDs"
        + (" (IcM team IDs are numeric)" if _show_internal_features() else "") + ". Portal: Owning team.",
    )
    schema.owning_teams.Element = AAZStrArg()
    schema.merge_enabled = AAZBoolArg(
        options=["--merge-enabled"],
        help="Merge related incidents into one investigation thread. Service default: true.",
    )
    schema.merge_window_hours = AAZIntArg(
        options=["--merge-window-hours"],
        help="Hours within which related incidents are merged. Service default: 3.",
    )
    schema.max_investigation_attempts = AAZIntArg(
        options=["--max-investigation-attempts", "--max-attempts"],
        help="How many times the agent automatically investigates a matched incident. Service default: 3.",
    )
    schema.alert_id = AAZStrArg(
        options=["--alert-id"], arg_group="Azure Monitor",
        help="Only match incidents raised by this alert rule (its resource ID).",
    )
    schema.target_resource_type = AAZStrArg(
        options=["--target-resource-type"], arg_group="Azure Monitor",
        help="Only match alerts on this resource type, for example Microsoft.App/containerApps.",
    )
    schema.target_resource = AAZStrArg(
        options=["--target-resource"], arg_group="Azure Monitor",
        help="Only match alerts on this resource.",
    )
    schema.instructions = AAZStrArg(
        options=["--instructions"], help="Custom instructions the subagent follows for matched incidents.",
    )
    schema.processing_guide = AAZListArg(
        options=["--processing-guide"],
        help="Quoted step-by-step guidance for the subagent, one value per step.",
    )
    schema.processing_guide.Element = AAZStrArg()


def _response_plan_criteria(args):
    """Filter properties for every criteria flag the user actually passed."""
    flt = {}
    for key, arg in (
            ("priorities", args.priorities), ("titleNotContains", args.title_not_contains),
            ("incidentTypes", args.incident_types), ("owningTeamIds", args.owning_teams)):
        values = _arg_value(arg)
        if values:
            flt[key] = list(values)
    if flt.get("incidentTypes"):
        # The portal reads the legacy single field and treats the plan as invalid without it.
        flt["incidentType"] = flt["incidentTypes"][0]
    for key, arg in (("titleContains", args.title_contains), ("impactedService", args.impacted_service),
                     ("alertId", getattr(args, "alert_id", None))):
        value = _arg_value(arg)
        if value:
            flt[key] = value
    az_monitor = {}
    for key, arg in (("targetResourceType", getattr(args, "target_resource_type", None)),
                     ("targetResource", getattr(args, "target_resource", None))):
        value = _arg_value(arg)
        if value:
            az_monitor[key] = value
    if az_monitor:
        flt["azMonitorFilterSettings"] = az_monitor
    merge_enabled = _arg_value(args.merge_enabled)
    if merge_enabled is not None:
        flt["mergeEnabled"] = bool(merge_enabled)
    window = _arg_value(args.merge_window_hours)
    if window is not None:
        if window < 1:
            raise CLIError("--merge-window-hours must be at least 1.")
        flt["mergeWindowHours"] = window
    attempts = _arg_value(getattr(args, "max_investigation_attempts", None))
    if attempts is not None:
        if attempts < 1:
            raise CLIError("--max-investigation-attempts must be at least 1.")
        flt["maxAutomatedInvestigationAttempts"] = attempts
    return flt


def _response_plan_handler_fields(args):
    handler = {}
    instructions = _arg_value(args.instructions)
    guide = _arg_value(args.processing_guide)
    if instructions:
        handler["customInstructions"] = instructions
    if guide:
        handler["incidentProcessingGuide"] = list(guide)
    return handler


def _raise_if_subagent_missing(cli_ctx, agent_name, resource_group, subagent, error):
    """The service rejects a plan whose subagent doesn't exist with a generic error; explain it."""
    try:
        _extension_resource_show(cli_ctx, agent_name, resource_group, "subagents", subagent)
    except ResourceNotFoundError:
        raise CLIError(
            f"Subagent '{subagent}' doesn't exist, so the response plan can't hand incidents to it. "
            "Create it first with 'az sre subagent create'."
        ) from error
    except Exception as ex:  # pylint: disable=broad-except
        logger.debug("Could not check subagent '%s': %s", subagent, ex)


@register_command("sre response-plan create")
class ResponsePlanCreate(AAZCommand):
    """Create or update an incident response plan.

    Routes matching incidents to a subagent. Connect the incident platform and
    create the subagent first.

    :example: Route high-severity Azure Monitor incidents to a subagent in review mode
        az sre response-plan create -g myrg --agent-name myagent -n sev1-api \\
            --platform AzMonitor --subagent incident-responder --priority Sev0 Sev1 \\
            --title-contains api --mode review

    :example: Skip noisy incidents and give the subagent step-by-step guidance
        az sre response-plan create -g myrg --agent-name myagent -n api-errors \\
            --platform AzMonitor --subagent incident-responder --priority Sev1 Sev2 \\
            --title-not-contains test synthetic \\
            --processing-guide "Check recent deployments" "Query error rates in App Insights"

    :example: Change an existing plan
        az sre response-plan update -g myrg --agent-name myagent -n api-errors --mode autonomous
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _response_plan_target_schema(schema)
        schema.platform = AAZStrArg(
            options=["--platform"], required=True,
            help=(
                "Incident platform: " + ", ".join(RESPONSE_PLAN_PLATFORMS) + ". Icm is Microsoft-internal only."
                if _show_internal_features()
                else "Incident platform: " + ", ".join(p for p in RESPONSE_PLAN_PLATFORMS if p != "Icm") + "."
            ),
        )
        schema.subagent = AAZStrArg(
            options=["--subagent"], required=True,
            help="Name of the existing subagent that handles matched incidents. Use meta_agent for the main agent.",
        )
        _add_response_plan_criteria_args(schema)
        schema.mode = AAZStrArg(
            options=["--mode"], default="autonomous",
            help="Agent autonomy: autonomous (portal default) or review (agent proposes, you approve).",
        )
        schema.disabled = AAZBoolArg(
            options=["--disabled"], help="Create the plan turned off.",
        )
        schema.overwrite = AAZBoolArg(
            options=["--overwrite"], help="Allow replacing an existing response plan.",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        args = self.ctx.args
        agent_name = _arg_value(args.agent_name)
        resource_group = _arg_value(args.resource_group)
        name = _arg_value(args.extension_name)
        platform = _arg_value(args.platform)
        mode = _arg_value(args.mode)
        overwrite = bool(_arg_value(args.overwrite))
        if platform not in RESPONSE_PLAN_PLATFORMS:
            visible = [p for p in RESPONSE_PLAN_PLATFORMS if p != "Icm" or _show_internal_features()]
            raise CLIError(f"--platform must be one of: {', '.join(visible)}.")
        if mode not in RESPONSE_PLAN_MODES:
            raise CLIError(f"--mode must be one of: {', '.join(RESPONSE_PLAN_MODES)}.")
        if platform == "Icm":
            if not _arg_value(args.incident_types):
                raise CLIError(
                    "--incident-type is required with --platform Icm (for example --incident-type LiveSite).")
            _require_first_party(self.cli_ctx, agent_name, resource_group, "--platform Icm")
        flt = {
            "incidentPlatform": platform,
            "handlingAgent": _arg_value(args.subagent),
            "agentMode": mode,
            "isEnabled": not bool(_arg_value(args.disabled)),
        }
        flt.update(_response_plan_criteria(args))
        _validate_incident_filters_shape(flt)
        filter_body = {"name": name, "type": "IncidentFilter", "properties": flt}
        try:
            result = {"filter": _incident_resource_create(
                self.cli_ctx, agent_name, resource_group, "incidentFilters", name,
                flt, _incident_filter_path(name), filter_body, overwrite)}
        except ResourceExistsError:
            raise
        except Exception as ex:  # pylint: disable=broad-except
            _raise_if_platform_not_connected(self.cli_ctx, agent_name, resource_group, platform, ex)
            _raise_if_subagent_missing(self.cli_ctx, agent_name, resource_group, flt["handlingAgent"], ex)
            raise
        handler_fields = _response_plan_handler_fields(args)
        if handler_fields:
            handler = {"id": name, "incidentFilterId": name, **handler_fields}
            _validate_incident_handlers_shape(handler)
            try:
                result["handler"] = _incident_resource_create(
                    self.cli_ctx, agent_name, resource_group, "incidentHandlers", name,
                    handler, _incident_handler_path(name), handler, overwrite)
            except Exception as ex:  # pylint: disable=broad-except
                raise CLIError(
                    f"Response plan '{name}' was created, but its instructions were not saved: {ex}"
                ) from ex
        try:
            existing = _incident_unwrap_list("filter", _extension_resource_list(
                self.cli_ctx, agent_name, resource_group, "incidentFilters"))
            _warn_if_quickstart_plan(
                [f for f in existing.get("value", []) if f.get("name") != name], agent_name)
        except Exception:  # pylint: disable=broad-except
            pass  # the warning is advisory; never fail a successful create
        return result


def _raise_if_platform_not_connected(cli_ctx, agent_name, resource_group, platform, error):
    """The service rejects a plan for an unconnected platform with a generic error; explain it."""
    try:
        agent = _cli_invoke(cli_ctx, "sre", "agent", "show", "--name", agent_name,
                            "--resource-group", resource_group)
        config = ((agent or {}).get("properties") or {}).get("incidentManagementConfiguration") or {}
    except Exception:  # pylint: disable=broad-except
        return
    connected = config.get("type")
    if connected and str(connected).lower() == platform.lower():
        return
    status = f"is connected to '{connected}'" if connected else "has no incident platform connected"
    if platform == "AzMonitor":
        hint = (f"  az sre agent update -g {resource_group} -n {agent_name} "
                "--incident-management-configuration '{type:AzMonitor,connection-name:azmonitor}'")
    else:
        hint = "  See 'az sre agent update -h' for --incident-management-configuration examples."
    raise CLIError(
        f"Agent '{agent_name}' {status}, so it can't route {platform} incidents. "
        f"Connect {platform} first:\n{hint}"
    ) from error


def _response_plan_read_filter(cli_ctx, agent_name, resource_group, name):
    return _incident_unwrap("filter", _extension_resource_show(
        cli_ctx, agent_name, resource_group, "incidentFilters", name))


def _response_plan_apply_filter_changes(cli_ctx, agent_name, resource_group, name, changes, existing=None):
    """Apply changes to the plan's filter, read through ARM unless given, and write it back through ARM."""
    if existing is None:
        existing = _response_plan_read_filter(cli_ctx, agent_name, resource_group, name)
    # ARM echoes unset fields as null, which the service rejects on write.
    properties = {k: v for k, v in (existing.get("properties") or {}).items() if v is not None}
    if isinstance(changes.get("azMonitorFilterSettings"), dict):
        current = properties.get("azMonitorFilterSettings")
        merged = {k: v for k, v in current.items() if v is not None} if isinstance(current, dict) else {}
        merged.update(changes["azMonitorFilterSettings"])
        changes = {**changes, "azMonitorFilterSettings": merged}
    properties.update(changes)
    _validate_incident_filters_shape(properties)
    return _incident_resource_create(
        cli_ctx, agent_name, resource_group, "incidentFilters", name, properties,
        _incident_filter_path(name),
        {"name": name, "type": "IncidentFilter", "properties": properties}, True)


@register_command("sre response-plan update")
class ResponsePlanUpdate(AAZCommand):
    """Update a response plan. Only the flags you pass change.

    Passing a list flag (for example --priority) replaces that whole list.
    Use 'enable' or 'disable' to turn a plan on or off.

    :example: Change the autonomy mode and the merge window
        az sre response-plan update -g myrg --agent-name myagent -n sev1-api \\
            --mode autonomous --merge-window-hours 6

    :example: Point a plan at a different subagent and replace its severities
        az sre response-plan update -g myrg --agent-name myagent -n sev1-api \\
            --subagent other-responder --priority Sev0 Sev1
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _response_plan_target_schema(schema)
        schema.platform = AAZStrArg(
            options=["--platform"],
            help="Incident platform: "
            + ", ".join(p for p in RESPONSE_PLAN_PLATFORMS if p != "Icm" or _show_internal_features()) + ".",
        )
        schema.subagent = AAZStrArg(
            options=["--subagent"],
            help="Name of the existing subagent that handles matched incidents. Use meta_agent for the main agent.",
        )
        schema.mode = AAZStrArg(
            options=["--mode"], help="Agent autonomy: autonomous or review.",
        )
        _add_response_plan_criteria_args(schema)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        args = self.ctx.args
        agent_name = _arg_value(args.agent_name)
        resource_group = _arg_value(args.resource_group)
        name = _arg_value(args.extension_name)
        changes = _response_plan_criteria(args)
        for key, arg, allowed in (
                ("incidentPlatform", args.platform, RESPONSE_PLAN_PLATFORMS),
                ("agentMode", args.mode, RESPONSE_PLAN_MODES)):
            value = _arg_value(arg)
            if value is not None:
                if value not in allowed:
                    flag = "--platform" if key == "incidentPlatform" else "--mode"
                    raise CLIError(f"{flag} must be one of: {', '.join(allowed)}.")
                changes[key] = value
                if key == "incidentPlatform" and value == "Icm":
                    _require_first_party(self.cli_ctx, agent_name, resource_group, "--platform Icm")
        subagent = _arg_value(args.subagent)
        if subagent:
            changes["handlingAgent"] = subagent
        handler_fields = _response_plan_handler_fields(args)
        if not changes and not handler_fields:
            raise CLIError("Nothing to update. Pass at least one option to change.")
        # The filter (ARM) and the instructions (agent API) are separate, non-atomic
        # writes, so finish every read and check before the first one.
        existing = _response_plan_read_filter(self.cli_ctx, agent_name, resource_group, name)
        handler = None
        if handler_fields:
            handlers = _response_plan_handlers_for(self.cli_ctx, agent_name, resource_group, name)
            handler = dict(handlers[0]) if handlers else {"id": name, "incidentFilterId": name}
            handler.update(handler_fields)
            _validate_incident_handlers_shape(handler)
        result = {"filter": existing}
        if changes:
            result["filter"] = _response_plan_apply_filter_changes(
                self.cli_ctx, agent_name, resource_group, name, changes, existing)
        if handler is not None:
            handler_id = handler.get("id") or name
            try:
                result["handler"] = _incident_resource_create(
                    self.cli_ctx, agent_name, resource_group, "incidentHandlers", handler_id, handler,
                    _incident_handler_path(handler_id), handler, True)
            except Exception as ex:  # pylint: disable=broad-except
                if not changes:
                    raise
                retry_flags = " and ".join(
                    flag for flag, key in (
                        ("--instructions", "customInstructions"),
                        ("--processing-guide", "incidentProcessingGuide"))
                    if key in handler_fields)
                raise CLIError(
                    f"Response plan '{name}' was only partly updated: its filter changes "
                    f"({', '.join(sorted(changes))}) were saved, but saving its instructions failed. "
                    f"Re-run the update with only {retry_flags} to retry them. Error: {ex}"
                ) from ex
        return result


@register_command("sre response-plan show")
class ResponsePlanShow(AAZCommand):
    """Show a response plan and its instructions.

    :example: Show one plan
        az sre response-plan show -g myrg --agent-name myagent -n sev1-api
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _add_read_target_args(schema, short_name=False)
        schema.extension_name = AAZStrArg(
            options=["--name", "-n", "--extension-name"],
            help="Name of the response plan.",
            required=True,
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name, resource_group, agent_url = _read_target(self.ctx.args)
        name = _arg_value(self.ctx.args.extension_name)
        if agent_url:
            flt = _data_plane_request(
                self.cli_ctx, agent_name, resource_group, "GET",
                _incident_filter_path(name), missing_ok=True, agent_url=agent_url)
            if flt is None:
                raise ResourceNotFoundError(f"Response plan '{name}' not found on agent '{agent_url}'.")
        else:
            flt = _incident_unwrap("filter", _extension_resource_show(
                self.cli_ctx, agent_name, resource_group, "incidentFilters", name))
        handlers = _response_plan_handlers_for(
            self.cli_ctx, agent_name, resource_group, name, agent_url=agent_url)
        return {"filter": flt, "handlers": handlers}


@register_command("sre response-plan list")
class ResponsePlanList(AAZCommand):
    """List response plans.

    :example: List an agent's response plans
        az sre response-plan list -g myrg --agent-name myagent
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _add_read_target_args(schema)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name, resource_group, agent_url = _read_target(self.ctx.args)
        if agent_url:
            result = _data_plane_request(
                self.cli_ctx, agent_name, resource_group, "GET", _incident_filter_path(),
                agent_url=agent_url)
        else:
            result = _incident_unwrap_list("filter", _extension_resource_list(
                self.cli_ctx, agent_name, resource_group, "incidentFilters"))
        filters = result.get("value", []) if isinstance(result, dict) else []
        _warn_if_quickstart_plan(filters, agent_name or agent_url)
        if not filters:
            logger.warning(
                "No response plans found on agent '%s'. Add one with "
                "'az sre response-plan create'.", agent_name or agent_url)
        return filters


@register_command(
    "sre response-plan delete",
    confirmation="Delete this response plan and its instructions?",
)
class ResponsePlanDelete(AAZCommand):
    """Delete a response plan and its linked instructions.

    :example: Delete a plan
        az sre response-plan delete -g myrg --agent-name myagent -n sev1-api
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        _response_plan_target_schema(schema)
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        name = _arg_value(self.ctx.args.extension_name)
        handlers = _response_plan_handlers_for(self.cli_ctx, agent_name, resource_group, name)
        # Deleting a plan that doesn't exist still reports success, so look it up first.
        try:
            _extension_resource_show(self.cli_ctx, agent_name, resource_group, "incidentFilters", name)
            has_filter = True
        except ResourceNotFoundError:
            has_filter = False
        if not has_filter and not handlers:
            raise ResourceNotFoundError(f"Response plan '{name}' not found on agent '{agent_name}'.")
        for handler in handlers:
            handler_id = handler.get("id") or name
            _data_plane_request(
                self.cli_ctx, agent_name, resource_group, "DELETE",
                _incident_handler_path(handler_id), missing_ok=True)
        if not has_filter:
            return
        try:
            _extension_resource_delete(
                self.cli_ctx, agent_name, resource_group, "incidentFilters", name)
        except Exception as ex:  # pylint: disable=broad-except
            if getattr(getattr(ex, "response", None), "status_code", None) != 403:
                raise
            # SRE Agent Administrator has the agent's data-plane delete but not the ARM delete action.
            logger.info("ARM refused the delete; using the agent's own API for '%s'.", name)
            _direct_extension_delete(
                self.cli_ctx, agent_name, resource_group, "incidentFilters", name)


@register_command("sre response-plan enable")
class ResponsePlanEnable(AAZCommand):
    """Turn on a response plan.

    :example: Enable a plan
        az sre response-plan enable -g myrg --agent-name myagent -n sev1-api
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        return _incident_filter_toggle_schema(cls, super()._build_arguments_schema(*args, **kwargs))

    def _handler(self, command_args):
        super()._handler(command_args)
        return _set_incident_filter_enabled(self, True)


@register_command("sre response-plan disable")
class ResponsePlanDisable(AAZCommand):
    """Turn off a response plan without deleting it.

    :example: Disable a plan
        az sre response-plan disable -g myrg --agent-name myagent -n sev1-api
    """

    _args_schema = None

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        return _incident_filter_toggle_schema(cls, super()._build_arguments_schema(*args, **kwargs))

    def _handler(self, command_args):
        super()._handler(command_args)
        return _set_incident_filter_enabled(self, False)


# ---- sre skill (portal: Extensions > Skills / Skill builder) ----
@register_command_group("sre skill")
class _SkillGroup(AAZCommandGroup):
    """Manage custom skills, which are specialized capabilities the agent can use.

    Built-in skills are toggled on/off separately, not created here; use
    'sre skill create --file-path SKILL.md' to author a custom one, then
    'sre skill list'/'sre skill show' to see it.
    """


@register_command("sre skill create")
class SkillCreate(_PinnedExtensionCreate):
    """Create or update a custom skill.

    :example: Create a skill from a SKILL.md file
        az sre skill create --agent-name myagent --resource-group myrg --name my-skill \\
            --file-path SKILL.md --tools kusto-query log-search

    :example: Name the skill from the SKILL.md frontmatter 'name:' line
        az sre skill create --agent-name myagent --resource-group myrg --file-path SKILL.md

    :example: Create a skill from a raw JSON value
        az sre skill create --agent-name myagent --resource-group myrg --name my-skill \\
            --value '{"description": "...", "tools": [], "skillContent": "# My skill\\n..."}'
    """

    _EXTENSION_TYPE = "skills"
    _args_schema = None
    _VALUE_HELP = (
        "Skill configuration as a JSON document. Alternative to --file-path "
        "(specify exactly one of the two)."
    )

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        # --value is normally required by the base class; relax that here
        # since --file-path is the other, mutually-exclusive way to supply
        # it (enforced in _prepare_value below).
        schema.value._required = False
        # --name can come from the SKILL.md frontmatter instead.
        schema.extension_name._required = False
        schema.file_path = AAZStrArg(
            options=["--file-path"],
            arg_group="Skill builder",
            help="Path to a SKILL.md-style file: an optional frontmatter "
            "block between '---' lines with 'name:' and 'description:' lines, followed "
            "by the skill's Markdown instructions. The frontmatter name is used when "
            "--name is omitted. Alternative to --value.",
        )
        schema.tools = AAZListArg(
            options=["--tools"],
            arg_group="Skill builder",
            help="Space-separated tool names this skill can use when "
            "active. Only used with --file-path; defaults to none.",
        )
        schema.tools.Element = AAZStrArg()
        schema.description = AAZStrArg(
            options=["--description"],
            arg_group="Skill builder",
            help="Skill description. Only used with --file-path; overrides "
            "the SKILL.md frontmatter's 'description:' line if both are given.",
        )
        cls._args_schema = schema
        return schema

    def _prepare_value(self):
        args = self.ctx.args
        file_path = _arg_value(getattr(args, "file_path", None))
        explicit_value = _arg_value(getattr(args, "value", None))
        if file_path and explicit_value:
            raise CLIError("Specify either --file-path or --value, not both.")
        if not file_path and not explicit_value:
            raise CLIError("Specify either --file-path or --value.")
        name = _arg_value(getattr(args, "extension_name", None))
        if not file_path:
            if not name:
                raise CLIError("--name is required with --value.")
            return

        frontmatter, content = _read_skill_md(file_path)
        md_name = frontmatter.get("name")
        if md_name is not None and not _is_safe_extension_name(md_name):
            raise CLIError(
                f"SKILL.md frontmatter name '{md_name}' isn't a valid skill name. Use letters, "
                "digits, '.', '_' or '-', or pass --name."
            )
        if not name:
            if not md_name:
                raise CLIError("Pass --name, or add a 'name:' line to the SKILL.md frontmatter.")
            args.extension_name = md_name
        elif md_name and md_name != name:
            logger.warning(
                "Creating skill '%s'; the SKILL.md frontmatter name '%s' is ignored because --name was given.",
                name, md_name)
        description = _arg_value(getattr(args, "description", None)) or frontmatter.get("description")
        if not description:
            raise CLIError(
                "No description found. Add a 'description:' line to the "
                "SKILL.md frontmatter, or pass --description."
            )
        tools = _arg_value(getattr(args, "tools", None)) or []
        args.value = json.dumps(
            {"description": description, "tools": list(tools), "skillContent": content}
        )


@register_command("sre skill show")
class SkillShow(_PinnedExtensionShow):
    """Show a custom skill.

    :example: Show one custom skill
        az sre skill show -g myrg --agent-name myagent --name triage-skill
    """

    _EXTENSION_TYPE = "skills"
    _args_schema = None


@register_command("sre skill list")
class SkillList(_PinnedExtensionList):
    """List custom skills.

    :example: List an agent's custom skills
        az sre skill list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "skills"
    _args_schema = None


@register_command(
    "sre skill delete",
    confirmation="Are you sure you want to perform this operation?",
)
class SkillDelete(_PinnedExtensionDelete):
    """Delete a custom skill.

    :example: Delete a custom skill
        az sre skill delete -g myrg --agent-name myagent --name triage-skill
    """

    _EXTENSION_TYPE = "skills"
    _NOUN = "Skill"
    _args_schema = None


# ---- sre subagent (portal: Workflows > Agent Canvas > "Create subagent") ----
@register_command_group("sre subagent")
class _SubagentGroup(AAZCommandGroup):
    """Manage named sub-agents the meta-agent can hand off work to.

    A sub-agent is a scoped specialist with its own instructions, tools,
    and skills. In the portal, it's the Agent Canvas "Create subagent" dialog.
    """


@register_command("sre subagent create")
class SubagentCreate(_PinnedExtensionCreate):
    """Create or update a named sub-agent.

    :example: Create a read-only evidence-gathering sub-agent
        az sre subagent create --agent-name myagent --resource-group myrg --name app-investigator \\
            --value '{"instructions": "You are the application evidence specialist. Read supplied reference files with ReadFile and return source-backed observations.", "handoffDescription": "Use for read-only application request/error/dependency evidence.", "tools": ["ReadFile"], "mcpTools": [], "commonTools": [], "allowedSkills": ["zava-application-evidence"], "allowParallelToolCalls": true}'

    :example: Create the same sub-agent with a PreToolUse hook script from a file
        az sre subagent create --agent-name myagent --resource-group myrg --name app-investigator \\
            --value "@value.json" --pre-tool-use-script-file readonly-evidence.py
    """

    _EXTENSION_TYPE = "subagents"
    _args_schema = None
    _VALUE_HELP = (
        "Sub-agent configuration as JSON. instructions (at least 50 characters) and "
        "handoffDescription are required. Other fields: "
        "tools, mcpTools, commonTools, allowedSkills, allowParallelToolCalls."
    )

    @classmethod
    def _build_arguments_schema(cls, *args, **kwargs):
        if cls._args_schema is not None:
            return cls._args_schema
        schema = super()._build_arguments_schema(*args, **kwargs)
        schema.pre_tool_use_script_file = AAZStrArg(
            options=["--pre-tool-use-script-file", "--pre-tool-use-script"],
            arg_group="Hooks",
            help="Path to a script file to run before every tool call this "
            "sub-agent makes, like the portal's Manage Hooks > Pre Tool Use "
            "button. It's added to --value.hooks.PreToolUse for all tools, "
            "with a 30-second timeout and failMode \"block\". For other "
            "matchers or timeouts, set --value.hooks instead.",
        )
        cls._args_schema = schema
        return schema

    def _prepare_value(self):
        args = self.ctx.args
        script_file = _arg_value(getattr(args, "pre_tool_use_script_file", None))
        if not script_file:
            return
        if not os.path.isfile(script_file):
            raise CLIError(f"--pre-tool-use-script-file '{script_file}' does not exist.")
        raw_value = _arg_value(getattr(args, "value", None))
        try:
            parsed = json.loads(raw_value) if raw_value else {}
        except (TypeError, ValueError) as ex:
            raise CLIError(f"--value must be a JSON document: {ex}") from ex
        if not isinstance(parsed, dict):
            raise CLIError("--value must be a JSON object that describes the sub-agent.")
        with open(script_file, "r", encoding="utf-8-sig") as handle:
            script = handle.read()
        hooks = parsed.setdefault("hooks", {})
        hooks["PreToolUse"] = [
            {
                "type": "command",
                "matcher": "(?s:.*)",
                "timeout": 30,
                "failMode": "block",
                "script": script,
            }
        ]
        args.value = json.dumps(parsed)

    def _handler(self, command_args):
        try:
            return super()._handler(command_args)
        except Exception as ex:  # pylint: disable=broad-except
            if "configuration is invalid" not in str(ex):
                raise
            try:
                parsed = json.loads(_arg_value(self.ctx.args.value))
            except (TypeError, ValueError):
                raise ex from None
            if isinstance(parsed, dict) and not str(parsed.get("handoffDescription") or "").strip():
                raise CLIError(
                    f"{ex}\nThe service needs --value.handoffDescription: one sentence telling the "
                    "main agent when to hand work to this sub-agent."
                ) from ex
            raise


@register_command("sre subagent show")
class SubagentShow(_PinnedExtensionShow):
    """Show a sub-agent.

    :example: Show one sub-agent
        az sre subagent show -g myrg --agent-name myagent --name app-investigator
    """

    _EXTENSION_TYPE = "subagents"
    _args_schema = None


@register_command("sre subagent list")
class SubagentList(_PinnedExtensionList):
    """List sub-agents.

    :example: List an agent's sub-agents
        az sre subagent list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "subagents"
    _args_schema = None


@register_command(
    "sre subagent delete",
    confirmation="Are you sure you want to perform this operation?",
)
class SubagentDelete(_PinnedExtensionDelete):
    """Delete a sub-agent.

    :example: Delete a sub-agent
        az sre subagent delete -g myrg --agent-name myagent --name app-investigator
    """

    _EXTENSION_TYPE = "subagents"
    _NOUN = "Sub-agent"
    _args_schema = None


# ---- sre hook (portal: Extensions > Hooks) ----
@register_command_group("sre hook")
class _HookGroup(AAZCommandGroup):
    """Manage lifecycle hooks that run a prompt or script at a specific agent event.

    Fires on one of four events (Start, PreToolUse, PostToolUse, Stop) and
    runs either an LLM prompt or a bash/Python command. See 'sre hook
    create -h' for the full --value shape and the portal-vs-API note.
    """


@register_command("sre hook create")
class HookCreate(_PinnedExtensionCreate):
    """Create or update a hook.

    :example: Run a prompt after every Bash tool call
        cat > hook.json <<'JSON'
        {"eventType": "PostToolUse", "activationMode": "always", "description": "Flag risky commands",
         "hook": {"type": "prompt", "prompt": "Warn if the last tool call looks destructive.",
                  "matcher": "Bash.*", "failMode": "Allow"}}
        JSON
        az sre hook create --agent-name myagent --resource-group myrg --name post-tool-check \\
            --value @hook.json

    :example: Run a command instead of a prompt
        cat > command-hook.json <<'JSON'
        {"eventType": "PostToolUse", "activationMode": "always",
         "hook": {"type": "command", "script": "#!/usr/bin/env python3\\nimport json\\nprint(json.dumps({'decision': 'allow'}))",
                  "matcher": "Bash.*", "timeout": 30}}
        JSON
        az sre hook create --agent-name myagent --resource-group myrg --name post-tool-command \\
            --value @command-hook.json
    """

    _EXTENSION_TYPE = "hooks"
    _args_schema = None
    _VALUE_HELP = (
        "Hook configuration as JSON: eventType, activationMode, description and a nested \"hook\" object. hook.matcher is required for PreToolUse and PostToolUse."
    )


@register_command("sre hook show")
class HookShow(_PinnedExtensionShow):
    """Show a hook.

    :example: Show one hook
        az sre hook show -g myrg --agent-name myagent --name post-tool-check
    """

    _EXTENSION_TYPE = "hooks"
    _args_schema = None


@register_command("sre hook list")
class HookList(_PinnedExtensionList):
    """List hooks.

    :example: List an agent's hooks
        az sre hook list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "hooks"
    _args_schema = None


@register_command(
    "sre hook delete",
    confirmation="Are you sure you want to perform this operation?",
)
class HookDelete(_PinnedExtensionDelete):
    """Delete a hook.

    :example: Delete a hook
        az sre hook delete -g myrg --agent-name myagent --name post-tool-check
    """

    _EXTENSION_TYPE = "hooks"
    _NOUN = "Hook"
    _args_schema = None


# ---- sre instructions (NOT the portal's "Custom instructions" box --
# see the warning in _InstructionsGroup below) ----
@register_command_group("sre instructions")
class _InstructionsGroup(AAZCommandGroup):
    """Manage named, reusable prompt snippets ('commonPrompts').

    Important: these snippets aren't the portal's "Custom instructions" text
    box. That box is the 'customInstructions' field in the agent's global
    settings. Set it with 'az sre agent settings update'.
    """


@register_command("sre instructions create")
class InstructionsCreate(_PinnedExtensionCreate):
    """Create or update a reusable prompt snippet.

    Important: this doesn't set the portal's "Custom instructions" text box.
    To set that, use 'az sre agent settings update'.

    Use the same --name (e.g. "default") each time to update a given
    snippet in place, or pass --overwrite to replace an existing one.

    :example: Set the portal's global custom instructions with agent settings
        az sre agent settings update -g myrg --agent-name myagent \\
            --value '{"customInstructions": "Always cite the runbook section you used."}'

    :example: Create a named, reusable prompt snippet
        az sre instructions create -g myrg --agent-name myagent --name default \\
            --value '{"prompt": "Always cite the runbook section you used."}'

    :example: In Windows PowerShell, pass a JSON file
        '{"prompt": "Be concise."}' | Set-Content -Path "$env:TEMP\\instructions.json"
        az sre instructions create -g myrg --agent-name myagent --name default --value "@$env:TEMP\\instructions.json" --overwrite true

    :example: In Windows PowerShell, pass inline JSON through cmd /c
        cmd /c 'az sre instructions create --agent-name myagent --resource-group myrg --name default --value "{\\"prompt\\": \\"Be concise.\\"}" --overwrite true'
    """

    _EXTENSION_TYPE = "commonPrompts"
    _args_schema = None
    _VALUE_HELP = (
        "Prompt snippet as JSON: {\"prompt\": \"...\"}. For custom instructions, use 'az sre agent settings update'."
    )


@register_command("sre instructions show")
class InstructionsShow(_PinnedExtensionShow):
    """Show a named, reusable prompt snippet ('commonPrompts').

    Important: this isn't the portal's "Custom instructions" box (see
    'az sre instructions create -h'). To see that box's text, run
    'az sre agent settings show' and read its 'customInstructions' field.

    :example: Show an agent's current custom instructions
        az sre instructions show -g myrg --agent-name myagent --name default
    """

    _EXTENSION_TYPE = "commonPrompts"
    _args_schema = None


@register_command("sre instructions list")
class InstructionsList(_PinnedExtensionList):
    """List an agent's reusable prompt snippets.

    Important: these aren't the portal's "Custom instructions" box (see
    'az sre instructions create -h').

    :example: List an agent's custom instructions entries
        az sre instructions list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "commonPrompts"
    _args_schema = None


@register_command(
    "sre instructions delete",
    confirmation="Are you sure you want to perform this operation?",
)
class InstructionsDelete(_PinnedExtensionDelete):
    """Delete a named, reusable prompt snippet ('commonPrompts').

    Important: this doesn't clear the portal's "Custom instructions" box (see
    'az sre instructions create -h'). To clear that box, run
    'az sre agent settings update --value \\'{"customInstructions": ""}\\''.

    :example: Delete an agent's custom instructions
        az sre instructions delete -g myrg --agent-name myagent --name default
    """

    _EXTENSION_TYPE = "commonPrompts"
    _NOUN = "Instructions"
    _args_schema = None


# ---- sre plugin (portal: Extensions > Plugins) ----
# Nested two-deep for genuine parent->child sub-resources -- NOT the
# 'agent connector' anti-pattern, which would nest every noun under the
# one universal parent every resource already scopes to via --agent-name.
# Marketplace and install are a true two-step flow (install requires an
# existing marketplace).
@register_command_group("sre plugin")
class _PluginGroup(AAZCommandGroup):
    """Manage community plugins that add skills, tools, and integrations.

    Two separate steps: connecting a marketplace (a GitHub/Azure
    DevOps/GitLab repo of plugins, via 'sre plugin marketplace') and
    installing a specific plugin from one (via 'sre plugin install').
    """


@register_command_group("sre plugin marketplace")
class _PluginMarketplaceGroup(AAZCommandGroup):
    """Connect a repo of plugins as a marketplace the agent can install from.

    Supports GitHub, Azure DevOps, and GitLab repos. Use 'sre plugin install'
    afterward to actually install a plugin from the connected marketplace.
    """


@register_command("sre plugin marketplace create")
class PluginMarketplaceCreate(_PinnedExtensionCreate):
    """Connect a plugin marketplace.

    :example: Connect a GitHub repo as a plugin marketplace
        az sre plugin marketplace create -g myrg --agent-name myagent --name contoso-plugins \\
            --value '{"sourceType": "github", "sourceUrl": "owner/repo"}'
    """

    _EXTENSION_TYPE = "pluginMarketplaces"
    _args_schema = None
    _VALUE_HELP = (
        "Marketplace configuration as JSON. Fields: sourceType (\"github\"), sourceUrl (\"owner/repo\", not a full URL), owner, description."
    )


@register_command("sre plugin marketplace show")
class PluginMarketplaceShow(_PinnedExtensionShow):
    """Show a connected plugin marketplace.

    :example: Show one connected plugin marketplace
        az sre plugin marketplace show -g myrg --agent-name myagent --name contoso-plugins
    """

    _EXTENSION_TYPE = "pluginMarketplaces"
    _args_schema = None


@register_command("sre plugin marketplace list")
class PluginMarketplaceList(_PinnedExtensionList):
    """List connected plugin marketplaces.

    :example: List an agent's connected plugin marketplaces
        az sre plugin marketplace list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "pluginMarketplaces"
    _args_schema = None


@register_command(
    "sre plugin marketplace delete",
    confirmation="Are you sure you want to perform this operation?",
)
class PluginMarketplaceDelete(_PinnedExtensionDelete):
    """Disconnect a plugin marketplace.

    :example: Disconnect a plugin marketplace
        az sre plugin marketplace delete -g myrg --agent-name myagent --name contoso-plugins
    """

    _EXTENSION_TYPE = "pluginMarketplaces"
    _NOUN = "Plugin marketplace"
    _args_schema = None


@register_command_group("sre plugin install")
class _PluginInstallGroup(AAZCommandGroup):
    """Install a specific plugin from an already-connected marketplace.

    Run 'sre plugin marketplace create' first if you haven't connected a
    marketplace yet.
    """


@register_command("sre plugin install create")
class PluginInstallCreate(_PinnedExtensionCreate):
    """Install a plugin from a connected marketplace.

    'marketplaceName' and 'pluginName' aren't enough on their own. Also
    supply the full 'source' block ({"type", "repo", "url"}) with the
    plugin's exact path in the marketplace repo. This command writes the
    installation record directly and doesn't run the portal's install
    pipeline, so unlike a portal install, the result has no 'importedSkills',
    no 'sourceCommit', and no resolved 'mcpConnectorStatus'.

    :example: Install a plugin from a connected marketplace
        az sre plugin install create -g myrg --agent-name myagent --name datadog \\
            --value '{"marketplaceName": "contoso-plugins", "pluginName": "datadog", \\
            "source": {"type": "relative", "repo": "contoso/sre-plugins", "url": "plugins/datadog"}}'
    """

    _EXTENSION_TYPE = "pluginInstallations"
    _args_schema = None
    _VALUE_HELP = (
        "Plugin install configuration as JSON. Requires marketplaceName, pluginName and a \"source\" block."
    )


@register_command("sre plugin install show")
class PluginInstallShow(_PinnedExtensionShow):
    """Show an installed plugin.

    :example: Show one installed plugin
        az sre plugin install show -g myrg --agent-name myagent --name datadog
    """

    _EXTENSION_TYPE = "pluginInstallations"
    _args_schema = None


@register_command("sre plugin install list")
class PluginInstallList(_PinnedExtensionList):
    """List installed plugins.

    :example: List an agent's installed plugins
        az sre plugin install list -g myrg --agent-name myagent
    """

    _EXTENSION_TYPE = "pluginInstallations"
    _args_schema = None


@register_command(
    "sre plugin install delete",
    confirmation="Are you sure you want to perform this operation?",
)
class PluginInstallDelete(_PinnedExtensionDelete):
    """Uninstall a plugin.

    :example: Uninstall a plugin
        az sre plugin install delete -g myrg --agent-name myagent --name datadog
    """

    _EXTENSION_TYPE = "pluginInstallations"
    _NOUN = "Plugin"
    _args_schema = None


# --------------------------------------------------------------------------------------------
# "sre repo connect" -- a one-command golden path for the GitHub/Azure
# DevOps repo-connection flow. Collapses what would otherwise be a manual
# PAT-copy-paste + hand-built JSON payload into one flag because it already
# resolves a credential itself (an explicit token or a native GitHub OAuth
# Device Flow -- no 'gh' CLI needed) and a canonical payload shape it can
# build for the user.
#
# Before this command, connecting one repo required two raw extension
# creates the user had to build by hand:
#   1. githubAuths/azureDevOpsAuths, with a manually-pasted PAT
#   2. repositories, with a hand-written JSON --value
# This command does both, using a token it fetches itself -- an explicit
# --github-token/GITHUB_TOKEN env var or a native OAuth Device Flow for
# GitHub, or a freshly minted
# Azure DevOps PAT via the vssps.dev.azure.com REST API for Azure DevOps
# (ADO PAT creation has no `az devops` command; see running notes section on
# ADO PAT generation). Nothing here bypasses the real extension model --
# it is sugar that calls _extension_resource_create() twice with payloads
# it builds instead of asking the user to build them.
# --------------------------------------------------------------------------------------------

ADO_PAT_RESOURCE_ID = "499b84ac-1321-427f-aa17-267ca6975798"


# Azure CLI's own registered GitHub OAuth App client ID used by `az containerapp github-action add --login-with-github`,
# reused here per Paul's "steal what's tried and true" guidance -- device
# flow apps don't need a client secret, so this ID is already public in
# azure-cli's own source (command_modules/containerapp/_github_oauth.py).
# On GitHub's real consent screen this displays as "Azure CLI" by
# "AzureAppServiceCLI" (confirmed live, 2026-11-04) -- an accurate label,
# since `az sre repo connect` is itself an Azure CLI extension command.
# Matches ACA's device-flow mechanism and error handling exactly; the only
# thing intentionally not replicated is ACA's encrypted disk token cache,
# since `repo connect` is a one-time setup per repo (not a
# repeatedly-invoked command like `github-action add`), so there is
# nothing worth caching or needing to encrypt in the first place.
GITHUB_DEVICE_FLOW_CLIENT_ID = "8d8e1f6000648c575489"
# Narrower than azure-cli's containerapp scopes ("admin:repo_hook repo
# workflow"): "repo" already covers repository webhooks, so
# admin:repo_hook is dropped. "workflow" is kept because the agent can
# commit to .github/workflows files.
GITHUB_DEVICE_FLOW_SCOPES = "repo workflow"


def _github_device_flow(hostname="github.com", scope=GITHUB_DEVICE_FLOW_SCOPES):
    """Native GitHub OAuth Device Flow (RFC 8628) -- no 'gh' CLI, no client
    secret. Prints a user code, opens the verification page in a browser,
    then polls until the user approves it there."""
    import time
    from azure.cli.core.util import open_page_in_browser

    code_data = _github_oauth_post(
        hostname, "/login/device/code",
        {"client_id": GITHUB_DEVICE_FLOW_CLIENT_ID, "scope": scope},
    )
    if "error" in code_data:
        raise CLIError(
            f"Could not start GitHub sign-in: {_github_error_text(code_data)}. "
            f"{_GITHUB_TOKEN_HINT}"
        )
    device_code = code_data["device_code"]
    user_code = code_data["user_code"]
    verification_uri = code_data.get("verification_uri", f"https://{hostname}/login/device")
    interval = code_data.get("interval", 5)
    expires_in = code_data.get("expires_in", 900)

    # The address and the code get lines of their own so a zoomed (narrow)
    # console can't wrap them and a screen reader's line review reads each
    # one whole. They're printed before the browser opens and takes focus.
    _print_sign_in_text(
        "To sign in to GitHub, open this page:",
        verification_uri,
        "and enter this one-time code:",
        user_code,
        f"The code expires in {_minutes_text(expires_in)}. Press Ctrl+C to cancel.",
    )
    try:
        opened = _browser_opened(open_page_in_browser(verification_uri))
    except Exception:  # pylint: disable=broad-except
        opened = False
    if not opened:
        _print_sign_in_text("Could not open a browser. Open the page yourself.")
    _print_sign_in_text("Waiting for you to approve access on GitHub.")

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        token_data = _github_oauth_post(
            hostname, "/login/oauth/access_token",
            {
                "client_id": GITHUB_DEVICE_FLOW_CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
        )
        if "access_token" in token_data:
            return token_data["access_token"]
        error = token_data.get("error")
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval = token_data.get("interval", interval + 5)
            continue
        if error == "expired_token":
            break
        if error == "access_denied":
            raise CLIError(
                "GitHub sign-in was denied. Run the command again and approve "
                f"access. {_GITHUB_TOKEN_HINT}"
            )
        raise CLIError(
            f"GitHub sign-in failed: {_github_error_text(token_data)}. Run the "
            f"command again. {_GITHUB_TOKEN_HINT}"
        )
    raise CLIError(
        "The GitHub sign-in code expired before access was approved. Run the "
        f"command again to get a new code. {_GITHUB_TOKEN_HINT}"
    )


# Offered in every sign-in error: unlike the device code, a token has no
# time limit and needs no browser.
_GITHUB_TOKEN_HINT = (
    "To skip browser sign-in, set the GITHUB_TOKEN environment variable to a "
    "GitHub token."
)


def _github_oauth_post(hostname, path, data):
    """POST to a GitHub OAuth endpoint and return the decoded JSON body.

    Azure CLI prints a full traceback for requests errors other than
    HTTPError and SSLError, so turn network failures and non-JSON replies
    (for example, a proxy sign-in page) into readable errors.
    """
    try:
        response = requests.post(
            f"https://{hostname}{path}",
            headers={"Accept": "application/json"},
            data=data,
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.SSLError:
        raise  # Azure CLI already explains certificate and proxy problems.
    except requests.exceptions.HTTPError as ex:
        status = getattr(ex.response, "status_code", None) or "an error"
        raise CLIError(
            f"GitHub sign-in failed: {hostname} returned HTTP {status}. Run the "
            f"command again. {_GITHUB_TOKEN_HINT}"
        ) from ex
    except requests.exceptions.RequestException as ex:
        raise CLIError(
            f"Could not reach {hostname} to sign in to GitHub. Check your "
            "network and proxy settings, then run the command again. "
            f"{_GITHUB_TOKEN_HINT}"
        ) from ex
    try:
        return response.json()
    except ValueError as ex:
        raise CLIError(
            f"GitHub sign-in failed: the reply from {hostname} wasn't JSON. A "
            "proxy might be intercepting the request. Check your network and "
            f"proxy settings. {_GITHUB_TOKEN_HINT}"
        ) from ex


def _github_error_text(data):
    return str(data.get("error_description") or data.get("error") or "unknown error").rstrip(".")


def _minutes_text(seconds):
    minutes = max(1, round(seconds / 60))
    return f"{minutes} minute" if minutes == 1 else f"{minutes} minutes"


def _browser_opened(result):
    """Whether Azure CLI's open_page_in_browser opened the page.

    It returns webbrowser.open's bool on Windows and Linux, powershell.exe's
    exit code on WSL, and the 'open' process on macOS, which exits as soon as
    the request is handed off. Anything else counts as opened.
    """
    import subprocess

    if isinstance(result, bool):
        return result
    if isinstance(result, int):
        return result == 0
    if isinstance(result, subprocess.Popen):
        try:
            return result.wait(timeout=5) == 0
        except subprocess.TimeoutExpired:
            return True
    return True


def _print_sign_in_text(*lines):
    """Write sign-in instructions to stderr.

    Not logger.warning(): --only-show-errors (or core.only_show_errors) would
    hide the one-time code and leave the command waiting, and with color off
    each line would get a misleading "WARNING:" label. stdout stays clean
    for -o json and --query.
    """
    for line in lines:
        print(line, file=sys.stderr, flush=True)


def _github_token(explicit_token=None, hostname="github.com"):
    """Resolve a GitHub token with no 'gh' CLI dependency at all, in two
    layers (per Paul/Preeti's feedback: a 'gh' CLI reuse tier would just add
    a second, environment-dependent code path -- dropped in favor of one
    deterministic fallback):

    1. Explicit/CI first: --github-token, or GITHUB_TOKEN/GH_TOKEN env vars.
    2. Native GitHub OAuth Device Flow fallback: works with nothing but a
       web browser, no 'gh' CLI and no client secret needed.
    """
    if explicit_token:
        return explicit_token
    for env_var in ("GITHUB_TOKEN", "GH_TOKEN"):
        env_token = os.environ.get(env_var)
        if env_token:
            logger.warning(
                "Using the GitHub token from the %s environment variable; it will be stored on the "
                "agent. Pass a fine-grained, repo-scoped token with --github-token to control this.",
                env_var,
            )
            return env_token

    return _github_device_flow(hostname=hostname)


def _devops_access_token(cli_ctx):
    # Reuses the public `az account get-access-token` command (via
    # _cli_invoke, same pattern as every other cross-command call in this
    # file) instead of touching azure.cli.core internals directly -- the
    # resource is the bare Azure DevOps application ID GUID, NOT an
    # "https://<guid>" URI (that form fails tenant-wide with AADSTS500011).
    token_response = _cli_invoke(
        cli_ctx, "account", "get-access-token", "--resource", ADO_PAT_RESOURCE_ID,
    )
    token = (token_response or {}).get("accessToken")
    if not token:
        raise CLIError("Could not acquire an Azure DevOps access token.")
    return token


def _devops_pat_token(cli_ctx, organization, display_name):
    """Mint a short-lived Azure DevOps PAT via the vssps REST API and return
    (pat, authorization_id); the authorization ID is what revokes it.

    `az devops` has no PAT-creation command, so this calls the same
    vssps.dev.azure.com/_apis/tokens/pats endpoint the Portal's "New token"
    button uses, authenticated with an AAD token scoped to Azure DevOps's own
    resource ID (499b84ac-1321-427f-aa17-267ca6975798).
    """
    import datetime

    token = _devops_access_token(cli_ctx)
    valid_to = (datetime.datetime.now(datetime.timezone.utc)
                + datetime.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
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
    pat_token = response.json().get("patToken") or {}
    pat = pat_token.get("token")
    if not pat:
        raise CLIError("Azure DevOps did not return a PAT token.")
    return pat, pat_token.get("authorizationId")


def _revoke_devops_pat(cli_ctx, organization, authorization_id):
    """Best-effort revoke of a PAT minted by _devops_pat_token."""
    if not authorization_id:
        logger.warning("Could not revoke the Azure DevOps PAT created for this agent; revoke it "
                       "manually in Azure DevOps (User settings > Personal access tokens).")
        return
    try:
        token = _devops_access_token(cli_ctx)
        url = (f"https://vssps.dev.azure.com/{organization}/_apis/tokens/pats"
               f"?authorizationId={quote(authorization_id, safe='')}&api-version=7.1-preview.1")
        send_raw_request(cli_ctx, "DELETE", url, headers=[f"Authorization=Bearer {token}"])
    except Exception as ex:  # pylint: disable=broad-except
        logger.warning("Could not revoke the Azure DevOps PAT created for this agent (%s); revoke "
                       "it manually in Azure DevOps (User settings > Personal access tokens).", ex)


def _detect_repo_provider(repo_url):
    host = (urlparse(repo_url).hostname or "").lower()
    if host == "github.com":
        return "GitHub"
    if any(host == d or host.endswith("." + d) for d in ("dev.azure.com", "visualstudio.com")):
        return "AzureDevOps"
    raise CLIError(
        f"Could not detect the repo provider from '{repo_url}'. Pass "
        "--provider GitHub or --provider AzureDevOps explicitly."
    )


# Characters ARM rejects in resource names; the repository name becomes one.
_INVALID_REPO_NAME_CHARS = ("/", "\\", "?", "#", "%", "&", ":", "<", ">", "*")


def _repo_name_from_url(repo_url):
    name = urlparse(repo_url).path.rstrip("/").rsplit("/", 1)[-1]
    if name.lower().endswith(".git"):
        name = name[:-4]
    return name


def _devops_organization_from_url(repo_url):
    parsed = urlparse(repo_url)
    host = (parsed.hostname or "").lower()
    if host.endswith(".visualstudio.com"):
        return host.split(".", 1)[0]
    return parsed.path.strip("/").split("/", 1)[0]


@register_command("sre repo connect")
class RepoConnect(AAZCommand):
    """Connect a GitHub or Azure DevOps repo to an agent.

    For GitHub, the command uses --github-token, or the GITHUB_TOKEN or
    GH_TOKEN environment variable. If none is set, it shows a one-time code
    and opens GitHub's sign-in page in your browser. Enter the code there
    before it expires (15 minutes).

    :example: Connect a GitHub repo
        az sre repo connect --agent-name myagent --resource-group myrg \\
            --repo-url https://github.com/contoso/my-service

    :example: Connect a GitHub repo in CI, with the token in GITHUB_TOKEN
        az sre repo connect --agent-name myagent --resource-group myrg \\
            --repo-url https://github.com/contoso/my-service

    :example: Connect an Azure DevOps repo
        az sre repo connect --agent-name myagent --resource-group myrg \\
            --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo

    :example: Connect an Azure DevOps repo with a managed identity
        az sre repo connect --agent-name myagent --resource-group myrg \\
            --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo \\
            --devops-auth-type managed-identity --devops-identity <agent-identity-resource-id>
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
            help="HTTPS clone URL of the repo.",
            required=True,
        )
        schema.provider = AAZStrArg(
            options=["--provider"],
            help="Repo provider. Auto-detected from --repo-url's host when omitted.",
            enum={"GitHub": "GitHub", "AzureDevOps": "AzureDevOps"},
        )
        schema.display_name = AAZStrArg(
            options=["--display-name", "--name", "-n"],
            help="Display name for the repo. Defaults to the repo name from --repo-url (without .git).",
        )
        schema.branch = AAZStrArg(
            options=["--branch"],
            help="Branch to check out. Defaults to the repo's default branch.",
        )
        schema.github_token = AAZStrArg(
            options=["--github-token"],
            help="GitHub token. Defaults to GITHUB_TOKEN or GH_TOKEN, then to browser sign-in "
                 "with a one-time code. A fine-grained, repo-scoped token is recommended; "
                 "it is stored on the agent.",
        )
        schema.devops_organization = AAZStrArg(
            options=["--devops-organization"],
            help="Azure DevOps organization. Default: taken from --repo-url.",
        )
        schema.devops_auth_type = AAZStrArg(
            options=["--devops-auth-type"],
            help="Azure DevOps auth method. Use managed-identity if your org blocks PAT creation.",
            enum={"pat": "pat", "managed-identity": "managed-identity"},
            default="pat",
        )
        schema.devops_identity = AAZStrArg(
            options=["--devops-identity"],
            help="Managed identity resource ID. Required with --devops-auth-type managed-identity.",
        )
        schema.devops_federated_client_id = AAZStrArg(
            options=["--devops-federated-client-id", "--devops-fed-client-id"],
            help="Federated client ID, for an identity in a different tenant. Use with --devops-federated-tenant-id.",
        )
        schema.devops_federated_tenant_id = AAZStrArg(
            options=["--devops-federated-tenant-id", "--devops-fed-tenant-id"],
            help="Federated tenant ID. Use with --devops-federated-client-id.",
        )
        cls._args_schema = schema
        return schema

    def _handler(self, command_args):
        super()._handler(command_args)
        agent_name = _arg_value(self.ctx.args.agent_name)
        resource_group = _arg_value(self.ctx.args.resource_group)
        repo_url = _arg_value(self.ctx.args.repo_url)
        provider = _arg_value(self.ctx.args.provider) or _detect_repo_provider(repo_url)
        display_name = _arg_value(self.ctx.args.display_name) or _repo_name_from_url(repo_url)
        branch = _arg_value(self.ctx.args.branch)
        github_token = _arg_value(self.ctx.args.github_token)
        devops_organization = _arg_value(self.ctx.args.devops_organization)
        devops_auth_type = _arg_value(self.ctx.args.devops_auth_type) or "pat"
        devops_identity = _arg_value(self.ctx.args.devops_identity)
        devops_federated_client_id = _arg_value(self.ctx.args.devops_federated_client_id)
        devops_federated_tenant_id = _arg_value(self.ctx.args.devops_federated_tenant_id)
        pat_authorization_id = None

        # Validate the repository before touching auth: the auth write below
        # replaces any existing credentials for the host/org.
        if not display_name or any(ch in display_name for ch in _INVALID_REPO_NAME_CHARS):
            raise InvalidArgumentValueError(
                f"'{display_name}' is not a valid repository name. Pass --display-name with a name "
                "that is not empty and has none of these characters: " + " ".join(_INVALID_REPO_NAME_CHARS)
            )
        repo_type = provider
        repo_body = {"url": repo_url, "type": repo_type, "description": display_name}
        if branch:
            repo_body["branch"] = branch
        repo_value = _normalize_extension_value(json.dumps(repo_body), "repositories")

        if provider == "GitHub":
            if github_token:
                _warn_if_secret_typed(
                    "--github-token", "set GITHUB_TOKEN and leave the flag off, or use the browser sign-in")
            token = _github_token(explicit_token=github_token)
            try:
                auth_value = json.dumps({"authType": "Pat", "pat": token})
            finally:
                token = None
            auth_result = _extension_resource_create(
                self.cli_ctx, agent_name, resource_group, "githubAuths", "github_com",
                auth_value, overwrite=True,
            )
        else:
            organization = devops_organization or _devops_organization_from_url(repo_url)
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
                    with _no_http_trace():
                        pat, pat_authorization_id = _devops_pat_token(
                            self.cli_ctx, organization, f"sre-agent-{agent_name}")
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
            try:
                auth_result = _extension_resource_create(
                    self.cli_ctx, agent_name, resource_group, "azureDevOpsAuths", organization,
                    auth_value, overwrite=True,
                )
            except Exception:
                if devops_auth_type != "managed-identity":
                    _revoke_devops_pat(self.cli_ctx, organization, pat_authorization_id)
                raise

        try:
            repo_result = _extension_resource_create(
                self.cli_ctx, agent_name, resource_group, "repositories", display_name,
                repo_value, overwrite=True,
            )
        except Exception:
            # The auth write above already replaced the old credentials, so
            # the agent can't fall back to them.
            auth_name = "github_com" if provider == "GitHub" else organization
            logger.warning(
                "Saved new %s credentials ('%s') on agent '%s', but connecting repository '%s' failed. "
                "Re-run 'az sre repo connect' to finish.", repo_type, auth_name, agent_name, display_name,
            )
            raise
        return {"auth": _redact_auth_result(auth_result), "repository": repo_result}

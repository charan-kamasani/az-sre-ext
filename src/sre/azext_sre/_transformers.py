# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# -o table transformers for commands whose default az auto-table output is
# either unreadable or uses an internal wire value a user wouldn't
# recognize from the portal:
#   - 'sre access list' / 'sre managed-resource list': raw 'az role
#     assignment list' results, a dozen-plus top-level string fields and no
#     nesting, so az's default auto-table dumps every one of them as a
#     column -- confirmed live to wrap into an unreadable wall of text in a
#     normal terminal width.
#   - 'sre connector list' / 'sre connector show': properties.
#     dataConnectorType is an internal wire value (e.g. 'KustoClient') that
#     does not appear anywhere in the portal UI, which only ever shows the
#     display name (e.g. 'Azure Data Explorer') -- confirmed a source of
#     user confusion, so -o table resolves it to the portal name.
# Every other 'sre ... list' command (hook, knowledge, tool, skill, plugin,
# automation, incident-filter) returns a generic Microsoft.App/agents/*
# extension resource with no such wire-name mismatch, which already
# renders narrow/legible and does not need a transformer here.
# --------------------------------------------------------------------------------------------
from collections import OrderedDict

from .custom import CONNECTOR_TYPE_PORTAL_NAMES


def _short_timestamp(value):
    """Trim an ARM ISO-8601 timestamp's fractional seconds for compact display,
    e.g. '2026-11-03T18:10:42.126877+00:00' -> '2026-11-03T18:10:42Z'.
    Assumes UTC ('+00:00'), which is what this RP always returns.
    """
    if not value:
        return value
    return value.split(".", 1)[0].split("+", 1)[0].rstrip("Z") + "Z"


def access_list_table_format(result):
    """Curated columns for 'sre access list': who has access to the agent
    itself, and what role -- the scope is always the agent, so it's omitted
    as redundant. Shows the object ID when there's no display name (names
    are only filled in with --show-names).
    """
    return [
        OrderedDict([
            ("Principal", item.get("principalName") or item.get("principalId")),
            ("Type", item.get("principalType")),
            ("Role", item.get("roleDefinitionName")),
            ("GrantedOn", _short_timestamp(item.get("createdOn"))),
        ])
        for item in result
    ]


def managed_resource_list_table_format(result):
    """Curated columns for 'sre managed-resource list': what external scope
    the agent's own identity can reach, and with what role -- the
    principal here is always the agent's own identity, so PrincipalName
    (a GUID/app-id, not human-readable) is omitted as noise.
    """
    return [
        OrderedDict([
            ("Scope", item.get("scope")),
            ("Role", item.get("roleDefinitionName")),
            ("PrincipalType", item.get("principalType")),
            ("GrantedOn", _short_timestamp(item.get("createdOn"))),
        ])
        for item in result
    ]


def _connector_row(item):
    """Curated row for a single connector: resolves the raw
    properties.dataConnectorType wire value (e.g. 'KustoClient') to the
    real portal display name (e.g. 'Azure Data Explorer') so -o table
    output matches what a user actually sees in the portal, instead of
    the internal API name that caused confusion (see CONNECTOR_TYPE_
    PORTAL_NAMES in custom.py). Only -o table is affected -- -o json/yaml
    continue to return the raw dataConnectorType unchanged, since scripts
    rely on that exact wire value. Types with no confirmed portal display
    name (the 14 unlocked 2026-11-02, plus the 4 Knowledge* types) fall
    back to showing the wire value as-is.
    """
    if not isinstance(item, dict):
        return item
    properties = item.get("properties") or {}
    wire_type = properties.get("dataConnectorType")
    return OrderedDict([
        ("Name", item.get("name")),
        ("Type", CONNECTOR_TYPE_PORTAL_NAMES.get(wire_type, wire_type)),
        ("ProvisioningState", properties.get("provisioningState")),
        ("ConsentStatus", item.get("consentStatus")),
    ])


def connector_list_table_format(result):
    """Curated columns for 'sre connector list' -o table."""
    return [_connector_row(item) for item in result]


def connector_show_table_format(result):
    """Curated columns for 'sre connector show' -o table."""
    return _connector_row(result)


def _priority_text(priorities):
    """IcM stores priorities as numbers, and ARM may echo an unset list as null."""
    if isinstance(priorities, list):
        return ", ".join(str(p) for p in priorities if p is not None) or "All"
    return str(priorities) if priorities not in (None, "") else "All"


def response_plan_list_table_format(result):
    """Curated columns for 'sre response-plan list' -o table (mirrors the portal grid)."""
    rows = []
    for item in result:
        item = item if isinstance(item, dict) else {}
        props = item.get("properties")
        props = props if isinstance(props, dict) else {}
        rows.append(OrderedDict([
            ("Name", item.get("name")),
            ("Enabled", props.get("isEnabled")),
            ("Platform", props.get("incidentPlatform")),
            ("Subagent", props.get("handlingAgent")),
            ("Priority", _priority_text(props.get("priorities"))),
            ("Mode", props.get("agentMode")),
        ]))
    return rows


# Maps AZ_NAME -> table transformer, applied in commands.py right after each
# custom.py AAZCommand recipe is instantiated.
TABLE_TRANSFORMERS = {
    "sre access list": access_list_table_format,
    "sre managed-resource list": managed_resource_list_table_format,
    "sre connector list": connector_list_table_format,
    "sre connector show": connector_show_table_format,
    "sre response-plan list": response_plan_list_table_format,
}

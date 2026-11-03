# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
#
# -o table transformers for the two list commands whose output is a raw
# 'az role assignment list' result (sre access list / sre managed-resource
# list). Those objects have a dozen-plus top-level string fields (Id,
# PrincipalId, PrincipalName, PrincipalType, RoleDefinitionId,
# RoleDefinitionName, Scope, CreatedBy/On, UpdatedBy/On, ...) and no
# nesting, so az's default auto-table dumps every one of them as a column
# -- confirmed live to wrap into an unreadable wall of text in a normal
# terminal width. Every other 'sre ... list' command (connector, hook,
# knowledge, tool, skill, plugin, automation, incident-filter) returns a
# generic Microsoft.App/agents/* extension resource, which only has a
# handful of top-level fields (the rest is nested under 'properties', which
# az's default table auto-flattening does not expand into columns), so
# those already render narrow/legible and do not need a transformer here.
# --------------------------------------------------------------------------------------------
from collections import OrderedDict


def _short_timestamp(value):
    """Trim an ARM ISO-8601 timestamp's fractional seconds for compact display,
    e.g. '2026-11-03T18:10:42.126877+00:00' -> '2026-11-03T18:10:42Z'.
    Assumes UTC ('+00:00'), which is what this RP always returns.
    """
    if not value:
        return value
    return value.split(".", 1)[0].split("+", 1)[0] + "Z"


def access_list_table_format(result):
    """Curated columns for 'sre access list': who has access to the agent
    itself, and what role -- the scope is always the agent, so it's omitted
    as redundant.
    """
    return [
        OrderedDict([
            ("Principal", item.get("principalName")),
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


# Maps AZ_NAME -> table transformer, applied in commands.py right after each
# custom.py AAZCommand recipe is instantiated.
TABLE_TRANSFORMERS = {
    "sre access list": access_list_table_format,
    "sre managed-resource list": managed_resource_list_table_format,
}

# Operations guide

Task-oriented workflows for day-to-day use of `az sre`. For the full
command syntax reference, see [docs/cli-reference.md](cli-reference.md).

## Agent lifecycle

```bash
az sre agent create --name myagent -g myrg -l eastus2 \
  --default-model "{provider:anthropic,name:claude-sonnet-4-5}" \
  --mi-system-assigned

az sre agent show -g myrg -n myagent
az sre agent list -g myrg
az sre agent start -g myrg --agent-name myagent
az sre agent stop -g myrg --agent-name myagent
az sre agent delete -g myrg -n myagent -y
```

`start`/`stop` and `list-connectors-with-secret`/`connector list-secret`
only accept `--agent-name` (no `-n` shorthand) — this is existing,
confirmed-correct behavior, not a bug.

At least one managed identity is required at create time:

```bash
az sre agent identity assign -g myrg --agent-name myagent --mi-system-assigned
az sre agent identity show -g myrg --agent-name myagent
az sre agent identity remove -g myrg --agent-name myagent --mi-system-assigned
```

`identity remove` is correctly rejected by the server if it would leave the
agent with zero identities (`ManagedIdentityRequired`).

## RBAC

```bash
az sre agent grant-access -g myrg --agent-name myagent \
  --assignee someone@example.com --role user
```

`--role` accepts `admin`/`user`/`author`/`reader` — a thin wrapper over
`az role assignment create` that builds the agent's full resource-ID scope,
not a new ARM operation. See `GrantAccess._ROLES` in `custom.py` for the
exact mapping, confirmed against real `az role definition list` output.

## Data connectors

```bash
az sre agent connector create -g myrg --agent-name myagent \
  --name my-kusto-connector --data-connector-type Kusto \
  --data-source "https://help.kusto.windows.net/Samples"

az sre agent connector show -g myrg --agent-name myagent --name my-kusto-connector
az sre agent connector update -g myrg --agent-name myagent \
  --name my-kusto-connector --data-source "https://help.kusto.windows.net/Samples2"
az sre agent connector list-secret -g myrg --agent-name myagent \
  --connector-name my-kusto-connector
az sre agent connector delete -g myrg --agent-name myagent --name my-kusto-connector -y
```

`--data-source` is required for `Kusto` connectors (learned from a real
server error, not documented in the generated help). `dataSource` and
`identity` are write-only on the wire — they never come back on `show`/
`list`/`list-secret`, even for the connector that owns them; this is
confirmed server behavior, not a CLI omission.

`consentStatus` is a derived, CLI-added field on connector output — present
only for `EntraOAuth`-based connectors, silently absent otherwise. It is
unit-tested for both branches but has not been live-verified for the
positive ("Consented") branch, because EntraOAuth MCP connectors are
server-side disabled in the test subscription used so far.

## Runbook extension payload shapes

`agent extension create/show/list/delete` manage a data-plane proxy
resource with **no ARM Swagger** — every payload shape must be confirmed by
live probing, not by reading a spec. Status as of the last live-verification
pass:

| Extension type | Confirmed shape | Status |
| --- | --- | --- |
| `commonPrompts` | `{"prompt": "<string>"}`, one prompt per ARM resource name (e.g. `commonPrompts/default`) | Confirmed — corrected after an earlier source-mined guess (`Array<{name, content}>`) turned out to be wrong on the wire |
| `globalSettings` | `{}` plus optional `toolPermissions`/`toolStatuses`/`skillStatuses`/`customInstructions`/`approvalExpirationSetting` | Confirmed — true ARM singleton, `DELETE` unsupported, reset via `PUT {}` |
| `pluginMarketplaces` | See `PLAN.md` | Confirmed |
| `tools`, `skills`, `scheduledTasks`, `incidentFilters`, `incidentHandlers`, `httpTriggers`, `repositories`, `githubAuths`, `azureDevOpsAuths`, `pluginInstallations` | Not yet confirmed | `tools` is known to accept the root-object shape gate but then fails with `500 InternalServerError: "Failed to create or update extension in Kubernetes"` for an empty `{}` body against resource name `default` — root cause (required fields vs. invalid resource name) not yet isolated |

A universal constraint applies to every extension type: the decoded
`--value` must be a JSON **object** at the root. A bare JSON array is
always rejected with `"request body contains an invalid or unrecognized
property"`.

```bash
az sre agent extension create -g myrg --agent-name myagent \
  --extension-type commonPrompts --extension-name default \
  --value '{""prompt"": ""Investigate using recent deployments first.""}'

az sre agent extension list -g myrg --agent-name myagent --extension-type commonPrompts
az sre agent extension delete -g myrg --agent-name myagent \
  --extension-type commonPrompts --extension-name default
```

See [docs/testing.md](testing.md#live-verification-workflow) for the
round-trip (PUT then GET) technique used to confirm a shape, and why
checking only for a 200 response is not sufficient proof.

## Networking

See [docs/networking.md](networking.md) for VNet injection and sandbox
egress configuration via `agent update-network`.

## Usage and connection info

```bash
az sre agent get-connection -g myrg -n myagent
az sre agent list-usage -g myrg -n myagent
az sre supported-agent-model list -l eastus2
```

## Cleanup ownership

Live-tested resources (throwaway agents, test connectors, test extension
values) must be fully torn down after a verification pass — see
[docs/testing.md](testing.md#live-verification-workflow). Confirm with a
final `list`/`show` sweep that no stray resources remain before closing out
a verification session.

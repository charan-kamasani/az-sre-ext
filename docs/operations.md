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

`start`/`stop` and `connector list-secret` only accept `--agent-name` (no
`-n` shorthand) — this is existing, confirmed-correct behavior, not a bug.

At least one managed identity is required at create time:

```bash
az sre identity assign -g myrg --agent-name myagent --system-assigned
az sre identity show -g myrg --agent-name myagent
az sre identity remove -g myrg --agent-name myagent --system-assigned
```

`identity remove` is correctly rejected by the server if it would leave the
agent with zero identities (`ManagedIdentityRequired`).

## RBAC

```bash
az sre access grant -g myrg --agent-name myagent \
  --assignee someone@example.com --role user
```

`--role` accepts `admin`/`user`/`author`/`reader` — a thin wrapper over
`az role assignment create` that builds the agent's full resource-ID scope,
not a new ARM operation. See the `*_ROLES` constant in `custom.py` for the
exact mapping, confirmed against real `az role definition list` output.
Pass `--assignee-me` instead of `--assignee` to grant yourself access without
looking up your own object ID first (also available as
`az sre agent create --grant-access-to-me <role>` at agent-creation time).

The mirror image is `az sre managed-resource grant/revoke/list` — instead of
granting a person access *to* the agent, it grants the agent's own managed
identity Reader + Monitoring Contributor *on* an external subscription,
resource group, or management group (matches the portal's Build + setup >
Context > Managed resources page):

```bash
az sre managed-resource grant -g myrg --agent-name myagent \
  --target-subscription <sub-id> --target-resource-group monitored-rg
az sre managed-resource list -g myrg --agent-name myagent
az sre managed-resource revoke -g myrg --agent-name myagent \
  --target-subscription <sub-id> --target-resource-group monitored-rg
```

## Data connectors

```bash
az sre connector create -g myrg --agent-name myagent \
  --name my-kusto-connector --data-connector-type Kusto \
  --data-source "https://help.kusto.windows.net/Samples"

az sre connector show -g myrg --agent-name myagent --name my-kusto-connector
az sre connector update -g myrg --agent-name myagent \
  --name my-kusto-connector --data-source "https://help.kusto.windows.net/Samples2"
az sre connector list-secret -g myrg --agent-name myagent \
  --connector-name my-kusto-connector
az sre connector delete -g myrg --agent-name myagent --name my-kusto-connector -y
```

`--data-source` is required for `Kusto` connectors (learned from a real
server error, not documented in the generated help). `dataSource` and
`identity` are write-only on the wire — they never come back on `show`/
`list`/`list-secret`, even for the connector that owns them; this is
confirmed server behavior, not a CLI omission.

`consentStatus` is a derived, CLI-added field on connector output — present
only for `EntraOAuth`-based connectors, silently absent otherwise. When a
connector's `consentStatus` is `PendingConsent`, the CLI now also emits a
warning with a direct Azure Portal deep link to finish the OAuth consent —
there is no public ARM action to initiate or complete consent from the CLI
itself (confirmed by inspecting the control-plane's ARM-facing surface).

For MCP connectors (including the built-in GitHub MCP server) and for
knowledge sources, use the convenience flags instead of hand-built JSON:

```bash
az sre connector create -g myrg --agent-name myagent \
  --name conn-mcp --data-connector-type Mcp --github true

az sre knowledge create -g myrg --agent-name myagent \
  --name my-notes --type text --file-path ./notes.md
```

### Per-`--data-connector-type` live-verification status

All 11 real `--data-connector-type` values were probed end-to-end (create →
show/list → delete) against a real agent on 2026-10-28:

| Type | Status | Notes |
|---|---|---|
| `Kusto` | Live-verified | Requires `--data-source`. |
| `Mcp` | Live-verified | Both `--github true` and `--mcp-endpoint <url>` confirmed. A real server-side check rejects an MCP endpoint that shares a host with an existing `Kusto` connector ("HTTP MCP and Kusto requests on the same host cannot be distinguished safely") — not a CLI bug, pick a distinct host. |
| `Teams` | Live-verified | No `--data-source` needed in this tenant; `extendedProperties` empty on read-back (write-only, same as other types). |
| `Icm` | Live-verified | Singleton per agent; service auto-populates `extendedProperties.icmEndpointMode: "ProdOnly"` regardless of `--data-source` passed. |
| `KustoClient` | Live-verified | Kusto via the `@azure/mcp` server; `--data-source` accepted but not required. |
| `KnowledgeText` | Live-verified | Use `--extended-properties '{"content": "..."}'` directly, or `sre knowledge create --type text --file-path <path>`. |
| `KnowledgeFile` | Live-verified | Known service-side gap: `extendedProperties` (fileContent/fileName) always reads back empty — confirmed via the actual request body sent, not a CLI defect. |
| `KnowledgeWebPage` | Live-verified (bug fixed this pass) | Correct shape is `--extended-properties '{"url": "..."}'` **only** — sending `--data-source` at the same time (the CLI's own prior behavior) made the service return a 500. `sre knowledge create --type webpage --url <url>` was fixed to match and now round-trips correctly. |
| `KnowledgeRepository` | Live-verified | Use `--extended-properties '{"url": "..."}'`; `sre repo connect` is the dedicated front door for this type. |
| `Outlook` | Blocked — real server error | `create` consistently returns `(InternalServerError) Internal server error occurred`, with and without `--data-source`. Reproduced twice; not a CLI defect (payload shape matches every other working type) — looks like this connector type isn't provisionable in this tenant/environment yet. Re-verify once a tenant known to support Outlook connectors is available. |
| `Dgrep` | Blocked — real server error | `create` returns `(InvalidRequestParameter) ... MDS endpoint is not approved.` — a real, environment-specific allowlist check on the service side, not a shape or CLI defect. |

Cosmetic (non-blocking) noise you may see on `connector create`/`update`:
an `ERROR: Operation returned an invalid status 'Not Found'` line can print
to stderr even though the command still exits `0` with the correct created
resource in its JSON output. This comes from the generated AAZ long-running-
operation poller's final-state GET racing real ARM-proxy replication lag —
confirmed harmless (the resource exists and `show`/`list` return it
immediately after) — not something fixable without hand-editing the
generated recipe, which this project deliberately never does.


## Runbook extension payload shapes

`extension create/show/list/delete` manage a data-plane proxy resource with
**no ARM Swagger** — every payload shape must be confirmed by live probing,
not by reading a spec. Prefer a dedicated front-door noun where one exists
(`tool`, `skill`, `hook`, `instructions`, `knowledge`, `repo connect`,
`plugin marketplace`/`plugin install`) — `extension` itself is only needed
for the six extension types with no dedicated noun yet. Status as of the
last live-verification pass (12 of 15 extension types confirmed live):

| Extension type | Confirmed shape | Status |
| --- | --- | --- |
| `commonPrompts` (`instructions`) | `{"prompt": "<string>"}`, one prompt per ARM resource name (e.g. `commonPrompts/default`) | Live-verified |
| `globalSettings` | `{}` plus optional `toolPermissions`/`toolStatuses`/`skillStatuses`/`customInstructions`/`approvalExpirationSetting` | Shape-confirmed from the control-plane team's own integration tests — true ARM singleton, `DELETE` unsupported, reset via `PUT {}` |
| `pluginMarketplaces` (`plugin marketplace`), `pluginInstallations` (`plugin install`) | See `PLAN.md` | Create/show live-verified; K8s-backed install provisioning not exercised in this sandbox |
| `tools` (`tool`), `skills` (`skill`), `hooks` (`hook`), `repositories` (`repo connect`) | Confirmed | Live-verified end to end (PUT + GET round-trip against a real agent) |
| `incidentFilters`, `incidentHandlers` | Shape-confirmed from authoritative source | Live-create is environment-blocked (sandbox tenant lacks real IcM team-identity resolution), not a shape defect |
| `githubAuths`, `azureDevOpsAuths` | Shape-confirmed from authoritative source | Live-create rejected by real credential/token validation on the service side, not a shape defect |
| `subagents` | No model found | Believed server-managed / Agent-Canvas-only, not CLI-creatable |

A universal constraint applies to every extension type: the decoded
`--value` must be a JSON **object** at the root. A bare JSON array is
always rejected with `"request body contains an invalid or unrecognized
property"`.

```bash
az sre extension create -g myrg --agent-name myagent \
  --extension-type globalSettings --extension-name default --value '{}'

az sre extension list -g myrg --agent-name myagent --extension-type globalSettings
az sre extension delete -g myrg --agent-name myagent \
  --extension-type globalSettings --extension-name default
```

See [docs/testing.md](testing.md#live-verification-workflow) for the
round-trip (PUT then GET) technique used to confirm a shape, and why
checking only for a 200 response is not sufficient proof.

## Networking

See [docs/networking.md](networking.md) for VNet injection and sandbox
egress configuration via `network update`.

## Usage and connection info

```bash
az sre connection show -g myrg -n myagent
az sre usage list -g myrg -n myagent
az sre supported-agent-model list -l eastus2
```

## Cleanup ownership

Live-tested resources (throwaway agents, test connectors, test extension
values) must be fully torn down after a verification pass — see
[docs/testing.md](testing.md#live-verification-workflow). Confirm with a
final `list`/`show` sweep that no stray resources remain before closing out
a verification session.

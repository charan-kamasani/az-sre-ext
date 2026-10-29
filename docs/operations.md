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

### `agent create`/`agent update` -- Properties/Identity args live-verification

All non-trivial `--<property>` arguments on `agent create`/`agent update`
were live-tested end-to-end against a real agent (not just schema/help
inspection). Status:

| Arg | Status | Notes |
| --- | --- | --- |
| `--default-model` | Live-verified | Used throughout this session. |
| `--grant-access-to-me` | Live-verified | See RBAC section. |
| `--mi-system-assigned` (create) | Live-verified | **Required** -- see the `agent create` defaulting behavior below. |
| `--mi-user-assigned` (create only) | Live-verified | Not accepted on `agent update` (service only exposes it on the create/PUT recipe) -- use `az sre identity assign --user-assigned <id>` to add one to an existing agent instead. |
| `--tags` | Live-verified | Plain pass-through. |
| `--upgrade-channel` | Live-verified | `Preview`/`Stable` both accepted. |
| `--action-configuration` | Live-verified, with one real enum/server mismatch found | `identity` must be the literal string `"system"` (not a resource ID) to reference the agent's own system-assigned identity, or a user-assigned identity's resource ID. **`mode` accepts `Autonomous`/`ReadOnly`/`Review` per the CLI's generated enum (from Swagger), but the live service only accepts `Autonomous`/`Review` -- `ReadOnly` is rejected with `(InvalidActionMode)`.** This is a Swagger/service enum drift, not a CLI defect; not fixable without a service-side Swagger fix or hand-editing generated code (which this project avoids). |
| `--knowledge-graph-configuration` | Live-verified | Same `identity: "system"` convention as `--action-configuration`. |
| `--log-configuration` | Live-verified, with a real identity-assign interaction bug found | `applicationInsightsConfiguration.connectionString` is write-only (never echoed back on `agent show`), same pattern as connector `extendedProperties`/`dataSource`. **Known gotcha**: if an agent has `--log-configuration` set, a subsequent `sre identity assign`/`sre identity remove` call will fail with `(InvalidApplicationInsightsConfiguration) The AppId and ConnectionString fields must be provided together` -- these are generated GET-merge-PUT commands, and the GET can never recover the write-only `connectionString`, so the merged PUT re-submits `appId` alone. Not fixable at the CLI layer without either (a) silently dropping the user's existing log configuration as a side effect of an unrelated identity change (worse), or (b) a service-side change. **Workaround**: re-apply `--log-configuration` with the same `app-id`/`connection-string` immediately after any `identity assign`/`identity remove` call on an agent that has one configured. The same risk likely applies to `--incident-management-configuration`'s `connection-key` (also a write-only/password field), though not independently reproduced. |
| `--incident-management-configuration` | Live-verified, with a real validation message found | `connection-url` must be omitted for production IcM connections (it's auto-wired via the Agent Space proxy); if set for testing it must be an `https://*.microsofticm.com` URL -- any other host is rejected with `(InvalidIcmConnectionUrl)` and a clear, actionable error message. |
| `--agent-identity` | Not independently tested | Requires `initial-sponsor-group-id`, a real tenant-specific AAD "sponsor group" GUID used for agent-identity/Teams-user provisioning -- out of scope without guidance from the SRE Agent team on which group is valid to use in this tenant. |

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

### `hook` eventType has 4 values, not 2

The official docs (`sre.azure.com/docs/capabilities/agent-hooks`) confirm
hooks fire on one of **four** lifecycle events: `Start`, `PreToolUse`,
`PostToolUse`, `Stop` — all usable via the REST API v2 this CLI calls
directly. The portal's own "Create hook" dialog currently only exposes
`PostToolUse`/`Stop` in its UI picker, but that's a portal UI limitation,
not an API one. `az sre hook create`'s client-side shape validator used to
incorrectly restrict `eventType` to only `("Stop", "PostToolUse")`
(matching the portal's UI subset), which would have wrongly rejected valid
`Start`/`PreToolUse` payloads before they ever reached ARM. Fixed to accept
all four values.

### `hook.failMode` is "Allow"/"Block", not "Allow"/"Deny"

Live-probed against a real agent (`mytestagent`): `failMode` governs what
happens if the **hook itself** errors or times out — it is not the hook's
allow/deny decision output (that's returned separately by the hook's
prompt/script). Confirmed accepted values are `"Allow"`/`"Block"`
(case-insensitive); `"Deny"`, `"fail"`, and `"continue"` all look
plausible but are rejected by the real API with a generic `"The extension
configuration is invalid"` error that gives no hint about which field is
wrong. The CLI now validates `failMode` client-side against the confirmed
enum so this is caught immediately instead of surfacing as an opaque
400 from ARM.

**PowerShell note**: `az.cmd` on Windows mangles `--value '{"..."}'` JSON
passed directly in PowerShell (quotes get eaten, and shell metacharacters
like `&&` inside a `command` field get interpreted by cmd.exe before the
JSON reaches the CLI). Reliable options: write the JSON to a file and pass
`--value (Get-Content hook.json -Raw)`, or invoke via `subprocess.run([...],
shell=False)` in Python. Avoid `&&`/`|`/`<`/`>` inside a hook's `command`
field value on Windows for the same reason.

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

### `tool` discriminator is `type`, not `toolType`; `LinkTool` uses `template`, not `url`

An earlier, now-fixed `az sre tool create --value` example suggested
`{"toolType": "LinkTool", "url": "https://..."}`. That shape reaches ARM
fine but fails downstream with an opaque `InternalServerError: Failed to
create or update extension in Kubernetes` -- both field names are wrong.
Confirmed against `sreagent-runtime`'s `ExtendedAgentToolApiModel`/
`LinkToolApiModel` (the real agent runtime's wire models, a stricter
source than the ARM control-plane proxy) and live-verified by creating a
real `LinkTool` on `mytestagent`:

- The polymorphic discriminator field is **`type`** (values: `KustoTool`,
  `LinkTool`, `PythonTool`, `HttpClientTool`), not `toolType`.
- `LinkTool`'s link field is **`template`**, not `url`. `url` is a real
  field, but only on `HttpClientTool`.

```bash
az sre tool create -g myrg --agent-name myagent -n my-link-tool --value \
  '{"type": "LinkTool", "name": "my-link-tool", "description": "Opens the docs", \
    "template": "https://example.com/docs"}'
```

The CLI's `_validate_tools_shape` client-side validator already enforced
the correct `type`/`template` fields; only the `--value` help text's
example was stale and contradicted it. Fixed so the documented example
now matches the validator and the real API.

### `globalSettings.toolStatuses` is accepted but doesn't round-trip; `toolPermissions`/`approvalExpirationSetting` do

Live-verified all three `globalSettings` fields on `mytestagent` via
`az sre extension create --extension-type globalSettings`:

- `toolPermissions` (`allow`/`ask`/`deny` arrays) -- **persists correctly**,
  confirmed via `show` after `create`.
- `approvalExpirationSetting` (`enabled`/`approvalExpirationInMinutes`) --
  **persists correctly**, confirmed via `show` after `create`.
- `toolStatuses` (`[{"name": ..., "enabled": ...}]`, enable/disable a
  built-in tool) -- the PUT is accepted, unknown tool names are rejected
  (`InvalidRequestParameterWithDetails: Unknown or custom built-in tool
  name`, confirming real server-side name validation runs), but a
  subsequent `show`/`list` always comes back with `toolStatuses: []`
  regardless of what was sent, even for a known-valid name
  (`AddTagToIncident` tested).

Root cause (confirmed by reading `sreagent-runtime`'s
`GlobalSettingsExtensionService.cs`): the real Cosmos document stores this
under `toolConfigurations.toolOverrides` (not the ARM-facing
`toolStatuses` name), and the read path (`MapSettings`) re-filters
`toolOverrides` through a freshly-resolved "current built-in tool scope"
set (`GetBuiltInScopeAsync`) -- any override whose tool name isn't in that
live-resolved scope at *read* time is silently dropped from the response,
even though the write passed an equivalent scope check moments earlier
and was saved. This is a service-side behavior, not a CLI bug -- the CLI
sends/validates the shape correctly. Net effect: **enabling/disabling
built-in tools via `az sre extension create --extension-type
globalSettings` is unreliable today**; use the portal's Built-in tools tab
for that until confirmed fixed server-side.

### `repo connect` fixes: stale `--repo-type` example, misleading GitLab claim, and a real PAT-leak bug

Three issues found while live-testing `az sre repo connect`:

1. **Stale example**: `_help.py`'s example used `--repo-type GitHub`, a flag
   that doesn't exist -- the real flag is `--provider`. Fixed.
2. **Misleading docstring**: `_RepoGroup` claimed "Supports GitHub, Azure
   DevOps, and GitLab", but `repo connect`'s `--provider` enum only allows
   `GitHub`/`AzureDevOps` -- GitLab isn't wired up for this one-step
   command (it IS supported at the raw `sre extension create
   --extension-type repositories` level). Docstring corrected to be
   precise about the split.
3. **Security bug (the serious one)**: live-tested against a real Azure
   DevOps org (`dev.azure.com/devdiv`) -- `repo connect` mints a PAT via
   the vssps REST API and echoes the full `auth` result back to the user.
   Confirmed server-side redaction is inconsistent by provider:
   `githubAuths` already comes back masked (`"pat": "******"`), but
   `azureDevOpsAuths` returned the **real PAT in plaintext** in the
   command's own output. Fixed client-side with a new `_redact_auth_result`
   helper that masks `pat`/`secret`/`password`/`token` fields in the
   returned `auth` object regardless of provider, so this command never
   prints a live secret even if server-side redaction behavior changes or
   regresses for either provider. Both live-minted PATs from testing this
   (one GitHub-account-scoped via `gh`, one Azure DevOps PAT via vssps)
   were revoked immediately after discovery/confirmation.

```bash
az sre repo connect -g myrg --agent-name myagent \
  --repo-url https://dev.azure.com/myorg/myproject/_git/myrepo --provider AzureDevOps
```

### `az sre workflow`: new group for scheduled tasks and HTTP triggers

The portal's "Automation" tab (previously "Workflows" in an older nav)
exposes four things: Scheduled tasks, HTTP triggers, Subagents, and
Incident filters/handlers. All four turned out to already be generic
`az sre extension` resource types (`scheduledTasks`, `httpTriggers`,
`subagents`, `incidentFilters`/`incidentHandlers`), confirmed by reading
`AgentExtensionsApiServiceExtensionTypesTests.cs`'s
type-name-to-C#-model table in `AAPT-SREAgent-ControlPlane`.

Added noun-specific wrappers (mirroring the `tool`/`repo` pattern) for
the two simplest, well-defined, actively-supported types:

- `az sre workflow scheduled-task create/show/list/delete` -- run the
  agent on a cron schedule against a prompt.
- `az sre workflow http-trigger create/show/list/delete` -- run the
  agent from an inbound webhook call.

Both live-verified end-to-end against `mytestagent`: created via CLI,
confirmed showing up correctly in the portal's Automation tab (status,
type, and for HTTP triggers the real `triggerUrl`), then deleted via
CLI and confirmed gone from the portal.

**Intentionally not wrapped (yet):**
- `incidentFilters` -- a real, actively-developed type, but with a much
  larger spec (20+ fields, nested ICM/AzMonitor settings) -- deferred to
  a follow-up.
- `incidentHandlers` -- confirmed **legacy/deprecated**: the control
  plane has its own migration tooling
  (`DeleteLegacyIncidentHandlerDocument`, `MigrateLegacyIncidentHandler`)
  moving everyone onto `incidentFilters` instead. Deliberately not
  exposed as a CLI create path so the CLI doesn't steer anyone onto a
  deprecated pattern.
- `subagents` -- the largest of the five: a full nested agent definition
  (instructions, handoffs, tools, mcpTools, connectors, hooks, etc.),
  essentially the same scope as `az sre agent create` itself. Deferred
  to its own follow-up project.

```bash
az sre workflow scheduled-task create -g myrg --agent-name myagent \
  -n daily-digest --value '{"cronExpression":"0 9 * * 1-5","agentPrompt":"Summarize overnight alerts"}'

az sre workflow http-trigger create -g myrg --agent-name myagent \
  -n alert-webhook --value '{"agentPrompt":"Investigate the attached alert payload"}'
```

## Networking

See [docs/networking.md](networking.md) for VNet injection and sandbox
egress configuration via `network update`.

## Usage and endpoint info

```bash
az sre endpoint show -g myrg -n myagent
az sre usage list -g myrg -n myagent
az sre agent list-models -l eastus2
```

`endpoint show` (renamed from `connection show`)/`access grant`/`access revoke`/
`agent delete --no-wait` live-verification (all pass):

| Command | Status | Notes |
|---|---|---|
| `endpoint show` (was `connection show`) | Fixed real bug | Was rendering `dataPlaneAudience` as `{"isDefault": true}` instead of the actual URL string whenever `--data-plane-audience` was left at its default. Root cause: an unset `AAZStrArg` with a declared `default=` resolves to a `knack.validators.DefaultStr` (a `str` subclass used to flag "still at default"); az's own output formatter introspects that subclass via `vars()` instead of treating it as a plain string. Fixed by coercing with `str(...)` before returning. The on-disk `~/.azure/sreAgentConnections.json` file was never affected (stdlib `json.dump()` already handles `str` subclasses correctly) — only the console JSON output was wrong. Renamed to `endpoint show` per live naming feedback (`connection` read too similar to `connector`). |
| `access grant`/`revoke --assignee-me` | Works | Live-verified: granting `reader` while already holding `admin` correctly adds a second role assignment; revoking removes only the targeted one, leaving `admin` intact. |
| `agent delete --no-wait` | Works | Live-verified: returns in ~2.6s, agent transitions through `Deleting` provisioningState, and is confirmed gone (`ResourceNotFound`) ~20-40s later. |

## Cleanup ownership

Live-tested resources (throwaway agents, test connectors, test extension
values) must be fully torn down after a verification pass — see
[docs/testing.md](testing.md#live-verification-workflow). Confirm with a
final `list`/`show` sweep that no stray resources remain before closing out
a verification session.

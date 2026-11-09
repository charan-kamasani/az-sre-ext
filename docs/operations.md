# Operations guide

Task-oriented workflows for day-to-day use of `az sre`. For the full
command syntax reference, see [docs/cli-reference.md](cli-reference.md).

## Agent lifecycle

```bash
az sre agent create --name myagent -g myrg -l eastus2 \
  --default-model "{provider:anthropic,name:automatic}" \
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

**Default when neither `--mi-system-assigned` nor `--mi-user-assigned` is
passed to `agent create`**: matches the Azure Portal's own default by
auto-creating a new `Microsoft.ManagedIdentity/userAssignedIdentities`
resource and enabling both system-assigned and user-assigned identities on
the agent (`identity.type = "SystemAssigned, UserAssigned"`). This is
confirmed against the portal's own ARM template
(`createUserIdentity ?? true`) and is now documented directly on both
`--mi-system-assigned`/`--mi-user-assigned` in `--help`, not just a runtime
warning — found during a help-only live walkthrough of the CLI where this
side effect was discoverable only after running the command.

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
Use `az sre access list -g myrg --agent-name myagent` to see every current
role assignment on the agent (added after a help-only live walkthrough found
no documented way to verify a grant afterward — a thin wrapper over
`az role assignment list --scope <agent-id>`). `-o table` shows a curated
`Principal`/`Type`/`Role`/`GrantedOn` view (not every raw field) — see the
same note under `sre managed-resource list` below for why.

**`--grant-access-to-me` cannot be combined with `--no-wait`** on
`agent create`: the grant runs in the AAZ command's `post_operations()` hook,
which the generated no-wait code path (`build_lro_poller`) never reaches —
advancing the `pre_operations -> yield PUT -> post_operations` generator
only one step before returning. This combination is rejected up front with a
clear `CLIError` instead of silently never granting access.

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

`access list` and `managed-resource list` both return a raw
`az role assignment list` object (a dozen-plus flat top-level fields —
`id`/`principalId`/`principalName`/`principalType`/`roleDefinitionId`/
`roleDefinitionName`/`scope`/`createdBy`/`createdOn`/`updatedBy`/`updatedOn`),
which az's default `-o table` auto-generator renders as one column per
field — confirmed live to wrap into an unreadable wall of text at a normal
terminal width. Both commands register a custom `table_transformer`
(`_transformers.py`) that curates the columns actually useful for each: a
`Principal`/`Type`/`Role`/`GrantedOn` view for `access list` (the scope is
always the agent itself, so it's omitted), and a
`Scope`/`Role`/`PrincipalType`/`GrantedOn` view for `managed-resource list`
(the principal is always the agent's own identity, so its GUID/app-id is
omitted as noise). `-o json`/`-o jsonc`/`-o yaml`/etc. are unaffected and
still return every field.

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

`--data-connector-type` also accepts the product's own friendly names
(`"Azure Data Explorer"`, `"MCP server"`, `"Office 365 Outlook"`, etc. — see
the friendly-names table below), case-insensitively, as an alias for the
raw wire value. `--data-source` is required for `Kusto` connectors (learned
from a real server error, not documented in the generated help). Note:
`"Azure Data Explorer"` (the bare friendly name, matching what the portal
calls it) resolves to `KustoClient`, not `Kusto` — the portal's own picker
has no entry for plain `Kusto` at all; use `"Azure Data Explorer Cluster"`
or the raw `Kusto` value directly for the legacy pinned-cluster type.
`dataSource`
and `identity` are write-only on the wire — they never come back on `show`/
`list`/`list-secret`, even for the connector that owns them; this is
confirmed server behavior, not a CLI omission.

`connector list`/`show -o table` resolve `properties.dataConnectorType`'s
raw wire value (e.g. `KustoClient`) to the real portal display name (e.g.
`Azure Data Explorer`) via a curated `table_transformer`
(`_transformers.py`, `CONNECTOR_TYPE_PORTAL_NAMES` in `custom.py`) —
confirmed a real source of user confusion, since the wire value never
appears anywhere in the portal UI. Only the 7 types with a confirmed
portal picker entry (`KustoClient`, `Kusto`, `Mcp`, `Outlook`, `Teams`,
`Icm`, `Dgrep`) are mapped; the 14 types unlocked 2026-11-02 and the 4
`Knowledge*` types have no confirmed portal display name, so they fall
back to showing the wire value as-is rather than guessing. `-o json`/
`-o yaml`/etc. are unaffected and still return the raw `dataConnectorType`
unchanged, since scripts/automation rely on that exact value.

**How the portal's single "Azure Data Explorer" option actually maps to
`Kusto`/`KustoClient` (confirmed against `ConnectorWizardFormik.tsx` and
`DialogHelper.tsx`'s `buildKustoConnectorsFromClusterGroups`, and live
ARM-verified):** picking "Azure Data Explorer" in the portal does **not**
create one connector — it can create several:

- The connector you name in step 2 is always created as `KustoClient` (the
  generic MCP Kusto-query capability, no `--data-source` needed). This is
  what `--data-connector-type "Azure Data Explorer"` creates.
- Each optional "cluster group" you add in step 3 ("Add clusters") becomes
  its **own separate connector**, created as `dataConnectorType: "Kusto"`
  (`ConnectorType.AzureDataExplorerQuery = 'Kusto'` in source), named after
  the group, with `--data-source` set to the group's first cluster URI.
  So `Kusto` **does** have a portal entry point after all — just reached
  indirectly, through the "Azure Data Explorer" wizard's cluster-groups
  step, not as its own top-level picker entry. (Correcting an earlier
  assumption in this doc that `Kusto` was portal-unreachable.)
- The review step's "Allow agent to use query tools from this connector"
  checkbox sets `extended-properties.toolsVisibleToMetaAgent` on the
  `KustoClient` parent connector to `["*"]` (checked) or `[]` (unchecked) —
  use `--tool-access true|false` instead of hand-building this JSON
  (live-verified: both values persist and read back correctly).
- A cluster group's additional clusters beyond the first are meant to go
  into `extended-properties.additionalClusters` on the child `Kusto`
  connector, but this was live-verified to **not** persist on read-back
  (same known echo-bug pattern as `KnowledgeFile`'s `fileContent` -- see
  below) -- so the CLI does not offer a convenience flag for it. If you
  need multiple clusters, create one `Kusto` connector per cluster instead.

To replicate a cluster group yourself:

```bash
az sre connector create -g myrg --agent-name myagent \
  --name azure-data-explorer --data-connector-type "Azure Data Explorer" \
  --tool-access true

az sre connector create -g myrg --agent-name myagent \
  --name dnci-westus --data-connector-type Kusto \
  --data-source "https://dnci.westus.kusto.windows.net/dnci"
```

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

### Friendly names

Each `--data-connector-type` value also has an official product name (from
the portal's own i18n strings, `sreagent-runtime`'s
`Agent.Web/Client/src/src/Strings/SREAgentResources.ts`) that the CLI now
accepts as an alias, case-insensitively, alongside the raw wire value:

| Wire value (`--data-connector-type`) | Friendly name (also accepted) |
|---|---|
| `KustoClient` | Azure Data Explorer — this is the exact type the portal creates when you pick "Azure Data Explorer" (confirmed: the portal's picker has no separate entry for plain `Kusto`, and always persists that selection as `KustoClient`) |
| `Kusto` | Azure Data Explorer Cluster — pinned-single-cluster type; has no *direct* top-level portal picker entry, but the portal creates it indirectly as a per-cluster-group child connector under the "Azure Data Explorer" wizard's optional "Add clusters" step; requires `--data-source` |
| `Mcp` | MCP server (a.k.a. "User provided connector"; portal Title corrected 2026-11-04 — not "Custom MCP") |
| `Outlook` | Office 365 Outlook |
| `Teams` | Microsoft Teams |
| `Icm` | IcM connector (portal Title corrected 2026-11-04 — subtitle is "Microsoft IcM") |
| `Dgrep` | DGrep (portal Title corrected 2026-11-04 — subtitle is "Microsoft DGrep") |

`KnowledgeText`/`KnowledgeFile`/`KnowledgeWebPage`/`KnowledgeRepository`
have no separate portal-facing connector name — they're reached through the
dedicated `sre knowledge create`/`sre repo connect` nouns instead, not typed
in directly by most users.

### Master connector catalog: portal vs. this CLI (captured 2026-11-04)

Every connector card the user captured from the real SRE Agent portal picker,
cross-referenced against this CLI's `DATA_CONNECTOR_TYPES` allowlist. This is
the authoritative tracking table for "is X implemented in the CLI yet?" —
update it whenever a new wire value or portal card is confirmed.

| Portal card (Title) | Portal subtitle | Wire value (`--data-connector-type`) | CLI status |
|---|---|---|---|
| Azure Data Explorer | Azure Data Explorer | `KustoClient` | **Implemented** — live-verified, default type |
| Azure Data Explorer (cluster group, indirect) | — | `Kusto` | **Implemented** — live-verified, requires `--data-source` |
| MCP server | User provided connector | `Mcp` | **Implemented** — live-verified |
| DGrep | Microsoft DGrep | `Dgrep` | **Implemented** — shape-confirmed; create blocked in this tenant by a real "MDS endpoint is not approved" server error (not a CLI defect) |
| Geneva Metrics | Geneva Metrics (MDM) | `GenevaMetrics` | **Implemented** — live-verified, tenant-gated |
| Log Analytics Workspace | Log Analytics | `LogAnalytics` | **Implemented** — schema/create-level verified |
| Application Insights | Application Insights | `AppInsights` / `ApplicationInsights` | **Implemented** — schema/create-level verified; which wire value the portal card persists as is unconfirmed |
| Datadog | Datadog | *(none)* | **Not implemented** — no confirmed wire value; do not assume it's `Mcp` + endpoint without backend confirmation |
| Elasticsearch | Elasticsearch | *(none)* | **Not implemented** — same caveat |
| Dynatrace | Dynatrace | *(none)* | **Not implemented** — same caveat |
| New Relic | New Relic | *(none)* | **Not implemented** — same caveat |
| Splunk | Splunk | *(none)* | **Not implemented** — same caveat |
| Hawkeye | Hawkeye (NeuBird) | *(none)* | **Not implemented** — same caveat |
| S360 connector | S360 | `S360` | **Implemented** — schema/create-level verified |
| Gmail | Google Gmail | *(none)* | **Not implemented** — Connector Gateway/"Additional connectors" platform, no public ARM surface (see below) |
| Yammer | Microsoft Viva Engage | *(none)* | **Not implemented** — same (Connector Gateway) |
| Office 365 Outlook | Microsoft Outlook | `Outlook` | **Implemented** — live-verified (also listed under "Additional connectors" in the portal, but has its own dedicated wire value here, unlike the true Gateway connectors) |
| Microsoft Teams | Microsoft Teams | `Teams` | **Implemented** — live-verified (same note as Outlook) |
| MCP server (custom) | User provided connector | `Mcp` | **Implemented** — same as "MCP server" above, listed twice in the portal under different categories |
| Limn | Limn | *(none)* | **Not implemented** — no confirmed wire value |
| Engineering Hub | Engineering Hub | *(none)* | **Not implemented** — no confirmed wire value |
| GitHub (dedicated card) | — | *(none — reached via `Mcp --github true` instead)* | **Implemented indirectly** — this CLI's `Mcp --github true` convenience flag targets the built-in GitHub MCP server; unclear if it is wire-identical to this dedicated portal card |
| IcM connector | Microsoft IcM | `Icm` | **Implemented** — shape-confirmed; create blocked in this tenant by a real `InternalServerError` (not a CLI defect) |
| EV2 | Ev2 (ExpressV2) | `Ev2Mcp` | **Implemented** — schema/create-level verified |
| Database query connector (user) | Azure Data Explorer | `KustoUser` | **Implemented** — high-confidence correlation, not create-and-inspect confirmed |
| Database indexing connector | Azure Data Explorer | `KustoDataIndexer` | **Implemented** — same caveat |
| Documentation connector | Documentation | `Documentation` | **Implemented** — schema/create-level verified |
| Azure DevOps AI Search | Azure DevOps | `AzureDevOpsBuiltinMcp` | **Implemented** — high-confidence correlation, not create-and-inspect confirmed |
| Microsoft Security Copilot | Microsoft Security Copilot | *(none)* | **Not implemented** — Connector Gateway/"Additional connectors" platform |
| Notion | Notion | *(none)* | **Not implemented** — same |
| OneDrive for Business | Microsoft OneDrive | *(none)* | **Not implemented** — same |
| SharePoint | Microsoft SharePoint | *(none)* | **Not implemented** — same |
| Box | Box | *(none)* | **Not implemented** — same |
| Office 365 Users | Microsoft 365 | *(none)* | **Not implemented** — same |
| Power BI | Microsoft Power BI | *(none)* | **Not implemented** — same |
| Confluence | Atlassian Confluence | *(none)* | **Not implemented** — same |
| Planner | Microsoft Planner | *(none)* | **Not implemented** — same |
| OneNote (Business) | Microsoft OneNote | *(none)* | **Not implemented** — same |
| Microsoft Forms | Microsoft Forms | *(none)* | **Not implemented** — same |
| Google Sheets | Google Sheets | *(none)* | **Not implemented** — same |
| Trello | Trello | *(none)* | **Not implemented** — same |
| RSS | RSS | *(none)* | **Not implemented** — same |
| Microsoft To-Do (Business) | Microsoft To Do | *(none)* | **Not implemented** — same |
| Microsoft Bookings | Microsoft Bookings | *(none)* | **Not implemented** — same |
| MS Graph Users and Groups | Microsoft Graph | *(none)* | **Not implemented** — same |
| Google Drive | Google Drive | *(none)* | **Not implemented** — same |
| Dropbox | Dropbox | *(none)* | **Not implemented** — same |
| FTP | FTP | *(none)* | **Not implemented** — same |
| Excel Online (Business) | Microsoft Excel | *(none)* | **Not implemented** — same |
| Word Online (Business) | Microsoft Word | *(none)* | **Not implemented** — same |
| EV2 *(shown again under "Other")* | Ev2 (ExpressV2) | `Ev2Mcp` | **Implemented** — duplicate portal listing, same as above |
| Database query connector (user) *(shown again under "Other")* | Azure Data Explorer | `KustoUser` | **Implemented** — duplicate portal listing, same as above |
| Database indexing connector *(shown again under "Other")* | Azure Data Explorer | `KustoDataIndexer` | **Implemented** — duplicate portal listing, same as above |
| Documentation connector *(shown again under "Other")* | Documentation | `Documentation` | **Implemented** — duplicate portal listing, same as above |
| Azure DevOps AI Search *(shown again under "Other")* | Azure DevOps | `AzureDevOpsBuiltinMcp` | **Implemented** — duplicate portal listing, same as above |
| Azure Managed Grafana | Azure Managed Grafana | *(none)* | **Not implemented** — no confirmed wire value; do not assume `Mcp` + endpoint without backend confirmation |

Not shown as a connector card at all, but implemented in this CLI anyway
(reached via a separate noun, `sre knowledge`/`sre repo connect`, not
`sre connector` directly — confirmed absent from the portal's Connectors
picker):

| Wire value | CLI status |
|---|---|
| `KnowledgeText` | **Implemented** — live-verified via `sre knowledge create --type text` |
| `KnowledgeFile` | **Implemented** — live-verified via `sre knowledge create --type file`; known service-side echo gap (see table above) |
| `KnowledgeWebPage` | **Implemented** — live-verified via `sre knowledge create --type webpage` |
| `KnowledgeRepository` | **Implemented** — live-verified via `sre repo connect` |

Confirmed **implemented but with no confirmed portal picker card at all**
(backend-accepted, unlocked 2026-11-02, no matching portal UI entry found in
either individual screenshots or the full catalog export):

| Wire value | CLI status |
|---|---|
| `TsgCrawler` | **Implemented** — schema/create-level verified only |
| `ConnectorGateway` | **Implemented** — schema/create-level verified only; name collides with the separate "Connector Gateway" *platform* (see below), not the same thing |
| `AzureMonitor` | **Implemented** — schema/create-level verified only |
| `MonitorClient` | **Implemented** — schema/create-level verified only |

**"Implemented" above means accepted by this CLI's `--data-connector-type`
allowlist** (schema- or live-create-verified against the real backend, see
the per-type table earlier in this section for exact verification depth) —
it does **not** mean the CLI has a dedicated convenience flag for every type;
most just take raw `--data-source`/`--extended-properties` JSON.

### Connector Gateway: what this CLI can and can't reach

The agent genuinely integrates with Azure's real **Connector Namespace /
Connector Gateway** platform (`connectors.azure.com`) — confirmed by reading
`sreagent-runtime`'s own source (`ConnectorGatewayArmClient.cs`,
`ConnectorGatewayMcpSyncService.cs`, `ConnectorType.ts`), not assumed --
further confirmed 2026-11-05 by the platform's own dedicated management
portal at https://connectors.azure.com/ ("Connector Namespaces"), a
separate React SPA that authenticates via Entra ID and calls ARM directly
from the browser -- independent, out-of-band evidence that this is a real,
separately-managed first-party control plane, not something this CLI's
agent-scoped ARM surface can or should try to reach into. That
platform's catalog is much larger than the list above: 30+ managed
connectors (Jira, Slack, SharePoint, SQL Server, Key Vault, Service Bus,
Confluence, GitLab, GitHub, Azure DevOps, and more, each suffixed `*CG` in
the runtime's `ConnectorType` enum), each exposed to the agent as an MCP
tool once configured.

**None of those `*CG` connectors are reachable through the ARM control
plane this CLI talks to.** The 7 types in the table above (plus the 4
knowledge types) are the complete, confirmed set the real swagger/ARM-proxy
route accepts (`KnownDataConnectorTypes.cs`/`DataConnectorValidator.cs`).
The larger Connector Gateway catalog is wired up entirely through the
agent's own data-plane connector wizard in the portal — there is no public
ARM action to create, list, or manage a Connector-Gateway-backed connector
today. This is a real, confirmed platform boundary, not a CLI gap to be
fixed by renaming or adding more `--data-connector-type` values: adding
`Jira`/`Slack`/`SharePoint` etc. as CLI-accepted values today would
immediately fail server-side, because the ARM-exposed resource genuinely
doesn't support them yet. Revisit this once/if the Connector Gateway
control plane grows a public ARM surface.

**Confirmed authoritatively 2026-11-05** by Dalibor Kovacevic (SRE Agent
team) in response to a direct question: "yes they are a separate rp and a
separate thing we hook into so the resource is as you noted connector
gateway and they return some sort of tools payload we render." This
confirms, from the source team, exactly what the code pointed to: Connector
Gateway is a genuinely separate ARM **Resource Provider**, the agent
runtime calls into it, and it hands back a tools payload the agent renders
-- not something this CLI's `Microsoft.App/agents` surface owns or can
extend into. Bruce Moe, Jitin John, and Jack Pa were named as the SMEs for
deeper follow-up if/when `az`-level support for these connectors is
pursued.

### Connector authentication reference: who actually needs consent?

Captured 2026-11-05, in response to a question from Paul Yuknewicz about
when `connector create` actually requires a user to click through a consent
screen vs. just creating an ARM link that may or may not work. Answer: it
depends entirely on the connector's auth mechanism, which varies per type —
**not every connector needs consent, and the ones that don't still need an
RBAC grant to actually work** (see the "happy path" section in
`quickstart.md`). Sources: live portal wizard screenshots (Kusto, ICM, MCP)
plus source-level confirmation against `sreagent-runtime`
(`KustoClient.cs`, `McpDataConnector.cs`, `ICMAPIClient.cs`,
`DGrepPluginClient.cs`, `ConnectorGatewayArmClient.cs`,
`ExperimentalSettings.cs`) and
`docs/ImplementationSpecs/mcp-aad-oauth-github-v2-clone.md`.

| Connector type | Auth mechanism | Consent step? | Notes |
|---|---|---|---|
| `Kusto` / `KustoClient` | Agent's own managed identity (system- or user-assigned, per the connector's `identity` field) | **No** | RBAC-only. Live-verified this session: created ≠ working until the identity is granted a role (e.g. Viewer) on the target cluster/database. The portal wizard shows no auth picker at all for this type — it's implicit. |
| `Icm` | Fixed **platform-wide** service-managed identity (a single shared AME-tenant App ID, `a67bb1ee-091f-46eb-a5f3-d45f1aed9332` — confirmed via live portal wizard screenshot, not the agent's own identity) | **No** | RBAC-only, same shape as Kusto but the identity is shared across all agents/tenants, not per-agent. Portal explicitly states "Authentication via certificate is deprecated by ICM. Managed identity is the only supported authentication method" — confirms `IcmDataConnectorCertAuthService.cs`'s cert path is legacy/being phased out. |
| `Dgrep` | Managed identity or Key Vault certificate, scope `https://monitor.azure.com/` | **No** | RBAC/cert-only, not user-facing. |
| `Mcp` | One of 5 types set via `extendedProperties.authType` (confirmed in `McpDataConnector.cs`): `None`, `BearerToken` (static key/PAT), `OAuth` (per-user delegated token), `EntraOAuth` (feature-flagged **off** by default -- `EnableMcpEntraOAuth = false`), `SpecOAuth` (dynamic client registration / DCR) | **Depends on authType** -- `OAuth`/`SpecOAuth` yes, others no | **CLI flags added 2026-11-05**: `connector create --data-connector-type Mcp` now supports `--bearer-token`, `--managed-identity-auth`/`--mi-token-scope`, and `--oauth-dcr`/`--oauth-scopes`/`--oauth-client-name`, matching the real portal wizards 4 "Authentication method" choices -- no auth / static-token / managed identity / OAuth with Dynamic Client Registration (the DCR option is live today and is the one that shows a real "Authorize" browser redirect). All three were previously a real gap vs. the portal; now closed (schema/create-level verified, see custom.pys _ConnectorConvenienceArgsMixin). |
| `Outlook` / `Teams` | Unresolved from code alone — likely resolves through the separate Connector Gateway platform at runtime, possibly pre-consented at tenant/platform level | **Unconfirmed** | Live-tested this session: `Outlook` create fails with a real `(InternalServerError)` in this tenant (pre-existing, documented below); `Teams` create succeeds but its ARM resource shows `extendedProperties: null` and `identity: ""` — **zero auth/consent signal visible from the CLI or ARM**, so this CLI's consent-status annotation can never fire for it regardless of what's actually happening at runtime. Flagged as an open question for the SRE Agent product team, not resolved here. |
| Connector Gateway types (Jira, Slack, SharePoint, ServiceNow, Salesforce, "Engineering Hub", and 30+ others, each suffixed `*CG` in the runtime) | OAuth, always | **Yes, always** | Confirmed live: a real `login.microsoftonline.com/.../oauth2/v2.0/authorize` redirect was observed for an "Engineering Hub" connector. The lightweight `Microsoft.App/agents/connectors` ARM resource this CLI talks to is not the full picture for these — real config lives in a separate `Microsoft.Web/connectorGateways`/`connections` resource fetched via `ConnectorGatewayArmClient.cs`. None of these types are reachable through this CLI today (see Connector Gateway section above). |

**Practical takeaway for CLI users**: after `connector create` succeeds,
treat it as "ARM link created", not "agent can read data". For
`Kusto`/`KustoClient` (and likely `Icm`/`Dgrep`), the CLI now warns you
to grant RBAC (see `_connector_access_reminder()` in `custom.py`). For
`Mcp` with `OAuth`/`EntraOAuth`/`SpecOAuth`, use the existing
`_annotate_connector_consent_status()` output and the portal consent link
(for `SpecOAuth`, use the new `--oauth-dcr true` flag to create the
connector, then complete the browser consent in the portal).
For `Outlook`/`Teams`, there is currently no reliable signal either way —
verify by asking the agent to actually use the connector in chat.

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

**2026-11-02: expanded from 11 to 25 real backend types.** The CLI's
allowlist was stricter than the actual backend: the control plane
(`DataConnectorTypes.cs` in `sreagent-runtime`) accepts a `V1` list of 20
first-party built-in types, of which only 11 were previously exposed here.
All 14 missing `V1` types were confirmed live against a real agent (schema
accepted, same endpoint, no new backend work) and added:
`AppInsights`, `LogAnalytics`, `KustoUser`, `KustoDataIndexer`,
`TsgCrawler`, `Ev2Mcp`, `GenevaMetrics`, `S360`, `ConnectorGateway`,
`Documentation`, `AzureDevOpsBuiltinMcp`, `ApplicationInsights`,
`AzureMonitor`, `MonitorClient`. These were schema/create-level verified
only (fake placeholder data sources) — not confirmed to retrieve real data
end-to-end, except `GenevaMetrics` (see below). The remaining 26 `Managed`
API types (Box, Dropbox, GitLab, etc.) are intentionally **not** exposed:
they require a separately-provisioned `Microsoft.Web/connectorGateways`
Azure resource wired via `agent.spec.connectorGatewaySettings.resourceId`
— genuine infrastructure work, not a CLI allowlist fix.

**`GenevaMetrics` is gated to Microsoft-internal tenants**, matching the
real SRE Agent portal's own behavior. The portal's connector picker
(`ConnectorPicker.tsx`/`FirstPartyHelper.ts`) hides the Geneva/S360/DGrep/
Limn/EngHub cards entirely for non-first-party tenants; the CLI can't hide
`--help` text per-tenant, so it instead rejects client-side with a clear
`CLIError` before any ARM call when the signed-in tenant (resolved via
`az account show`) isn't one of Microsoft's 13 known first-party tenant
IDs (AME, Corp, PME, TORUS, MicrosoftHealthcareCloud, GME, MSFTGreen,
DevicesMFG, MPA, MPD, PKIHRE, TestTRS01, PCECloud — the exact same
allowlist the portal uses). In an allowed tenant, the request still goes
through normal backend validation (e.g. a `GenevaMetrics` connector also
needs `--extended-properties monitoringAccount=<account>`, and the service
genuinely validates that account exists — confirmed live, this is the only
one of the 14 new types verified against a real downstream auth check,
not just schema acceptance).

**Portal display names for the 14 newer types (confirmed 2026-11-03/04
against the real portal's "Connectors" picker dialog, via live screenshots
and a full catalog text export):**

| Wire value | Portal card name | Status |
| --- | --- | --- |
| `LogAnalytics` | "Log Analytics Workspace" | Confirmed — this is the card's **Title**; subtitle is "Log Analytics" |
| `Ev2Mcp` | "EV2" | Confirmed — Title; subtitle is "Ev2 (ExpressV2)" |
| `GenevaMetrics` | "Geneva Metrics" | Confirmed — Title; subtitle is "Geneva Metrics (MDM)" (gated, see above) |
| `S360` | "S360 connector" | Confirmed — Title; subtitle is "S360" |
| `Documentation` | "Documentation connector" | Confirmed — Title; subtitle is "Documentation" |
| `Mcp` | "MCP server" | **Corrected 2026-11-04**: the real Title is "MCP server" (subtitle "User provided connector"), not "Custom MCP" as previously (incorrectly) documented/coded — "Custom MCP" does not appear anywhere in the real catalog |
| `Icm` | "IcM connector" | **Corrected 2026-11-04**: the real Title is "IcM connector" (subtitle "Microsoft IcM") — previously had Title/subtitle swapped |
| `Dgrep` | "DGrep" | **Corrected 2026-11-04**: the real Title is "DGrep" (subtitle "Microsoft DGrep") — previously had Title/subtitle swapped |
| `AppInsights` / `ApplicationInsights` | "Application Insights" | **Ambiguous**: the portal shows exactly one "Application Insights" card, but the backend accepts two distinct wire values. Which one the portal card actually persists as has not been confirmed by a create-and-inspect test — do not assume either is "the" correct one until verified. |
| `KustoUser` | "Database query connector (user)" *(high-confidence, unconfirmed)* | Subtitle "Azure Data Explorer"; description "Query Azure Data Explorer using your own identity via OAuth sign-in" matches the wire value's name/purpose closely, but no create-and-inspect test has confirmed the mapping |
| `KustoDataIndexer` | "Database indexing connector" *(high-confidence, unconfirmed)* | Subtitle "Azure Data Explorer"; description "The agent generates queries by learning about your logs, telemetry, and time series data" matches closely, same caveat as above |
| `AzureDevOpsBuiltinMcp` | "Azure DevOps AI Search" *(high-confidence, unconfirmed)* | Subtitle "Azure DevOps"; description "AI-powered remote code search across Azure DevOps repositories without local cloning" matches closely, same caveat as above |
| `TsgCrawler` | *(none)* | Confirmed **not** present as a picker card (empty search, and absent from the full catalog export) |
| `ConnectorGateway` | *(none)* | Confirmed **not** present as a picker card — consistent with it needing separate `Microsoft.Web/connectorGateways` infrastructure, not a direct picker entry |
| `AzureMonitor` / `MonitorClient` | *(none)* | Confirmed **not** present as their own cards anywhere in the full catalog — no "Azure Monitor" card exists; Azure Monitor's constituent signals are reached via the dedicated Log Analytics Workspace / Application Insights cards instead |

The 4 `Knowledge*` types were also confirmed **not** reachable through this
same "Connectors" picker dialog at all (empty search for `KnowledgeText`) —
they live in a different portal section, consistent with this CLI exposing
them through the separate `sre knowledge` noun rather than `sre connector`.

`CONNECTOR_TYPE_PORTAL_NAMES` in `custom.py` (used by `-o table` on
`connector list`/`show`, see "Data connectors" section above) and the
`--data-connector-type` help text were both updated 2026-11-04 to reflect
the Title-vs-subtitle corrections above plus the 3 new high-confidence
(but unconfirmed) entries. The ambiguous `AppInsights`/`ApplicationInsights`
pair and the types with no portal card are intentionally left unmapped —
they continue to show their raw wire value in `-o table` rather than guess.

#### Full portal connector catalog (reference, captured 2026-11-04)

The user captured the **complete** list of connector cards shown in the real
SRE Agent portal's connector picker (via a full-page text export), confirming
every mapping above and also surfacing several cards with **no corresponding
wire value anywhere in this CLI's `DATA_CONNECTOR_TYPES` allowlist** — a
genuine coverage gap, not yet added to code because their wire values are
unconfirmed (per the established verification methodology, nothing is added
to `DATA_CONNECTOR_TYPES` without backend source or live-create confirmation):

- **Azure Managed Grafana** — "Query dashboards, datasources, alerts, and
  metrics from an Azure Managed Grafana instance over its native MCP
  endpoint using the agent's managed identity."
- **Datadog** — "Connect to Datadog for monitoring, alerting, and
  observability data."
- **Elasticsearch** — "Connect to Elasticsearch for search, analytics, and
  log management."
- **Dynatrace** — "Connect to Dynatrace for application performance
  monitoring and observability."
- **New Relic** — "Connect to New Relic for application performance
  monitoring and analytics."
- **Splunk** — "Connect to Splunk for search, monitoring, and analysis of
  machine data."
- **Hawkeye (NeuBird)** — "Connect to Hawkeye by NeuBird for AI-powered
  observability and incident management."
- **Limn** — "Connect to Limn MCP server."
- **Engineering Hub** — "Connect to the Engineering Hub MCP server."
- **GitHub** (dedicated card, distinct from the generic MCP server type) —
  "The agent accesses GitHub repositories, features, and actions, including
  issue tracking and pull requests."

**This casts doubt on the existing claim** (in `custom.py`'s help text and
the `_ConnectorGroup` docstring) that Datadog/Splunk/S360/EV2/etc. are all
reached via the generic `Mcp` type, "differentiated by endpoint, not a
separate type." `S360` and `Ev2Mcp` turned out to be **dedicated wire
types**, not `Mcp` + a known endpoint — the same may well be true for
Datadog, Splunk, Grafana, and the others above. **Do not guess wire values
for these** — before adding anything, check `sreagent-runtime`'s
`DataConnectorTypes.cs` / `AgentExtensionsApiService.GetExtensionTypes()`,
or live-probe a real agent, following the same methodology used for the
2026-11-02 14-type expansion.

The large **"Additional connectors"** block in the same export (Gmail,
Yammer, Office 365 Outlook, Microsoft Teams, OneDrive for Business,
SharePoint, Box, Power BI, Confluence, Planner, OneNote, Microsoft Forms,
Google Sheets/Drive, Trello, RSS, Microsoft To-Do, Dropbox, FTP, Excel
Online, Word Online, etc. — almost all marked "Preview") matches the
already-documented `ConnectorGateway`/26-"Managed API type" story above —
**consistent**, no new gap there. Note that `Outlook`/`Teams` already have
their own dedicated, non-Preview, non-Gateway wire values in this CLI
(confirmed live-verified in the table above) — they also happen to appear
in this "Additional connectors" list, which is a portal UI grouping
decision, not evidence they route through Connector Gateway.

The raw export also included "Telemetry / Notification / MCP / Incidents /
Deployment / Other" — these are portal **category filter tabs**, not
connectors, and are correctly excluded from all analysis above.

**FIXED** (was: cosmetic, non-blocking noise on `connector create`/
`knowledge create`): an `ERROR: Operation returned an invalid status 'Not
Found'` line used to print to stderr on a successful first-time create, even
though the command still exited `0` with the correct created resource in its
JSON output. Root cause (confirmed this session, not the generated AAZ
poller as previously suspected): `connector create`'s pre-create existence
guard used to call `_cli_invoke(..., "connector", "show", ..., allow_missing
=True)`, which runs a *full* in-process `az sre connector show` via Azure
CLI's own `cli.invoke()`. On the common path of creating a brand-new
connector, that inner `show` genuinely 404s, and `cli.invoke()` logs the
error to stderr via its own global exception handler before returning
control to the caller — regardless of `allow_missing=True` silently
swallowing it afterward. Fixed by switching the guard to a direct, silent
raw ARM GET via `_arm_request(..., missing_ok=True)` (the same helper the
generic extension-type create/show/list/delete facade already uses for this
exact check), which goes straight through `send_raw_request` and never
touches `cli.invoke()`'s logger — a 404 on a brand-new name no longer prints
anything, while the duplicate-name guard itself still works exactly as
before.


## Runbook extension payload shapes

Every extension type is backed by a data-plane proxy resource with **no ARM
Swagger** — every payload shape had to be confirmed by live probing, not by
reading a spec. There is no longer a generic `az sre extension` escape
hatch: every extension type now has a dedicated front-door noun (`tool`,
`skill`, `hook`, `instructions`, `knowledge`, `repo connect`,
`plugin marketplace`/`plugin install`, `agent settings`, `automation
scheduled-task`/`http-trigger`, `response-plan`). The one remaining
generic command group, `az sre managed-resource`, is unrelated RBAC
plumbing, not an extension-type front door. Status as of the last
live-verification pass (12 of 15 extension types confirmed live):

| Extension type | Confirmed shape | Status |
| --- | --- | --- |
| `commonPrompts` (`instructions`) | `{"prompt": "<string>"}`, one prompt per ARM resource name (e.g. `commonPrompts/default`) | Live-verified |
| `globalSettings` (`agent settings`) | `{}` plus optional `toolPermissions`/`toolStatuses`/`skillStatuses`/`customInstructions`/`approvalExpirationSetting` | Shape-confirmed from the control-plane team's own integration tests — true ARM singleton, `DELETE` unsupported, reset via `agent settings update --value '{}'` |
| `pluginMarketplaces` (`plugin marketplace`), `pluginInstallations` (`plugin install`) | See `PLAN.md` | Create/show live-verified; K8s-backed install provisioning not exercised in this sandbox |
| `tools` (`tool`), `skills` (`skill`), `hooks` (`hook`), `repositories` (`repo connect`) | Confirmed | Live-verified end to end (PUT + GET round-trip against a real agent) |
| `incidentFilters` (`response-plan`), `incidentHandlers` (`response-plan`) | Filter: `{name,type:"IncidentFilter",properties:{...}}`; handler: flat JSON with `id` | Filter operations use ARM, including enable/disable; linked handler operations use the agent's v2 API because the deployed ARM handler proxy returns 404. Read back both halves when verifying a plan; configuration persistence alone does not prove real alert ingestion. |
| `githubAuths`, `azureDevOpsAuths` (both wired up for you by `repo connect`) | Shape-confirmed from authoritative source | Live-create rejected by real credential/token validation on the service side, not a shape defect |
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

### `hook.matcher` is effectively required for `PreToolUse`/`PostToolUse`

Live-confirmed this session (cold-start grading exercise finding #7): an
otherwise fully-valid hook payload for `eventType: "PreToolUse"` or
`"PostToolUse"` is rejected by the real API with the same opaque `"The
extension configuration is invalid"` error when `hook.matcher` (a tool-name
regex, e.g. `"Bash.*"`) is missing — adding only that one field makes the
identical payload succeed. `Start`/`Stop` hooks (not scoped to a specific
tool call) do **not** need `matcher` — confirmed accepted without it. The
CLI's client-side validator now requires `matcher` for `PreToolUse`/
`PostToolUse` hooks, and `az sre hook create --help` shows two full,
live-verified example payloads (one `prompt`-type, one `command`-type) so
this shape is no longer guessable-only from prose.

**PowerShell note**: `az.cmd` on Windows mangles `--value '{"..."}'` JSON
passed directly in PowerShell (quotes get eaten, and shell metacharacters
like `&&` inside a `command` field get interpreted by cmd.exe before the
JSON reaches the CLI). Reliable options: write the JSON to a file and pass
`--value (Get-Content hook.json -Raw)`, or invoke via `subprocess.run([...],
shell=False)` in Python. Avoid `&&`/`|`/`<`/`>` inside a hook's `command`
field value on Windows for the same reason.

```bash
az sre agent settings update -g myrg --agent-name myagent --value '{}'

az sre agent settings show -g myrg --agent-name myagent
```

### `globalSettings.toolPermissions` is all-or-nothing once present

Live-confirmed this session (independent-agent usability evaluation,
QuickStart re-run): `az sre agent settings update --value '{}'` succeeds,
but `--value '{"toolPermissions":{"deny":["restart*"]}}'` — a partial
`toolPermissions` object with only `deny` set, exactly as the quickstart
previously showed — is rejected by the real API with `"request is invalid.
The request body contains an invalid or unrecognized property."` Isolated
by testing with and without the sibling `allow`/`ask` keys against a real
agent: the real cause is a **missing** sibling property, not an
"unrecognized" one, despite what the error text says. Once `toolPermissions`
is specified at all, the real API requires all three of `allow`/`ask`/`deny`
(each can be an empty array). The CLI's client-side validator now catches
this and names the missing key(s) instead of surfacing that misleading 400,
and `docs/quickstart.md`'s own example was fixed to include all three keys.

See [docs/testing.md](testing.md#live-verification-workflow) for the
round-trip (PUT then GET) technique used to confirm a shape, and why
checking only for a 200 response is not sufficient proof.

### `sre network update`'s output used to return the entire parent agent object

Live-confirmed this session (independent-agent usability evaluation):
unlike every other `create`/`update` command in this CLI, which returns
only its own scoped sub-resource, `network update` returned the *entire*
parent `Microsoft.App/agents` resource (every property, including dozens of
unrelated `null` fields) because the underlying call is a PUT directly on
the agent resource itself (there's no separate ARM child resource for
networking). Fixed to trim the response to `id`/`name`/`resourceGroup`/
`type`/`provisioningState`/`vnetConfiguration`/`sandboxConfiguration` only,
matching the output shape convention used everywhere else.

### `sre agent list-models --output table` used to show only a concatenated name

Live-confirmed this session (independent-agent usability evaluation): the
raw item shape is `{id, name, properties: {provider, model, ...}}`, where
the top-level `name` is a single concatenated string like
`"Anthropic-Automatic"` — not directly reusable as the two separate
`provider`/`name` fields `--default-model` actually takes (e.g.
`--default-model "{provider:Anthropic,name:Automatic}"`). Fixed to flatten
`properties.provider`/`properties.model` to top-level `provider`/`name`
columns that match `--default-model`'s own input shape 1:1.

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
  `LinkTool`, `PythonFunctionTool`, `HttpClientTool`), not `toolType`.
- `PythonTool` remains accepted as a legacy CLI alias. The CLI normalizes it
  to `PythonFunctionTool` before encoding the request; the runtime rejects
  the old discriminator. Executable code and the other configuration fields
  are preserved.
- `LinkTool`'s link field is **`template`**, not `url`. `url` is a real
  field, but only on `HttpClientTool`.

```bash
az sre tool create -g myrg --agent-name myagent -n my-link-tool --value \
  '{"type": "LinkTool", "name": "my-link-tool", "description": "Opens the docs",
    "template": "https://example.com/docs"}'
```

The CLI's `_validate_tools_shape` client-side validator already enforced
the correct `type`/`template` fields; only the `--value` help text's
example was stale and contradicted it. Fixed so the documented example
now matches the validator and the real API.

### `globalSettings.toolStatuses` is accepted but doesn't round-trip; `toolPermissions`/`approvalExpirationSetting` do

Live-verified all three `globalSettings` fields on `mytestagent` via
`az sre agent settings update`:

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
built-in tools via `az sre agent settings update` is unreliable today**;
use the portal's Built-in tools tab for that until confirmed fixed
server-side.

### `repo connect` fixes: stale `--repo-type` example, misleading GitLab claim, and a real PAT-leak bug

Three issues found while live-testing `az sre repo connect`:

1. **Stale example**: `_help.py`'s example used `--repo-type GitHub`, a flag
   that doesn't exist -- the real flag is `--provider`. Fixed.
2. **Misleading docstring**: `_RepoGroup` claimed "Supports GitHub, Azure
   DevOps, and GitLab", but `repo connect`'s `--provider` enum only allows
   `GitHub`/`AzureDevOps` -- GitLab isn't wired up for this one-step
   command, and (since the generic `extension` command group was removed)
   there is no longer any CLI path at all to create a `repositories`
   extension for GitLab. Docstring corrected to be precise about the gap.
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

### `repo connect` no longer hard-depends on the `gh` CLI (GitHub OAuth Device Flow)

Paul (SRE Agent team) researched and proposed this fix after flagging that
`repo connect`'s GitHub path used to call `gh auth token` directly -- if a
user didn't have the `gh` CLI installed and logged in, the command just
failed outright. That's not acceptable for an `az` extension to depend on a
separate third-party tool for a core flow.

Fixed with the same no-hard-dependency pattern `az staticwebapp`,
`az containerapp github-action`, and `az functionapp deployment
github-actions` already use -- `_github_token()` tries, in order:

1. **Explicit/CI**: `--github-token`, or `GITHUB_TOKEN`/`GH_TOKEN` env vars.
   This remains required for any non-interactive use (CI/CD pipelines,
   scheduled jobs, headless containers) -- device flow needs a human in a
   browser, so it can never substitute for this tier.
2. **Native GitHub OAuth Device Flow (RFC 8628)** fallback, implemented
   directly in Python with `requests` + Azure CLI's own
   `azure.cli.core.util.open_page_in_browser` -- no `gh` CLI, no client
   secret needed (device-flow apps are public clients by design). Posts to
   `https://github.com/login/device/code`, logs the `user_code` via the
   CLI's standard `logger.warning()` (not a bare `print()`, so it respects
   `--only-show-errors` and never pollutes `--query`/`-o json` output),
   opens `verification_uri` in the browser, then polls
   `https://github.com/login/oauth/access_token` until authorized.

An earlier version of this fix had a middle tier that opportunistically
reused an installed, already-logged-in `gh` CLI's token (via `gh auth
token`) for a zero-prompt experience. Dropped after team feedback (Paul/
Preeti, 2026-11-04): a dual-mode token source (gh vs. device flow) adds
environment-dependent ambiguity -- which path actually ran becomes a
guessing game -- with no real benefit once the device flow alone already
removes the hard `gh` dependency. Two tiers only, now.

**Which OAuth App client ID is used, and why:** `_github_device_flow()`
sends GitHub a `client_id` of `8d8e1f6000648c575489` -- the same public,
already-registered client ID Azure CLI's own `az containerapp
github-action add --login-with-github` uses (confirmed directly from
`azure-cli`'s own source,
`command_modules/containerapp/_github_oauth.py`). Reused deliberately
("steal what's tried and true" -- Paul, 2026-11-04) instead of registering
a new one. On GitHub's real consent screen this client ID displays as
**"Azure CLI" by "AzureAppServiceCLI"** (confirmed live, 2026-11-04 --
earlier notes in this doc assumed it would show "Azure Container Apps";
that was wrong, GitHub's actual registered app name is the more generic
"Azure CLI"). That label is accurate for this use case too, since `az sre
repo connect` is itself an Azure CLI extension command.

Deliberately **not** replicated from `az containerapp`: its encrypted,
on-disk token cache (`github_token_cache`, Windows DPAPI). `repo connect`
is a one-time setup per repo, not a repeatedly-invoked command like
`github-action add`, so there is nothing worth caching -- and therefore
nothing that needs encrypting, since the token is only ever held in memory
for the single API call it's used for, then cleared (`token = None`)
before the command returns.

Live-verified end to end (2026-11-04) in two independent runs against a
real agent (`mytestagent`/`ckamasani-publishtest`):

- Standalone test of `_github_device_flow()` directly: produced a real
  device code, user approved in browser, returned a real `gho_...` access
  token -- confirming the device-flow mechanism works with `gh` entirely
  absent from `PATH`.
- A full, later `repo connect` run performed independently by the user in
  their own terminal: printed a device code, browser flow through GitHub's
  real "Authorize Azure CLI" consent screen (as `charan-kamasani`),
  "Confirm access" 2FA step, and GitHub's "Congratulations, you're all
  set!" success page -- then successfully created the `githubAuths` and
  `repositories` extension resources on the agent, with the PAT correctly
  redacted (`"pat": "******"`) in the command's own output.

248 unit tests passing after the two-tier simplification (down from an
earlier 250 with the dropped `gh`-reuse-specific test cases removed). The
rest of this extension was also audited for similar dependencies: the
Azure DevOps PAT path (`_devops_pat_token`) was already dependency-free
(calls the vssps REST API directly, no `az devops` extension needed), and
`requests` is a hard transitive dependency of `azure-cli-core` itself, not
something this extension adds.

```bash
# No token needed up front -- opens a browser-based device-flow prompt
# automatically if no token is already available:
az sre repo connect --agent-name myagent --resource-group myrg \
  --repo-url https://github.com/contoso/my-service

# Or pass a token explicitly (required in CI, where no browser is
# available -- device flow cannot run unattended):
az sre repo connect --agent-name myagent --resource-group myrg \
  --repo-url https://github.com/contoso/my-service --github-token $env:GITHUB_TOKEN
```

### `az sre automation`: group for scheduled tasks, HTTP triggers, and incident filters

Renamed from `workflow` to `automation` (2026-10-30) to match the portal's
own top-level naming: the portal's "Automation" tab holds Scheduled tasks
and HTTP triggers, while its separate "Workflows" heading is unrelated and
currently only holds Agent Canvas -- confirmed directly by the SRE Agent
product team during shape review. See `docs/shape-design.md` for the
earlier open-question note (Paul's feedback point #8), now resolved.

The portal's "Automation" tab exposes four things: Scheduled tasks, HTTP
triggers, Subagents, and Incident filters/handlers. All four turned out to
already be generic `az sre extension` resource types (`scheduledTasks`,
`httpTriggers`, `subagents`, `incidentFilters`/`incidentHandlers`),
confirmed by reading
`AgentExtensionsApiServiceExtensionTypesTests.cs`'s
type-name-to-C#-model table in `AAPT-SREAgent-ControlPlane`.

Noun-specific commands include:

- `az sre automation scheduled-task create/show/list/delete` -- run the
  agent on a cron schedule against a prompt.
- `az sre automation http-trigger create/show/list/delete` -- run the
  agent from an inbound webhook call.
- `az sre response-plan create/show/list/delete/enable/disable` -- match
  incoming incidents (by platform/title/team/etc.) and route matches to
  a handling agent (portal: Incidents > "Triggers & response plans", a
  separate top-level nav item from Automation).
  The plan is an incident filter plus an optional handler (instructions)
  linked through `incidentFilterId`; `--instructions` writes the handler.

Scheduled task and HTTP trigger were live-verified end-to-end against
`mytestagent`: created via CLI, confirmed showing up correctly in the
portal's Automation tab (status, type, and for HTTP triggers the real
`triggerUrl`), then deleted via CLI and confirmed gone from the portal.

Incident filter create, update, show, list and delete use the ARM extension
routes, as do `enable` and `disable`. On the generic ARM validation error,
filter creation replays the request on the agent data plane to surface the
real reason. `--agent-url` reads use the data plane.

Linked instructions are managed through the agent's v2 incident-handler API
for create, read, update and delete. The deployed ARM `incidentHandlers`
collection returns 404 even when the filter exists, so using that proxy can
leave a partially created response plan and break its default `show`.
The CLI does not use the ARM handler proxy:

- `/api/v2/incidentManagement/incidentFilters[/{name}]`
- `/api/v2/extendedAgent/incidentHandlers[/{id}]`

The CLI resolves `properties.agentEndpoint` through ARM, then requests a
token for `https://azuresre.dev`. The caller needs the appropriate SRE Agent
data-plane role as well as ARM read access. Filter lists return a `value`
collection; handler lists return an array.

Earlier filter ARM requests returned "The extension configuration is invalid".
Live testing showed the filter ARM routes work. The failures came from agents with
no incident platform configured, or a `handlingAgent` that did not exist, with
ARM collapsing the downstream reason into the generic message. On an agent
with Azure Monitor configured, the filter ARM operations succeeded.
A handler's `incidentFilterId` is the filter name; its own `id` can differ.
Remaining control-plane bug: some downstream validation errors are still
masked by the generic message, which is why create replays on the data plane.

Configure `incidentManagementConfiguration.type` to match the filter's
`incidentPlatform` first. For Azure Monitor, PagerDuty, and ServiceNow,
set `handlingAgent` to an existing subagent name. The plural
`handlingAgents` field is IcM-specific. Both create commands refuse to
replace existing resources unless `--overwrite` is supplied.
Creating and reading configuration does not prove that a real alert has
triggered an investigation; that requires a separate incident-flow test.

**Intentionally not wrapped (yet):**
- `subagents` -- **confirmed not buildable this way**: the portal's real
  "Create a custom agent" dialog bypasses the ARM extensions proxy
  entirely. Switching its UI to YAML view shows it PUTs a raw
  `kubectl apply`-style YAML document (`kind: AgentConfiguration`,
  snake_case fields like `system_prompt`/`agent_type`) directly to
  `sreagent-runtime`'s `Agent.Web` `PUT api/v1/extendedAgent/apply` --
  a data-plane-only endpoint this ARM-only CLI never reaches. A live
  test confirmed `az sre extension create --extension-type subagents`
  *does* reach the data plane (via the ARM-proxied `ExtendedAgentView`
  v2 route), but is rejected -- consistent with that being the wrong,
  unsupported schema for subagent creation. Use the portal or `srectl`
  to create subagents instead; this is permanently out of scope for
  `az sre automation`, not merely deferred.

**Confirmed out of scope entirely (not ARM resources):** the portal's
Release triggers, S360 triggers, and Incident Retrospective Response
Plans are data-plane-only features of the agent's own runtime --
confirmed via `sreagent-runtime`'s `Agent.Web` v1 controllers
(`ReleaseTriggerController`, `S360Controller`) and the absence of any
matching type in `AAPT-SREAgent-ControlPlane`'s extension-type table.
`release-trigger` already has its own first-party CLI support in
`srectl` (`Agent.Cli`'s `CommandBuilder.ReleaseTrigger.cs`), which talks
to the data plane directly -- this ARM-based control-plane CLI
correctly does not and should not add equivalents for any of these three.

```bash
az sre automation scheduled-task create -g myrg --agent-name myagent \
  -n daily-digest --value '{"cronExpression":"0 9 * * 1-5","agentPrompt":"Summarize overnight alerts"}'

az sre automation http-trigger create -g myrg --agent-name myagent \
  -n alert-webhook --value '{"agentPrompt":"Investigate the attached alert payload"}'

az sre response-plan create -g myrg --agent-name myagent -n disk-space \
  --platform AzMonitor --subagent storage-oncall-agent --title-contains "disk space" \
  --mode review --disabled --instructions "Gather disk-usage evidence and report findings."
```

## Networking

See [docs/networking.md](networking.md) for VNet injection and sandbox
egress configuration via `network update`.

## Windows PowerShell: JSON quoting

Live-verified during a cold-start grading pass of the quickstart on Windows:
bash-style `--value '{"key": "value"}'` quoting (single-quoted string
containing literal, unescaped double quotes) does **not** survive
`powershell.exe`/`pwsh` invoking `az` (which is `az.cmd`, a batch-wrapped
executable). The embedded `"` characters get re-tokenized on the way to the
native command line, producing either:

- `ERROR: unrecognized arguments: ...` (argument got split on whitespace
  inside the JSON), or
- `--value must be a JSON document... Expecting property name enclosed in
  double quotes` (the JSON arrived with its quotes stripped).

This reproduces identically regardless of spaces around `:` or any
particular character inside the string — it is PowerShell's general handling
of embedded `"` in a single-quoted argument being passed to a `.cmd`-wrapped
executable, not specific to any one flag or payload. It affects every Azure
CLI command that takes inline JSON, not just `az sre`.

**Fix: escape the inner double quotes with a backslash, keep the outer
single quotes:**

```powershell
# Fails on Windows PowerShell:
az sre instructions create -g myrg --agent-name myagent --name default `
  --value '{"prompt": "Escalate before restarting."}'

# Works on Windows PowerShell:
az sre instructions create -g myrg --agent-name myagent --name default `
  --value '{\"prompt\":\"Escalate before restarting.\"}'
```

Bash/zsh users are unaffected and can keep using the unescaped form shown
throughout this guide and the quickstart.

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

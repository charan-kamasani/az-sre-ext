# Azure SRE Agent CLI plan

Status: Control-plane prerequisites (agent lifecycle, identity, RBAC,
connectors, networking, runbook-extension mechanics) are built, unit-tested,
and live-verified. Priority 1 — making threads/incidents actually usable from
a terminal — has not started; it is blocked on two open design decisions, not
on missing access or code (see Decisions below).

## Scope: control plane vs. data plane

Per guidance from Paul (2026-10-21): this is **not** a port of the Azure
portal into a CLI. The portal is a reference, not the spec — some things the
CLI needs aren't in the portal (networking, identity), and some things the
portal has, this CLI deliberately does not replicate ("live mode", full
visual runbook authoring). The job to be done: **make threads and incidents
actually usable from a terminal** — creating an empty resource is not the
hard part, creating a useful agent is.

### Control plane (`az sre` — ARM-authenticated, what this CLI builds)

| Feature | Status | Blocker | Next step |
|---|---|---|---|
| Agent CRUD (create/show/list/update/delete/start/stop/wait) | Done | None | Live-verified end-to-end against a real resource. All `agent create`/`agent update` Properties/Identity args (`--action-configuration`, `--knowledge-graph-configuration`, `--log-configuration`, `--incident-management-configuration`, `--tags`, `--upgrade-channel`, `--mi-system-assigned`/`--mi-user-assigned`) live-verified this pass against real resources (disposable App Insights + user-assigned identity); `--agent-identity` not independently tested (needs a real tenant AAD sponsor group ID, out of scope). Found and fixed a real create-time bug (service requires a managed identity; CLI now defaults to `--mi-system-assigned` with a warning instead of failing with a raw ARM error) and a Swagger/service `--action-configuration` mode enum mismatch (`ReadOnly` is rejected live; the CLI now rejects it client-side with a clear error), and documented one real, non-CLI-fixable finding: a `--log-configuration` + `identity assign`/`remove` GET-merge-PUT interaction bug (write-only `connectionString` lost on merge). See docs/operations.md. |
| `endpoint show` (was `connection show`) / `usage list` | Done | None | Live-verified. Found and fixed a real bug this pass: `dataPlaneAudience` rendered as `{"isDefault": true}` instead of the URL string when left at its default (a `knack.validators.DefaultStr` subclass leaking through az's output formatter); fixed with an explicit `str(...)` coercion. Renamed from `connection show` to `endpoint show` per live naming feedback (too visually similar to `connector`). See docs/operations.md. |
| Identity (`--system-assigned`/`--user-assigned`) | Done | None | Live-verified against a real managed identity. |
| RBAC (`access grant --role admin\|user\|author\|reader`) | Done | None | Live-verified; a real role-name-mapping bug (wrong role names, not matching Azure's actual built-ins) was found and fixed this session, now locked in with a regression test. |
| Connectors (Kusto/Mcp/Outlook/Teams/Icm/KustoClient/Dgrep/Knowledge* CRUD) | 9 of 11 `--data-connector-type` values live-verified; friendly product names (Azure Data Explorer, Custom MCP, Office 365 Outlook, Microsoft Teams, Microsoft IcM, Microsoft DGrep) now accepted as aliases, confirmed against sreagent-runtime's own portal i18n strings | `Outlook`/`Dgrep` rejected by real server-side checks in this tenant (`InternalServerError` / "MDS endpoint is not approved"), not a CLI/shape defect | Re-verify `Outlook`/`Dgrep` once a tenant known to support them is available. See docs/operations.md for the full per-type table; a real `KnowledgeWebPage` bug (CLI was sending `--data-source` + `extended-properties` together, causing a 500) was found and fixed this pass. Per Paul's shape-review feedback (point 3/4): confirmed by reading sreagent-runtime source that the agent genuinely integrates with the real Connector Namespace/Connector Gateway platform, but none of its 30+ `*CG` managed connectors (Jira/Slack/SharePoint/etc.) are reachable through this ARM control plane today — a real platform boundary, documented in docs/operations.md, not something to paper over by adding more `--data-connector-type` values that would fail server-side. |
| Networking (`network update`, vnet/sandbox) | Done | None | Hand-written (not generated — no public Swagger exists for the real deployed api-version `2026-11-01-preview` yet) GET-merge-PUT that preserves unrelated properties. Unit-tested and live-verified end-to-end against a real agent (`sre-network-verify`; see docs/networking.md). |
| Runbook extensions — mechanism (routing/auth/base64 envelope) | Done | None | Real ARM-proxy routes confirmed (`.../agents/{name}/{extensionType}[/{name}]`), 15 extension types total. Full CRUD built and unit-tested; the 400/500s hit while probing proved it genuinely reaches the data-plane cluster, not a dead route. |
| Runbook extensions — 12 of 15 types (`tools`, `skills`, `commonPrompts`, `hooks`, `pluginMarketplaces`, `pluginInstallations`, `repositories`) | Done | None | Live-verified end-to-end (PUT + GET round-trip against a real agent), each promoted to its own dedicated top-level noun (`tool`, `skill`, `instructions`, `hook`, `plugin marketplace`/`plugin install`, `repo connect`). |
| Runbook extensions — `incidentFilters`/`incidentHandlers`/`githubAuths`/`azureDevOpsAuths` | Shape-confirmed, live-create blocked | Sandbox lacks real IcM team-identity resolution / real auth credentials, not a shape defect | Re-verify once a tenant with real credentials/IcM team identity is available. |
| Runbook extensions — `subagents`/`scheduledTasks` | Permanently out of scope | These 2 types require an "approve" data-action claim that ARM only forwards for portal-originated sessions — confirmed both in the control-plane service's own test comments and independently by the official Microsoft Learn doc (`learn.microsoft.com/azure/sre-agent/create-subagent`), which documents subagent authoring as Agent-Canvas/portal-only with no public REST/CLI path | No CLI fix exists for this; it's a deliberate platform boundary, not missing code. Per Paul's guidance, not chasing a workaround — formally closed rather than carried as a backlog item. Still reachable via the generic `extension` noun if the gating is ever lifted server-side. |
| `--data-connector-type` enum validation | Done | None | Implemented via `_DataConnectorTypeArgMixin`, mirroring the `--model-provider` fix exactly: case-insensitive validation/normalization of `kusto`/`mcp`/`outlook`/`teams`, `CLIError` on invalid input, unit-tested (`test_custom.py`). This row was stale — the fix had already landed. |
| Stale generic `Reader` role assignment cleanup | Done | None | Checked live against `mytestagent`'s scope and the `ckamasani-publishtest` resource group: no generic ARM `Reader` assignment remains, only the correct `SRE Agent Standard User` assignment. Nothing to clean up. |
| Repo + CI/CD infrastructure | Done | None | Code lives in `charan-kamasani/az-sre-ext` (private). Minimal GitHub Actions CI (install deps → run unit tests → build wheel) runs green on every push. 188+ unit tests, offline/mocked. |

### Data plane (`sre.azure.com` — agent runtime, NOT touched by `az sre`)

| Feature | Status | Blocker | Next step |
|---|---|---|---|
| Threads & Incidents chat UI (Priority 1 — the actual job) | Not started | Depends on all control-plane prerequisites above (done). Open design decision: **read-write vs. read-only access model per role**, gated by client-authorization checks | Needs a decision from Paul before building starts — not an access or code problem. |
| Connector consent flow (first-time auth) | Investigated, closed as not CLI-fixable | The control plane has no public ARM action to initiate/complete OAuth consent (confirmed: no `getLoginLinks`-style operation exists anywhere in the SRE Agent control-plane source) | CLI now detects `consentStatus=PendingConsent` and surfaces a direct Azure Portal deep link via `connector show`/`list`/`create`/`update`. No further CLI work possible until the service adds a public consent-initiation action. |
| Per-extension-type payload schema (field-level shapes for all 15 types) | 14 of 15 confirmed from authoritative source; 12 of 15 live-verified end-to-end (PUT+GET round trip) against a real agent | `subagents` has no model file anywhere in the runtime source; believed server-managed/non-CLI-creatable | No further action planned unless a `subagents` model surfaces in a future source pull. |
| Repo (code context for investigations) | Confirmed data-plane only, not something this CLI builds | N/A — architectural, not a gap | Confirmed via spec: `PUT /api/v2/repos/{repoName}` lives entirely on the agent's own data-plane endpoint. |
| Context categories observed in the portal (Code/Logs/Deployments/Incidents/Azure resources/Knowledge files/S360) | Observed only, intentionally not built | N/A — exactly the kind of portal-parity surface Paul's guidance says to skip | Informational only — confirmed our RBAC roles are mapped correctly (reaching the real data-plane UI). No CLI work planned. |

## Implementation progress

- Scope decision (2026-11-06): `az sre` is control-plane only. The data-plane
  `thread` and `incident` groups were removed; the last version is preserved at
  git tag `data-plane-thread-incident`. `response-plan` stays ARM-first and
  replays on the data plane only to surface the real error. Threads & Incidents
  (Priority 1) would need a separate data-plane extension.
- Incident response API correction (2026-11-06): the `response-plan` group
  (replaced the unreleased `incident-filter`/`incident-handler` commands) uses the agent's
  data-plane endpoints with audience `https://azuresre.dev`. Direct
  create/read-back on the test agent succeeded where ARM extension calls
  returned generic validation errors; the earlier IcM-identity explanation
  was unproven. Filter writes use a name/type/properties envelope; handlers
  use flat JSON with an ID matching the URL. Existing-name protection is
  preserved through `--overwrite`. Runtime source confirms plural
  `handlingAgents` is IcM-only; Azure Monitor needs singular `handlingAgent`.
  Offline regressions and rebuilt-wheel read-only calls pass; disposable-agent
  CLI write qualification passed on a disposable agent (subagent, filter,
  handler create/show/list/duplicate-guard/overwrite/delete; agent then
  deleted). `incident-filter enable`/`disable` (PATCH of `isEnabled` only)
  also passed live on a second disposable agent: other fields preserved,
  missing filter reported as not found. Duplicate-handler error now names the
  ID. Portal-vs-CLI table for tutorial Step 4 added to `docs\quickstart.md`.
  Preview of matching incidents is not implemented. Earlier scope/status rows above
  predate this correction. Real incident ingestion/investigation is not yet
  qualified by these configuration checks.
- The command surface is generated from the `Microsoft.App/agents` Swagger
  using `aaz-dev` (`scripts/generate_sre_extension.py`), directly under the
  final `az sre ...` names; `custom.py` subclasses generated commands only
  to add behavior and help the generator cannot produce.
- `API_VERSION = "2026-01-01"` is pinned to match the already-generated
  `aaz/latest` recipes. The officially published docs reference
  `2025-05-01-preview` — an unresolved discrepancy, flagged for
  reconciliation before GA, but every command in this extension must use the
  *same* version the generated code already uses or property names could
  silently mismatch between hand-written and generated calls.
- Networking (VNet injection, sandbox egress) is only supported by the real
  deployed api-version `2026-11-01-preview` (confirmed live via
  `az provider show --namespace Microsoft.App`) — not present in
  `2026-01-01`, and the `2026-07-01` public-spec version that does have the
  fields is **not actually deployed to production** (ARM rejects it
  directly). There is no public Swagger for `2026-11-01-preview` yet, so this
  shape was read directly from the internal control-plane source and is
  hand-maintained; re-verify against that source if the service's shape ever
  changes.
- Real built-in RBAC role names were confirmed live via
  `az role definition list --query "[?contains(roleName, 'SRE Agent')]"`:
  `SRE Agent Reader`, `SRE Agent Administrator`, `SRE Agent Standard User`,
  `SRE Agent Author`. An earlier draft wrongly used `"SRE Agent User"` and
  the generic ARM `Reader` role — the latter only grants ARM-level
  visibility, not data-plane agent access; the data-plane UI explicitly
  rejects Owner/Contributor/plain-Reader and requires one of the
  SRE-Agent-specific roles. Confirmed fixed by successfully reaching the
  agent's data-plane UI after the change.
- Runbook/agent extensions (`subagents`, `tools`, `skills`, `scheduledTasks`,
  `incidentFilters`, `commonPrompts`, `hooks`, `incidentHandlers`,
  `httpTriggers`, `repositories`, `pluginMarketplaces`,
  `pluginInstallations`, `githubAuths`, `azureDevOpsAuths`,
  `globalSettings`) are real, ARM-authenticated proxy endpoints
  (`.../agents/{agentName}/{extensionType}[/{name}]`) that the control plane
  forwards to the agent's data-plane cluster — but they are not modeled as
  standard ARM resource types, so no public Swagger covers them and
  `aaz-dev` could never generate commands for them. Confirmed directly from
  the internal control-plane repository's `AgentExtensionsApiController.cs`
  (route + the authoritative regex of valid `extensionType` values) and
  `AgentExtensionsApiService.cs`'s `GetExtensionTypes()` (the canonical
  type list, reproduced in `custom.py`'s `EXTENSION_TYPES`).
- `subagents` and `scheduledTasks` are deliberately gated server-side: they
  require an "approve" data-action claim supplied via an `x-allowed-actions`
  header that only the Portal's own session provides; generic ARM/CLI PUTs
  never receive it, so these two types will always fail regardless of
  payload shape. (`hooks` was originally believed to be gated the same way,
  but was later live-verified end-to-end via a real ARM PUT+GET round trip
  and promoted to its own dedicated `sre hook create/show/list/delete` noun —
  that earlier finding did not hold for `hooks` specifically.) Confirmed in
  the control-plane repo's own unit test comments, and independently
  confirmed for `subagents` by the official Microsoft Learn doc
  (`learn.microsoft.com/azure/sre-agent/create-subagent`), which documents
  subagent creation as a Portal/Agent-Canvas-only flow with a YAML edit tab
  matching the reverse-engineered schema below, and no public REST/CLI path.
- The extension `properties.value` payload format for subagent-style
  extensions is base64-encoded **YAML** (Kubernetes-CRD-style
  `api_version`/`kind`/`metadata`/`spec`), not JSON — found in the
  data-plane runtime source
  (`Agent.Web/Models/ExtendedAgents/AgentDeploymentModel.cs`,
  `YamlResourceRouter.cs`, `Agent.Framework/YamlAgentDescriptor.cs`). A
  correctly-shaped YAML subagent payload still returned a `500` live, which
  is expected and consistent with the gating finding above — the payload
  shape was never the problem for this extension type.
- 188+ offline, credential-free unit tests cover every hand-written command in
  `custom.py`: argument-validation/routing-logic tests for hand-written logic
  (constructed by pre-seeding a bare `AAZCommand` instance's `.ctx`/`.cli_ctx`
  and patching the base `AAZCommand._handler` to a no-op so the subclass's
  own `_handler` body runs against a controlled context), plus real
  `cli.invoke()` argument-enforcement tests that prove invalid/missing CLI
  arguments are rejected by argparse before any handler runs.
- A minimal GitHub Actions CI workflow (checkout → install deps → run unit
  tests → build wheel → upload artifact) runs on every push/PR against
  `charan-kamasani/az-sre-ext` (private, personal GitHub account). GitHub
  Actions is disabled by enterprise policy on the parallel EMU-account copy
  (`ckamasani_microsoft/az-sre-ext`), kept for a future migration into a
  shared org once the team is ready. A full production-grade release
  pipeline (swagger validation, codegen-drift check, SBOM, signed releases)
  is parked, unused, in `.github/workflows-future/release.yml` until signed
  releases are actually needed.

## Decisions

- Build a private Azure CLI extension first, following the standard
  AAZ-generation-plus-hand-written-overlay pattern.
- Use `az sre` as the top-level command (the generator renames the Swagger's
  default `app` group to `sre` in the aaz-dev workspace).
- Keep the noun hierarchy flat (`agent`, `connector`, `tool`, `skill`, etc.
  as independent top-level groups) rather than nesting everything under
  `agent`, and give each of the 15 runbook-extension types its own dedicated
  noun instead of one generic `extension --type` escape hatch. See
  [docs/shape-design.md](docs/shape-design.md) for the alternatives
  considered and why (Paul's shape-feedback points #1/#13).
- Do **not** aim for full portal parity ("live mode", full visual runbook
  authoring) — build discrete, scriptable jobs instead, per Paul's explicit
  guidance.
- Treat the portal as a reference for what's possible, not as the
  specification for what this CLI must build.
- Never duplicate generated request/response logic in `custom.py` — reuse it
  via `super()` wherever a generated recipe already exists; only add
  hand-written logic where no Swagger/generated command could ever cover it
  (networking, runbook extensions) or where real-world validation needs
  tightening beyond what the generated bare-string argument allows
  (`--model-provider`).
- Formally treat `subagents`/`scheduledTasks` runbook authoring as out of CLI
  scope rather than an open blocker to keep chasing — it's a deliberate
  Microsoft platform boundary (confirmed via official docs), not a missing
  schema or a coding gap. (`hooks` was re-tested and does NOT share this
  boundary — it shipped as a fully supported, live-verified, dedicated noun.)
- Keep the public-facing code repo free of internal reverse-engineered notes
  (file paths, class names, and schemas sourced from the internal
  control-plane and data-plane runtime repositories) — those stay in local,
  unpublished session notes only.
- Start the GitHub repo without an org (personal account) to unblock working
  CI immediately (GitHub Actions is disabled by policy on the EMU account);
  migrate to a shared org (`devdiv-microsoft`/`coreai-microsoft`) once the
  team is ready to collaborate on it.

## Open decisions needed from Paul

1. **Read-write vs. read-only access model per role**, specifically for
   threads/incidents — blocks the start of Priority 1 work.
2. ~~Connector consent flow design~~ — investigated and closed without
   needing Paul's input: the control plane has no public ARM action to
   initiate/complete OAuth consent at all, so there is no CLI-side design
   choice to make. The CLI now surfaces a portal deep-link when it detects
   `PendingConsent`.
3. Confirm formally dropping `subagents`/`scheduledTasks` runbook authoring
   from CLI scope (recommended above) rather than carrying it as an open
   item. (`hooks` is no longer part of this question — it shipped.)

## Product evidence

The command surface and every architectural decision above is grounded in:

- Live `az rest`/`az provider show`/`az role definition list` calls against
  real Azure resources (agent CRUD, identity, RBAC, networking, connectors).
- The internal `AAPT-SREAgent-ControlPlane` ADO repository — authoritative
  source for the `2026-11-01-preview` networking shape, the runbook
  extension routing/auth mechanism, and the `subagents`/`hooks`/
  `scheduledTasks` gating root cause (read with repo access, not from any
  public spec).
- The internal `sreagent-runtime` data-plane repository — authoritative
  source for the base64-YAML extension payload schema.
- The official Microsoft Learn SRE Agent documentation
  (`learn.microsoft.com/azure/sre-agent/`), which independently corroborated
  the subagent gating finding and documents the product's organization
  around agent lifecycle, connectors, runbook/subagents, RBAC, and
  networking.

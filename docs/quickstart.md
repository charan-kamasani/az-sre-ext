# Quickstart: the portal's "Get started" walkthrough, from the CLI

The [Azure SRE Agent portal](https://sre.azure.com) walks a new user through
deploying an agent, connecting sources, running a first investigation, and
automating incident response. This is the same walkthrough done entirely with
`az sre`, so you can stand up and bench-test a working agent without opening
a browser.

Everything here runs against real Azure resources and is safe to delete at
the end. Replace the placeholder values before running.

> **Windows PowerShell users:** every `--value '{"key": "value"}'` example on
> this page uses bash-style quoting (single-quoted string containing literal
> double quotes). PowerShell does **not** pass that through to `az.cmd`
> unchanged — it mangles embedded `"` characters, so copy-pasting these
> examples verbatim in `powershell.exe`/`pwsh` fails with either
> `unrecognized arguments` or a JSON parse error. Use backslash-escaped
> quotes instead:
>
> ```powershell
> # Bash-style (works in bash/zsh, fails in PowerShell):
> --value '{"prompt": "Escalate before restarting."}'
>
> # PowerShell-safe equivalent:
> --value '{\"prompt\":\"Escalate before restarting.\"}'
> ```
>
> This is a PowerShell/`.cmd`-wrapper quoting quirk, not an `az sre` bug — it
> affects every Azure CLI command that takes inline JSON. See
> [`operations.md`](operations.md#windows-powershell-json-quoting) for more
> detail.

## 0. Set up

```bash
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
LOCATION="eastus2"          # see "Supported regions" below
RG="rg-sre-quickstart"
AGENT="qs-agent"

az group create --subscription "$SUBSCRIPTION_ID" --name "$RG" --location "$LOCATION"
```

### Supported regions

The SRE Agent resource provider isn't available in every region yet. Check
first — `eastus` is a common miss (use `eastus2` instead):

```bash
az sre agent list-models --location "$LOCATION" --output table
```

If the region is wrong, the error message itself lists every region that
currently works.

## 1. Deploy an agent

Portal: *Create a new SRE Agent*.

```bash
az sre agent create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --location "$LOCATION" \
  --default-model "{provider:anthropic,name:automatic}"

az sre agent wait --resource-group "$RG" --name "$AGENT" --created
az sre agent show --resource-group "$RG" --name "$AGENT" --output table
```

## 2. Connect sources

Portal: *Connect sources* (repositories, logs, Azure resources).

Connect a code repository in one step — this detects GitHub vs. Azure DevOps
from the URL and wires up authentication for you. For GitHub, no pre-existing
`gh auth login` is required: this resolves a token automatically (an
explicit `--github-token`/`GITHUB_TOKEN`/`GH_TOKEN` if set, otherwise a
browser-based GitHub OAuth Device Flow prompt runs — see
[operations.md](operations.md#repo-connect-no-longer-hard-depends-on-the-gh-cli-github-oauth-device-flow)):

```bash
az sre repo connect \
  --resource-group "$RG" --agent-name "$AGENT" \
  --repo-url "https://github.com/<org>/<repo>"
```

Let the agent monitor resources outside its own resource group (needed before
it can investigate anything real):

```bash
az sre managed-resource grant \
  --resource-group "$RG" --agent-name "$AGENT" \
  --target-subscription "$SUBSCRIPTION_ID" --target-resource-group "<rg-to-monitor>"
```

Connect a data source, e.g. Azure Data Explorer for logs/metrics — this is
the exact type the portal's own "Azure Data Explorer" button creates
(confirmed live), so no `--data-source` is needed:

```bash
az sre connector create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name azure-data-explorer --data-connector-type "Azure Data Explorer"
```

> **`Kusto` vs. `KustoClient`:** the friendly name `"Azure Data Explorer"`
> above resolves to the wire value `KustoClient` — the portal's picker has
> no entry for the plain `Kusto` type at all. If you specifically need to
> pin a connector to one cluster URL (what the portal's optional "Add
> clusters" step under the "Azure Data Explorer" wizard creates per
> cluster group), use the raw `Kusto` type instead, which **does** require
> `--data-source`:
>
> ```bash
> az sre connector create \
>   --resource-group "$RG" --agent-name "$AGENT" \
>   --name my-kusto-cluster --data-connector-type Kusto \
>   --data-source "https://help.kusto.windows.net/Samples"
> ```
>
> See [`operations.md`](operations.md#data-connectors) for the full
> `Kusto`/`KustoClient` portal-mapping story.

### The happy path: connector created is not connector working

`connector create` only establishes the ARM link. It does **not** grant the
agent permission to actually read the data behind it — that's a separate
step, and its shape depends on the connector type:

- **OAuth-backed connectors** (first-party types like Outlook/Teams/Icm/
  Dgrep, and some `Mcp` variants) need a human to complete a browser OAuth
  consent flow before `consentStatus` flips from `PendingConsent` to
  `Consented`. `connector show`/`list` surface this status and a direct
  portal link automatically when it's pending — there is no public ARM
  action to drive consent from the CLI.
- **RBAC-backed connectors** (Kusto/`KustoClient`, and anything else that
  points at an Azure resource you already own) need the agent's managed
  identity granted a role on that resource. Nothing in `connector create`
  does this for you.

Confirmed live end to end with the connector from the previous step. First,
find which of the agent's two identities (system-assigned vs. user-assigned)
the connector actually queries with — do not assume:

```bash
az sre agent show --resource-group "$RG" --name "$AGENT" --query identity
```

Granting the wrong identity looks identical to success (the role assignment
is created fine) but the connector still fails — the real Kusto error names
the AAD app actually used, e.g.:

```
Principal 'aadapp=<app-id>;<tenant-id>' is not authorized to read database 'dnci'.
```

Resolve that app ID to find out which identity it really is:

```bash
az ad sp show --id <app-id> --query "{displayName:displayName, id:id}"
```

`id` here is the principal (object) ID to grant — in the live test this
turned out to be the agent's **system-assigned** identity, not the
user-assigned one that seemed like the obvious choice. Grant it Viewer on
the Kusto database (requires the `kusto` CLI extension):

```bash
az kusto database-principal-assignment create \
  --cluster-name <cluster> --resource-group <cluster-rg> --database-name <db> \
  --principal-assignment-name "$AGENT-viewer" \
  --principal-id <resolved-identity-object-id> --principal-type App --role Viewer \
  --tenant-id "$(az account show --query tenantId -o tsv)"
```

Then prove it end to end by asking the agent a question that forces it to
use the connector (data-plane chat, portal only — see step 4 below):

> "Using the \<connector-name\> Azure Data Explorer connector, run `.show
> tables` on the `<db>` database and list what you find."

A real response with actual table names (not an access error) is the
complete happy path: connector created → access granted → agent queries
live data. Live-verified this exact flow on 2026-11-05: the portal's
Connectors blade flipped from `Failed: Forbidden (403)` to `Connected`
after the correct identity was granted, and the agent's chat response came
back with real Kusto table names from the live cluster.

## 3. Give it operational context

Portal: *Team onboarding* and *Knowledge capture*.

Upload a runbook so the agent can reference it during investigations:

```bash
az sre knowledge create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name runbook --type file --file-path ./runbook.md
```

Set always-on custom instructions (team conventions, escalation contacts,
tone):

```bash
az sre instructions create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name default --value '{"prompt": "Escalate to #oncall-platform before restarting any production service."}'
```

## 4. First investigation

Portal: *Chat-based troubleshooting*.

This step is intentionally **not** a CLI command. Chatting with the agent
("investigate this alert", seeing its triage/root-cause output) is a
data-plane conversation against the agent's own runtime
(`sre.azure.com`/the agent's chat endpoint), not an ARM control-plane
operation. This CLI only manages the ARM resource around the agent — use the
portal or the agent's API directly for the conversation itself. Resolve the
URL to call it from your own tooling:

```bash
az sre endpoint show --resource-group "$RG" --name "$AGENT"
```

## 5. Route incidents to this agent

Portal: *Incidents > "Triggers & response plans"*.

Configure Azure Monitor and create a subagent before routing incidents.
This example creates a disabled filter in Review mode, so setup alone
does not start investigations:

```bash
az sre agent update --resource-group "$RG" --name "$AGENT" \
  --incident-management-configuration '{type:AzMonitor}'

az sre subagent create --resource-group "$RG" --agent-name "$AGENT" \
  --name incident-responder \
  --value '{"instructions":"Gather incident evidence and report findings without changing resources.","handoffDescription":"Incident evidence collection","tools":["ReadFile"],"mcpTools":[],"commonTools":[],"allowedSkills":[],"allowParallelToolCalls":true}'

az sre response-plan create \
  --resource-group "$RG" --agent-name "$AGENT" --name disk-space \
  --platform AzMonitor --subagent incident-responder --title-contains "disk space" \
  --mode review --disabled \
  --instructions "Gather disk-usage evidence and report findings."

az sre response-plan show \
  --resource-group "$RG" --agent-name "$AGENT" --name disk-space

# Turn the plan on or off without deleting it (only isEnabled changes)
az sre response-plan enable  --resource-group "$RG" --agent-name "$AGENT" --name disk-space
az sre response-plan disable --resource-group "$RG" --agent-name "$AGENT" --name disk-space
```

A response plan is an incident filter (the match rules and the subagent that
handles matches) plus an optional incident handler (instructions) that links to
the filter. `response-plan` manages both. `incident-filter` and
`incident-handler` remain for advanced use.

### Portal vs. CLI for this step (benchmark: tutorial "Step 4: Set up incident response")

Which parts of the tutorial the CLI covers, and where to hand off to the portal.
Nothing here is all-or-nothing: do the portal-only step, then continue in the CLI.

| Tutorial step | Where | How |
|---|---|---|
| Azure Monitor as incident source | CLI | Automatic at agent creation. Check with `az sre agent show ... --query properties.incidentManagementConfiguration`. |
| Connect PagerDuty | CLI | `--incident-management-configuration "{type:PagerDuty,connection-key:<api-key>,obo-user:<email>}"` on `agent create`/`update`. Live-checked with a fake key: the service validates the shape (bad email and missing key give clear errors) and accepted the request, but does not check the key with PagerDuty at create time. A working connection has not been tested with real credentials. |
| Connect ServiceNow | CLI (basic auth) or portal (OAuth) | `--incident-management-configuration "{type:ServiceNow,connection-url:'https://<instance>.service-now.com',connection-key:<credentials>}"`. Quote the URL. A missing credential gives `MissingServiceNowCredentials`. Live-checked with fake values only. The OAuth flow opens a browser popup and needs the portal. |
| Disconnect/switch platform | Portal *Incidents > ... menu* | No verified CLI path. A filter's `incidentPlatform` must match the agent's configured type. |
| Create the subagent | CLI | `az sre subagent create`. |
| Create the response plan | CLI | `az sre response-plan create` (writes the incident filter, plus the handler when `--instructions` is given). Live-verified; CLI-created plans appear in the portal grid. |
| Turn a plan on/off | CLI | `az sre response-plan enable` / `disable`. |
| Preview matching incidents | CLI | `az sre incident query --filter-name <name>` (or `--filter '<json>'`). Reads the connected platform's incidents; an agent with no alerts returns an empty list. |
| Delete the quickstart plan | CLI | `az sre response-plan list`, then `az sre response-plan delete --name quickstart_response_plan`. `list` and `create` warn when a plan with that name exists (name taken from the runtime source; not yet seen live). |
| Read investigation findings | CLI | `az sre thread list`, then `az sre thread messages --thread-id <id>`. |

Control-plane gaps behind these rows: ARM has no quickstart-plan or
consent operations, and it can hide the real reason a filter is rejected
behind a generic error. Thread and incident reads use the agent data plane.

Filter and handler create, show, list and delete go through ARM. If ARM
returns the generic `extension configuration is invalid` error, the CLI
replays the request on the agent data plane (audience `https://azuresre.dev`)
to show the real reason. `enable`/`disable` and `--agent-url` reads use the
data plane. Configure an incident platform on the agent first
(`az sre agent update --incident-management-configuration`). Use `--overwrite` to intentionally update an existing filter or
handler. Review the saved configuration before enabling a filter; this
example does not test real alert delivery or automatic investigation.
See the [incident response tutorial](https://learn.microsoft.com/azure/sre-agent/tutorial-incident-response).

Run the agent on a schedule, and from an inbound webhook:

```bash
az sre automation scheduled-task create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name nightly-check \
  --value '{"cronExpression":"0 2 * * *","agentPrompt":"Check overnight error rates."}'

az sre automation http-trigger create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name webhook-trigger \
  --value '{"agentPrompt":"Investigate the incoming alert."}'
```

Add a lifecycle hook so a script runs before/after every tool call:

```bash
az sre hook create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name audit-log --value '{"eventType":"PostToolUse","activationMode":"always","hook":{"type":"command","command":"echo logged","failMode":"Allow","matcher":".*"}}'
```

> **`hook.matcher` is required for `PreToolUse`/`PostToolUse`:** live-confirmed
> — the real API rejects a `PostToolUse`/`PreToolUse` hook missing `matcher`
> (a tool-name regex, e.g. `"Bash.*"` or `".*"` for "every tool") with an
> opaque "extension configuration is invalid" error. `Start`/`Stop` hooks
> don't need it. The CLI now validates this client-side with a clear
> message instead of surfacing that opaque 400.

## 6. Extend with custom automation

Portal: *Custom agents & skills* and *Plugin marketplace*.

```bash
az sre tool create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name docs-link --value '{"type": "LinkTool", "name": "docs-link", "description": "Opens the runbook", "template": "https://example.com/runbook"}'

az sre skill create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name triage-skill --file-path ./SKILL.md
```

## 7. Governance and security

Portal: *RBAC* and *Network*.

```bash
az sre access grant \
  --resource-group "$RG" --name "$AGENT" \
  --role user --assignee someone@contoso.com

az sre network update \
  --resource-group "$RG" --name "$AGENT" \
  --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[pypi.org]}}"
```

## 8. Tune agent-wide behavior

Portal: *Build + setup > Settings* (preview).

```bash
az sre agent settings update \
  --resource-group "$RG" --agent-name "$AGENT" \
  --value '{"toolPermissions": {"allow": [], "ask": [], "deny": ["restart*"]}, "approvalExpirationSetting": {"enabled": true, "approvalExpirationInMinutes": 120}}'

az sre agent settings show --resource-group "$RG" --agent-name "$AGENT"
```

> **`toolPermissions` is all-or-nothing:** live-confirmed — once you include
> `toolPermissions` at all, the real API requires all three of
> `allow`/`ask`/`deny` (each can be `[]`), rejecting a partial object (e.g.
> just `deny`) with a misleading "contains an invalid or unrecognized
> property" 400 — the real cause is a *missing* sibling property, not an
> unrecognized one. The CLI now validates this client-side with an accurate
> message instead of surfacing that 400.

## Clean up

```bash
az sre agent delete --resource-group "$RG" --name "$AGENT" --yes
az group delete --subscription "$SUBSCRIPTION_ID" --name "$RG" --yes --no-wait
```

## What this bench test proves

Running sections 1–3 and 5–8 end to end against a disposable agent exercises
every noun in the CLI's public surface at least once, in the same order a
new user would hit them in the portal. It is the fastest way to catch a
regression across the whole command surface after a refactor, not just the
unit tests.

## Open questions

- Step 4 (chat-based investigation) has no CLI equivalent today and isn't
  planned, since it's a data-plane feature outside this CLI's control-plane
  scope (see [PLAN.md](../PLAN.md)). The "happy path" section above shows
  how to verify it manually in the portal chat once access is granted —
  that verification step itself still can't be scripted from the CLI.

## Related docs

| Guide | Use it for |
| --- | --- |
| [CLI ergonomics reference](cli-reference.md) | Every group, command, exact syntax, option, and default |
| [Operations](operations.md) | Confirmed/unconfirmed payload shapes and known service-side quirks for each command used above |
| [Testing](testing.md) | How this same flow is exercised with throwaway resources in CI/live verification |

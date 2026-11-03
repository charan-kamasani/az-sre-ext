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
from the URL and wires up authentication for you:

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

Connect a data source, e.g. Kusto for logs/metrics:

```bash
az sre connector create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name my-kusto --data-connector-type Kusto \
  --data-source "https://help.kusto.windows.net/Samples"
```

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

Route matching incidents to this agent:

```bash
az sre incident-filter create \
  --resource-group "$RG" --agent-name "$AGENT" \
  --name high-sev --value '{"incidentPlatform":"Icm","titleContains":"disk space","handlingAgents":["'"$AGENT"'"],"isEnabled":true}'
```

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
  scope (see [PLAN.md](../PLAN.md)). Worth confirming with Paul whether that
  gap should be called out more prominently, or left as portal-only by
  design.

## Related docs

| Guide | Use it for |
| --- | --- |
| [CLI ergonomics reference](cli-reference.md) | Every group, command, exact syntax, option, and default |
| [Operations](operations.md) | Confirmed/unconfirmed payload shapes and known service-side quirks for each command used above |
| [Testing](testing.md) | How this same flow is exercised with throwaway resources in CI/live verification |

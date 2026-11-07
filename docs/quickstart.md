# Quickstart: set up your SRE agent

The [README quick start](../README.md#quick-start) creates an agent and connects a
repository and a data source. This guide picks up from there: share the agent, let it
monitor your Azure resources, add a custom skill and route incidents to it.

## Before you start

Finish the [README quick start](../README.md#quick-start) first, and keep the same shell
open so these variables are still set:

```bash
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
RG="<resource-group>"
AGENT="<agent-name>"
```

The examples use bash. In PowerShell, set variables as `$RG = "my-rg"` and end continued
lines with a backtick (`` ` ``). Flags that take JSON need extra care on Windows; see
[JSON quoting on Windows](operations.md#windows-powershell-json-quoting).

## 1. Share the agent

Give yourself, a teammate or a group a built-in role on the agent: `admin`, `author`,
`user` or `reader`.

```bash
az sre access grant \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --role user \
  --assignee "<user-or-group-object-id>"
```

To grant the role to the signed-in user, pass `--assignee-me true` instead of `--assignee`.
List who has access with `az sre access list`.

## 2. Let the agent monitor your Azure resources

An agent can only investigate resources its identity can read. Grant it Reader and
Monitoring Contributor on the resource group to monitor:

```bash
az sre managed-resource grant \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --target-subscription "$SUBSCRIPTION_ID" \
  --target-resource-group "<resource-group-to-monitor>"
```

To cover a whole subscription, omit `--target-resource-group`. Check the result with
`az sre managed-resource list` and undo it with `az sre managed-resource revoke`.

## 3. Add a custom skill

A skill teaches the agent a procedure. Write it as a `SKILL.md` file with a description
and the steps to follow:

```markdown
---
description: Check a service's health before escalating
---

# Service health check

1. Query the last hour of error rates for the service.
2. Compare them with the previous day.
3. Report whether the change is within normal range.
```

Then create the skill from the file:

```bash
az sre skill create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name service-health-check \
  --file-path ./SKILL.md
```

## 4. Route incidents to the agent

Send high-severity Azure Monitor incidents to a subagent. Start in review mode, so the
agent proposes actions and you approve each one. The subagent must already exist.

```bash
az sre response-plan create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name sev1-api \
  --platform AzMonitor \
  --subagent "<subagent-name>" \
  --priority Sev0 Sev1 \
  --mode review
```

Pause the plan without deleting it with `az sre response-plan disable`.

## Clean up

Delete the resource group from the README quick start. This removes the agent with it.
See [Clean up](../README.md#clean-up) for the command.

## Next steps

- [CLI reference](cli-reference.md): every command, option and example
- [Connector types](connector-types.md): the values for `--data-connector-type`
- [Operations guide](operations.md): connectors, networking, RBAC and incident handling in depth
- Questions or bugs: [open an issue](https://github.com/charan-kamasani/az-sre-ext/issues)

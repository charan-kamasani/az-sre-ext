# Quickstart: set up your SRE agent

This guide takes you from nothing to a working SRE agent: create it, connect a repository
and a data source, share it, let it monitor your Azure resources, add a custom skill and
route incidents to it. The first steps repeat the [README quick start](../README.md#quick-start),
so you can follow this page on its own.

You need [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) 2.75.0 or
later with the `sre` extension installed, and a subscription where you can create
resources. The examples use bash. In PowerShell, set variables as `$RG = "my-rg"` and end
continued lines with a backtick (`` ` ``). Flags that take JSON need extra care on Windows;
see [JSON quoting on Windows](operations.md#windows-powershell-json-quoting).

## Set up your context

```bash
az login

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
LOCATION="eastus2"
TEST_ID="$(date +%s)"
RG="rg-sre-${TEST_ID}"
AGENT="sre-${TEST_ID}"
```

## Create the agent

```bash
az group create \
  --subscription "$SUBSCRIPTION_ID" \
  --name "$RG" \
  --location "$LOCATION"

az sre agent create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --location "$LOCATION"

az sre agent show \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --output table
```

## Connect a repository

For GitHub, the command shows a one-time code and opens GitHub's sign-in page in
your browser; enter the code there. In CI, set `GITHUB_TOKEN` or pass
`--github-token` instead.

```bash
az sre repo connect \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --repo-url "https://github.com/<org>/<repo>"
```

## Connect a data source

Connect an Azure Data Explorer cluster the agent can query:

```bash
az sre connector create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name adx \
  --data-connector-type "Azure Data Explorer"
```

A new connector links the data source but doesn't give the agent access to it. Grant the
agent's identity a reader role on the data source next.
## Share the agent

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

## Let the agent monitor your Azure resources

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

These commands default to the agent's system-assigned identity. If the runtime
uses a user-assigned identity, find its assigned ARM resource ID with
`az sre identity show` and pass `--identity "<assigned-UAMI-ARM-ID>"` to
**grant, list, and revoke**. `--identity system` explicitly selects the default.
Selecting an identity for RBAC does not change the agent's runtime configuration.
See the [identity selection workflow](operations.md#rbac) for a complete example.

## Add a custom skill

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

## Route incidents to the agent

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

> [!CAUTION]
> This permanently deletes the resource group and everything in it, including the agent.
> Confirm the variables before running it. It does not delete the repository or the
> Azure Data Explorer cluster.

```bash
printf 'Deleting subscription=%s resource-group=%s\n' \
  "$SUBSCRIPTION_ID" "$RG"

az group delete \
  --subscription "$SUBSCRIPTION_ID" \
  --name "$RG" \
  --yes \
  --no-wait
```
## Next steps

- [CLI reference](cli-reference.md): every command, option and example
- [Connector types](connector-types.md): the values for `--data-connector-type`
- [Operations guide](operations.md): connectors, networking, RBAC and incident handling in depth
- Questions or bugs: [open an issue](https://github.com/charan-kamasani/az-sre-ext/issues)

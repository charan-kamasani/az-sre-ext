# Quickstart: set up your SRE agent

This guide takes you from nothing to a working SRE agent: create it, connect a repository
and a data source, share it, let it monitor your Azure resources, add a custom skill and
route incidents to it. The first steps repeat the [README quick start](../README.md#quick-start),
so you can follow this page on its own.

The examples use bash. In PowerShell, set variables as `$RG = "my-rg"` and end
continued lines with a backtick (`` ` ``). Flags that take JSON need extra care on Windows;
see [JSON quoting on Windows](operations.md#windows-powershell-json-quoting).

## Prerequisites

Check these before you start. Creating the agent only needs the first three rows. The
later steps fail with permission errors if the rest are missing, and the error doesn't
always say which permission.

| You need | For | How to check |
| --- | --- | --- |
| [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) 2.75.0 or later | Everything | `az version` |
| The `sre` extension | Everything | `az extension show --name sre`. To install it, see the [README](../README.md#install). |
| Owner, or Contributor plus User Access Administrator, on the subscription or resource group for the agent | [Creating the agent](#create-the-agent) and [sharing it](#share-the-agent) | `az role assignment list --assignee "$(az ad signed-in-user show --query id -o tsv)" --all -o table` |
| Owner or User Access Administrator on each subscription or resource group the agent should monitor | [Letting it monitor resources](#let-the-agent-monitor-your-azure-resources) | Same command |
| Admin on the Azure Data Explorer database | [Connecting a data source](#connect-a-data-source) | Ask the database admin |
| A GitHub account that can read the repository | [Connecting a repository](#connect-a-repository) | Open the repository in your browser |

These requirements match the portal's; see
[Create and set up Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/create-and-set-up#prerequisites).

The agent works through its own managed identity, not yours. `az sre agent create` makes
a user-assigned identity for it and turns on a system-assigned one too. Every data source
the agent reads needs its own grant to that identity. Creating a connector doesn't give
the agent access.

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
`--github-token` instead. The agent keeps one GitHub credential for all its
GitHub repositories, so use a token that can read every repository you connect.

```bash
az sre repo connect \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --repo-url "https://github.com/<org>/<repo>"
```

## Connect a data source

Connecting Azure Data Explorer takes two steps: create the connector, then give the
agent's identity access to the database. Until the second step is done, queries fail
with a permission error.

1. Create the connector:

   ```bash
   az sre connector create \
     --subscription "$SUBSCRIPTION_ID" \
     --resource-group "$RG" \
     --agent-name "$AGENT" \
     --name adx \
     --data-connector-type "Azure Data Explorer" \
     --tool-access true
   ```

   `--name` is a label you choose. "Azure Data Explorer" is the portal's name for the
   type; the service stores it as `KustoClient`, so that's what `connector show` returns.
   This connector can query any cluster the agent's identity has access to, so it doesn't
   take a cluster URL. `--tool-access true` lets the main agent use its query tools.

   To pin the connector to one cluster and database instead, use the `Kusto` type and
   create one connector per cluster:

   ```bash
   az sre connector create \
     --subscription "$SUBSCRIPTION_ID" \
     --resource-group "$RG" \
     --agent-name "$AGENT" \
     --name production \
     --data-connector-type Kusto \
     --data-source "https://<cluster>.<region>.kusto.windows.net/<database>"
   ```

2. Get the app ID of the identity the connector queries with. A connector created
   without `--identity` uses the agent's **system-assigned** identity. That's the one
   that worked in a live test; granting the user-assigned identity instead creates the
   grant but queries still fail.

   ```bash
   PRINCIPAL_ID=$(az sre agent show \
     --subscription "$SUBSCRIPTION_ID" \
     --resource-group "$RG" \
     --name "$AGENT" \
     --query identity.principalId \
     --output tsv)

   az ad sp show --id "$PRINCIPAL_ID" --query appId --output tsv
   ```

3. Ask a database admin to run this in Azure Data Explorer, using the app ID from
   step 2:

   ```kusto
   .add database <database> viewers ('aadapp=<app-id>')
   ```

   Repeat it for each database the agent should query. To check the grant, run
   `.show database <database> principals`.

4. Check that it works by asking the agent in the portal chat:

   > Using the adx connector, run `.show tables` on the `<database>` database and list
   > what you find.

   A list of table names means the setup is complete. If you get an error like
   `Principal 'aadapp=<app-id>;<tenant-id>' is not authorized to read database`, that
   `<app-id>` is the identity the agent actually used. Grant that one in step 3.

For more about the connector, see
[Connect Kusto](https://learn.microsoft.com/azure/sre-agent/kusto-connector).

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
  --target-rg "<resource-group-to-monitor>"
```

To cover a whole subscription, omit `--target-rg`. Check the result with
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

Send high-severity Azure Monitor incidents to a subagent. First connect Azure Monitor as
the agent's incident platform:

```bash
az sre agent update \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --incident-management-configuration '{type:AzMonitor,connection-name:azmonitor}'
```

Then create the subagent that handles the incidents. Save its configuration as
`subagent.json`. `instructions` must be at least 50 characters, and `handoffDescription`
tells the main agent when to hand work over:

```json
{
  "instructions": "You triage Azure Monitor alerts for the web API and summarize the evidence you find.",
  "handoffDescription": "Use for triaging Azure Monitor alerts on the web API."
}
```

```bash
az sre subagent create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name triage \
  --value @subagent.json
```

Now create the response plan. Start in review mode, so the agent proposes actions and you
approve each one:

```bash
az sre response-plan create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name sev1-api \
  --platform AzMonitor \
  --subagent triage \
  --priority Sev0 Sev1 \
  --mode review
```

Pause the plan without deleting it with `az sre response-plan disable`. For PagerDuty or
ServiceNow, and for the steps that still need the portal, see
[Step 4: Set up incident response](portal-cli-handoff.md#step-4-set-up-incident-response).
IcM works only on Microsoft first-party agents; see
[Non-Microsoft tenants](operations.md#non-microsoft-tenants).

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
- [Portal and CLI handoff guide](portal-cli-handoff.md): each Microsoft Learn tutorial step, with
  the command to run or the portal page to use
- [Connector types](connector-types.md): the values for `--data-connector-type`
- [Operations guide](operations.md): connectors, networking, RBAC and incident handling in depth
- Questions or bugs: [open an issue](https://github.com/charan-kamasani/az-sre-ext/issues)

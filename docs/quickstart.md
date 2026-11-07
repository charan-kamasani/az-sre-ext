# Quickstart: create and connect an SRE Agent

In about 10 minutes you will create an Azure SRE Agent from the command line,
give it access to a repository and a data source, route incidents to it, and
clean up. It uses the `az sre` extension, so you don't need the portal.

## Before you start

- [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) 2.75.0 or later
- An Azure subscription where you can create resources
- A supported region. If you pick one that isn't supported, the error lists the ones that are. `eastus2` works.

Sign in and install the extension:

```bash
az login
az extension add --source <path-or-url-to-sre-wheel>
az sre --help
```

The examples use bash. In PowerShell, set variables as `$RG = "rg-sre-quickstart"` and
see [JSON quoting on Windows](operations.md#windows-powershell-json-quoting) for flags that take JSON.

```bash
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
LOCATION="eastus2"
RG="rg-sre-quickstart"
AGENT="quickstart-agent"
```

## 1. Create an agent

```bash
az group create --subscription "$SUBSCRIPTION_ID" --name "$RG" --location "$LOCATION"

az sre agent create -g "$RG" --name "$AGENT" --location "$LOCATION" \
  --default-model "{provider:anthropic,name:automatic}"

az sre agent show -g "$RG" --name "$AGENT" --output table
```

To see the models available in a region first, run `az sre agent list-models --location "$LOCATION"`.

## 2. Connect your sources

Connect the repository that holds your service's code. GitHub asks you to sign in
in the browser the first time:

```bash
az sre repo connect -g "$RG" --agent-name "$AGENT" \
  --repo-url https://github.com/<org>/<repo>
```

Let the agent read the Azure resources it will investigate:

```bash
az sre managed-resource grant -g "$RG" --agent-name "$AGENT" \
  --target-subscription "$SUBSCRIPTION_ID" --target-resource-group <resource-group-to-monitor>
```

Connect a data source, for example Azure Data Explorer:

```bash
az sre connector create -g "$RG" --agent-name "$AGENT" \
  --name adx --data-connector-type KustoClient
```

Creating a connector links it to the agent. It does not give the agent permission
to read the data. Grant the agent's managed identity a reader role on the data source
next. Check the connector with `az sre connector show -g "$RG" --agent-name "$AGENT" -n adx`.

## 3. Route incidents to the agent

Send high-severity Azure Monitor incidents to a subagent. Start in review mode so
you approve each action:

```bash
az sre response-plan create -g "$RG" --agent-name "$AGENT" -n sev1-api \
  --platform AzMonitor --subagent <subagent-name> --priority Sev0 Sev1 --mode review
```

Pause the plan without deleting it with `az sre response-plan disable`.

## 4. Clean up

```bash
az sre agent delete -g "$RG" --name "$AGENT" --yes
az group delete --subscription "$SUBSCRIPTION_ID" --name "$RG" --yes --no-wait
```

## Next steps

- [CLI reference](cli-reference.md): every command, option and example
- [Connector types](connector-types.md): the values for `--data-connector-type`
- [Operations guide](operations.md): connectors, networking, RBAC and incident handling in depth
- Questions or bugs: [open an issue](https://github.com/charan-kamasani/az-sre-ext/issues)

# Azure CLI Sre Extension #

`az sre` manages the control plane of `Microsoft.App/agents` (Azure SRE Agent)
resources: lifecycle, identity, networking, RBAC, data connectors, and runbook
extensions (tools, skills, prompts, and similar). It does not talk to the
agent's own data plane directly.

## How to install ##

```bash
az extension add --source dist/sre-1.0.0b1-py3-none-any.whl -y
```

## How to use ##

```bash
# create an agent
az sre agent create --resource-group <rg> --name <agent> --location eastus2

# grant a teammate access
az sre access grant --resource-group <rg> --agent-name <agent> \
  --role user --assignee someone@example.com

# inspect connection details
az sre connection show --resource-group <rg> --name <agent>

# manage data connectors
az sre connector create --resource-group <rg> --agent-name <agent> \
  --name conn-kusto --data-connector-type Kusto --mcp-endpoint "https://help.kusto.windows.net/v1/rest"

# manage custom instructions / tools / skills / hooks (dedicated nouns)
az sre instructions create --resource-group <rg> --agent-name <agent> \
  --name default --value '{"prompt": "Always check the runbook before restarting a service."}'

# generic extension escape hatch, for types with no dedicated noun yet
# (subagents, scheduledTasks, incidentFilters, incidentHandlers,
# httpTriggers, globalSettings)
az sre extension create --resource-group <rg> --agent-name <agent> \
  --extension-type globalSettings --extension-name default --value '{}'
```

Run `az sre --help` for the top-level noun list, or `az sre <noun> --help`
(e.g. `az sre connector --help`) for any one group. See the repository
root [README.md](https://github.com/charan-kamasani/az-sre-ext#readme) and
[docs/](https://github.com/charan-kamasani/az-sre-ext/tree/master/docs) for
the complete, always-current command reference, supported extension-type
shapes, and architecture notes.
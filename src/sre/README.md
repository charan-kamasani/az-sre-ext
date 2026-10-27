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
az sre agent grant-access --resource-group <rg> --agent-name <agent> \
  --role user --assignee someone@example.com

# inspect connection details
az sre agent get-connection --resource-group <rg> --name <agent>

# manage data connectors
az sre agent connector create --resource-group <rg> --agent-name <agent> \
  --name <connector> --type Kusto --value '{"clusterUri": "...", "database": "..."}'

# manage runbook extensions (tools, skills, commonPrompts, etc.)
az sre agent extension create --resource-group <rg> --agent-name <agent> \
  --extension-type commonPrompts --name default --value '[{"name": "greeting", "content": "..."}]'
```

Run `az sre agent --help` for the full command tree, or see the repository
root [README.md](https://github.com/charan-kamasani/az-sre-ext#readme) and
[docs/](https://github.com/charan-kamasani/az-sre-ext/tree/master/docs) for
the complete command reference, supported extension-type shapes, and
architecture notes.
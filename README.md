# Azure SRE Agent CLI extension

`az sre` creates and manages [Azure SRE Agent](https://learn.microsoft.com/azure/sre-agent/overview)
resources from the command line: agent lifecycle, identity, access, repositories, data
connectors, tools, skills, scheduled tasks and incident response plans. Everything is scriptable,
so you can set up and tear down agents from a pipeline or share a setup as code.

> [!NOTE]
> This extension is in preview. Commands and options may change between releases.

## Quick start

You need [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) 2.75.0 or later
with the `sre` extension installed, and an Azure subscription where you can create resources.

Sign in and create an agent. Use your own values. The examples use bash; in PowerShell, set
variables as `$RG = "my-rg"` and end continued lines with a backtick (`` ` ``) instead of `\`.

```bash
SUBSCRIPTION_ID="<subscription-id>"
RG="<resource-group>"
AGENT="<agent-name>"
LOCATION="eastus2"
```

```bash
az login

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

Connect a repository and a data source (here, an Azure Data Explorer cluster the agent can query):

```bash
az sre repo connect \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --repo-url "https://github.com/<org>/<repo>"

az sre connector create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --name adx \
  --data-connector-type "Azure Data Explorer"
```

`repo connect` opens a GitHub sign-in in the browser. In CI, pass `--github-token` or set
`GITHUB_TOKEN`. A new connector links the data source but doesn't give the agent access
to it, so grant the agent's identity a reader role on the data source next.

To clean up, delete the resource group, which removes the agent with it:

```bash
az group delete \
  --subscription "$SUBSCRIPTION_ID" \
  --name "$RG" \
  --yes \
  --no-wait
```

Run `az sre <command> --help` for required arguments and examples. The
[quickstart](docs/quickstart.md) covers data sources, access and incident routing, and the
[CLI reference](docs/cli-reference.md) lists every command.

## What you can do

| Group | Commands | Use it to |
|---|---|---|
| `agent` | `create, show, list, update, delete, start, stop, list-models, wait`<br>**settings:** `show, update` | Manage the core SRE Agent lifecycle and global settings (tool/skill permissions, custom instructions, approval expiration). |
| `access` | `grant, list, revoke` | Grant, list, or revoke built-in RBAC roles (admin, user, author, reader) on the agent. |
| `connector` | `create, show, list, update, delete, list-secret` | Connect the agent to external data sources. Now accepts friendly names (Azure Data Explorer, Custom MCP, Office 365 Outlook, Microsoft Teams, Microsoft IcM, Microsoft DGrep) as well as raw wire values. |
| `endpoint` | `show` | Resolve the agent's live endpoint URL. |
| `hook` | `create, show, list, delete` | Manage lifecycle hooks (Start, PreToolUse, PostToolUse, Stop) that run prompts or scripts. |
| `identity` | `assign, show, remove` | Manage the agent's managed identity. |
| `response-plan` | `create, show, list, delete, enable, disable` | Route matching incidents to a subagent, with optional instructions (portal: Incidents > "Triggers & response plans"). |
| `instructions` | `create, show, list, delete` | Manage the agent's always-on custom instructions. |
| `knowledge` | `create, show, list, delete` | Add files or web pages the agent can read and reason over. |
| `managed-resource` | `grant, list, revoke` | Allow the agent's identity to monitor resources outside its resource group. |
| `network` | `update` | Configure VNet injection and sandbox egress allowlist (Preview). |
| `plugin` | **marketplace:** `create, show, list, delete`<br>**install:** `create, show, list, delete` | Connect a plugin marketplace and install specific plugins from it. |
| `repo` | `connect` | Connect a GitHub or Azure DevOps repository with automatic authentication configuration. |
| `skill` | `create, show, list, delete` | Create and manage custom SKILL.md-based skills. |
| `subagent` | `create, show, list, delete` | Manage named subagents the main agent hands work to (portal: Agent Canvas). |
| `tool` | `create, show, list, delete` | Manage custom tools the agent can invoke. |
| `usage` | `list` | View agent usage and billing statistics. |
| `automation` | **scheduled-task:** `create, show, list, delete`<br>**http-trigger:** `create, show, list, delete` | Manage scheduled runs and inbound webhook triggers. |

Run `az sre <group> --help` for any group. Exact syntax, options and defaults for every
command are in the generated [CLI reference](docs/cli-reference.md).

## More documentation

| Guide | Use it for |
|---|---|
| [CLI ergonomics reference](docs/cli-reference.md) | Every group, command, exact syntax, option, and default — generated, never drifts |
| [Quickstart](docs/quickstart.md) | Create an agent, connect sources and route incidents, from the CLI |
| [Connector types](docs/connector-types.md) | Values for `--data-connector-type` and their portal names |
| [CLI shape design](docs/shape-design.md) | Why the command surface is flat top-level nouns instead of everything nested under `agent`, and why each runbook-extension type gets its own noun instead of one generic `extension --type` |
| [Operations](docs/operations.md) | Agent lifecycle, RBAC, connectors, and confirmed/unconfirmed runbook extension payload shapes |
| [Networking](docs/networking.md) | VNet injection, sandbox egress, and safe sequencing for `network update` |
| [Testing](docs/testing.md) | Coverage layers and the live-verification workflow (rebuild/reinstall, throwaway agents, round-trip shape confirmation) |
| [Development](docs/development.md) | Architecture, local validation, CLI reference regeneration, commit hook |
| [Source code guide](docs/source-code.md) | Repository layout, generated vs. hand-authored code, how a command flows, security boundaries |
| [Implementation plan](PLAN.md) | Scope, architecture decisions, evidence, roadmap, and open blockers |

## Feedback

Found a bug or want a command added? [Open an issue](https://github.com/charan-kamasani/az-sre-ext/issues).

## Contributing

Run the offline unit tests (no Azure credentials needed):

```bash
cd src/sre
pip install azure-cli-core azure-cli-testsdk build setuptools wheel
python -m unittest discover -s azext_sre/tests
```

Install the commit hook once per checkout. It regenerates `docs/cli-reference.md` on every commit:

```bash
git config core.hooksPath .githooks
```

Most commands are generated from the `Microsoft.App/agents` API spec and live under
`azext_sre/aaz/latest/`. Don't edit those by hand. Hand-written behavior lives in
`azext_sre/custom.py`. See the [development guide](docs/development.md),
[testing guide](docs/testing.md) and [source code guide](docs/source-code.md).

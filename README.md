# Azure SRE Agent CLI extension

`sre` is an Azure CLI extension for creating and operating Azure SRE Agent
(`Microsoft.App/agents`) resources. It manages agents, identities, access,
repositories, data connectors, tools, skills, scheduled tasks, and incident
response plans under `az sre`.

> [!NOTE]
> This project is in preview. The command surface is not stable. Use it in
> test subscriptions until a release is published.

> [!IMPORTANT]
> Reviewing CLI ergonomics? Start with the generated
> **[`az sre` CLI reference](docs/cli-reference.md)**. It contains every group,
> command, exact syntax, option, and default.

## Quick start

Create an agent, connect a repository and an Azure Data Explorer data source, then clean
up. You need
[Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli) 2.90.0 or later with
the `sre` extension installed, and a subscription where you can create resources.

Sign in, then set the subscription and a unique test context. The examples use bash; in
PowerShell, set variables as `$RG = "my-rg"` and end continued lines with a backtick
(`` ` ``) instead of `\`:

```bash
az login

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
LOCATION="eastus2"
TEST_ID="$(date +%s)"
RG="rg-sre-${TEST_ID}"
AGENT="sre-${TEST_ID}"
```

Create the agent:

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

Connect a repository. For GitHub, the command shows a one-time code and opens
GitHub's sign-in page in your browser; enter the code there. In CI, set
`GITHUB_TOKEN` or pass `--github-token` instead:

```bash
az sre repo connect \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --repo-url "https://github.com/<org>/<repo>"
```

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

For access, incident routing, tools and skills, see the [quickstart](docs/quickstart.md) and
the [operations guide](docs/operations.md).

### Clean up

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

Run `az sre <group> --help` for any group.

## CLI reference

The generated **[CLI reference](docs/cli-reference.md)** lists every command, option,
default and example. It is generated from the loaded extension's own command metadata.

Regenerate it with one command:

```bash
python scripts/generate_cli_reference.py
```

The repository hook regenerates and stages it on commit attempts, and CI fails if it drifts.

## Testing

Run the credential-free smoke test:

```bash
az sre --help
az extension show --name sre
```

Offline unit tests need no Azure credentials:

```bash
cd src/sre
python -m unittest discover -s azext_sre/tests -v
```

Live tests create and delete isolated Azure resources. Follow the setup and cleanup steps in
the [testing guide](docs/testing.md).

## Development

Install the tracked commit hook and the test dependencies:

```bash
git config core.hooksPath .githooks

cd src/sre
pip install azure-cli-core azure-cli-testsdk msrest azure-common build setuptools wheel
```

Most commands are generated from the `Microsoft.App/agents` API spec under
`azext_sre/aaz/latest/`. Don't edit those by hand. Hand-written behavior lives in
`azext_sre/custom.py`. See the [development guide](docs/development.md).

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

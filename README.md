# Azure SRE Agent CLI extension

`sre` is a private Azure CLI extension for creating and operating
`Microsoft.App/agents` (SRE Agent) resources. It manages the agent's control
plane: lifecycle, identity, networking, RBAC, data connectors, and runbook
extensions (tools, skills, scheduled tasks, and similar) under `az sre`.

> [!NOTE]
> This project is in early development. The command surface is not stable and
> is built/tested against real Azure resources by the author, not yet
> distributed as a release artifact.

> [!IMPORTANT]
> This extension follows the standard AAZ-generation-plus-hand-written-overlay
> pattern: generated recipes under `aaz/latest/...` cover
> plain ARM CRUD, and a thin `custom.py` overlay adds the behavior no Swagger
> spec can express (see [Implementation plan](PLAN.md) for why).

## Quick start

Sign in, create an agent, connect a repository and a data source, and check the agent.
Set your own values first:

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
  --data-connector-type KustoClient

az sre agent show \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --output table
```

A new connector links the data source but doesn't give the agent access to it. Grant
the agent's identity a reader role on the data source next (see the quickstart).

Clean up:

```bash
az sre agent delete \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --yes

az group delete \
  --subscription "$SUBSCRIPTION_ID" \
  --name "$RG" \
  --yes --no-wait
```
Run `az sre <command> --help` for required arguments and examples. The
[quickstart](docs/quickstart.md) covers data sources, access and incident routing, and the
[CLI reference](docs/cli-reference.md) lists every command.

## SRE Agent CLI Command Reference

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

Everything in this table is backed by the unit test suite described below, and
most rows have also been exercised against real Azure resources by hand. The
full syntax for every command — options, defaults, allowed values, examples —
is in the generated [CLI ergonomics reference](docs/cli-reference.md), which
is regenerated by a commit hook so it can't drift from this table.

## Testing

```bash
cd src/sre
python -m unittest discover -s azext_sre/tests -v
```

234 offline, credential-free tests cover every hand-written command in
`custom.py`: RBAC role-name and managed-resource-scope mapping, the networking
GET-merge-PUT logic, extension create/show/list/delete resource-ID and payload
shape, the base64/JSON extension-value codec, model-provider and
data-connector-type normalization, extension-type enum completeness,
file-path-based skill/repo-connect convenience flags, command registration,
arg-schema help regressions, and CLI-level argument enforcement
(invalid/missing arguments rejected by argparse before any handler runs) —
a standard pattern for Azure CLI extension test suites. See
[docs/testing.md](docs/testing.md) for the full coverage breakdown and the
live-verification workflow used on top of these unit tests.

GitHub Actions runs this same command on every push/PR (see
`.github/workflows/ci.yml`), checks that `docs/cli-reference.md` is not
stale, then builds and uploads a wheel artifact.

## Development

```bash
cd src/sre
pip install azure-cli-core azure-cli-testsdk build setuptools wheel
python -m unittest discover -s azext_sre/tests
```

Install the repository-tracked commit hook once per checkout (regenerates
and stages `docs/cli-reference.md` on every commit):

```bash
git config core.hooksPath .githooks
```

The generated AAZ recipes under `azext_sre/aaz/latest/` are produced from the
`Microsoft.App/agents` Swagger using `aaz-dev` and should not be hand-edited —
regenerate them instead. Everything hand-written lives in
`azext_sre/custom.py`, which `commands.py` auto-discovers by scanning
`vars(custom)` for `@register_command`-decorated classes. See [docs/development.md](docs/development.md) and
[docs/source-code.md](docs/source-code.md) for the full architecture
walkthrough, and [PLAN.md](PLAN.md) for the API versions pinned, why, plus
every architecture decision and its evidence.

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


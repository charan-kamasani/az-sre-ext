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
> This extension follows the same AAZ-generation-plus-hand-written-overlay
> pattern as `azext-aigateway`: generated recipes under `aaz/latest/...` cover
> plain ARM CRUD, and a thin `custom.py` overlay adds the behavior no Swagger
> spec can express (see [Implementation plan](PLAN.md) for why).

## Scope: control plane vs. data plane

This CLI only talks to the **control plane** — the ARM resource
`Microsoft.App/agents` and its child resources/proxy endpoints. It does not,
and will not, talk to the agent's own **data plane** (`sre.azure.com`
runtime) directly. See [Implementation plan](PLAN.md) for the full
control-plane/data-plane breakdown, including which features are
intentionally out of scope and why.

## Quick use

Every noun below is a flat top-level group directly under `az sre` — there is
no `az sre agent connector ...`-style nesting except where a resource
genuinely only exists inside another one (`az sre plugin marketplace`/
`az sre plugin install`). See [docs/cli-reference.md](docs/cli-reference.md)
for the complete, always-current list.

The shortest useful walkthrough creates a disposable agent, grants a
collaborator RBAC access to it, inspects its connection details, then removes
it.

```bash
SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
LOCATION="eastus2"
RG="rg-sre-demo"
AGENT="my-sre-agent"

az group create --subscription "$SUBSCRIPTION_ID" --name "$RG" --location "$LOCATION"

az sre agent create \
  --subscription "$SUBSCRIPTION_ID" \
  --resource-group "$RG" \
  --name "$AGENT" \
  --location "$LOCATION"
```

Grant a teammate a built-in role (see [`MANAGED_RESOURCE_ROLES`/`_ROLES`
in `custom.py`](src/sre/azext_sre/custom.py) for the full
`admin`/`user`/`author`/`reader` mapping — confirmed against real
`az role definition list` output, not the Portal's friendly labels):

```bash
az sre access grant \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --role user \
  --assignee someone@example.com
```

Inspect the agent's connection info and clean up:

```bash
az sre connection show --resource-group "$RG" --name "$AGENT"

az sre agent delete --resource-group "$RG" --name "$AGENT" --yes
az group delete --subscription "$SUBSCRIPTION_ID" --name "$RG" --yes --no-wait
```

## What's implemented today

| Group | Example commands | Status |
|---|---|---|
| `agent` | `create`/`show`/`list`/`update`/`delete`/`start`/`stop`/`wait` | Done, live-verified |
| `access` | `grant`/`revoke --role admin\|user\|author\|reader [--assignee\|--assignee-me]` | Done, live-verified, regression-tested |
| `managed-resource` | `grant`/`revoke`/`list` — grants the agent's own identity Reader + Monitoring Contributor on an external scope | Done, live-verified |
| `identity` | `assign`/`show`/`remove` (system/user-assigned) | Done, live-verified |
| `connection` | `show` — resolves the agent's data-plane URL | Done, live-verified |
| `usage` | `list [--daily]` — token/request usage stats | Done, live-verified |
| `network` | `update` (VNet injection, sandbox egress) | Done — hand-written against the real `2026-11-01-preview` api-version, no public Swagger exists for it yet |
| `connector` | `create`/`update`/`delete`/`list`/`show`/`list-secret` | Done, live-verified against a real Kusto cluster + Mcp/Knowledge connector types |
| `knowledge` | `create --type {file,text,webpage,repository}`/`show`/`list`/`delete` | Done, live-verified (file/text types; service redacts content on read-back, a documented service-side limitation) |
| `repo` | `connect` — one-step GitHub/Azure DevOps repo connect | Done, live-verified |
| `tool` / `skill` / `hook` / `instructions` | `create`/`show`/`list`/`delete` (`skill create` also supports `--file-path SKILL.md`) | Done, live-verified |
| `plugin marketplace` / `plugin install` | `create`/`show`/`list`/`delete` | Create/show live-verified; K8s-backed install provisioning not exercised in this sandbox |
| `extension` | `create`/`show`/`list`/`delete --extension-type {...}` | Generic escape hatch behind every noun above plus `subagents`, `scheduledTasks`, `incidentFilters`, `incidentHandlers`, `httpTriggers`, `globalSettings` (no dedicated noun yet) |
| `supported-agent-model` | `list --location <value>` | Done, live-verified |

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

180+ offline, credential-free tests cover every hand-written command in
`custom.py`: RBAC role-name and managed-resource-scope mapping, the networking
GET-merge-PUT logic, extension create/show/list/delete resource-ID and payload
shape, the base64/JSON extension-value codec, model-provider and
data-connector-type normalization, extension-type enum completeness,
file-path-based skill/repo-connect convenience flags, command registration,
arg-schema help regressions, and CLI-level argument enforcement
(invalid/missing arguments rejected by argparse before any handler runs) —
following the same pattern `azext-aigateway`'s own test suite uses. See
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
`vars(custom)` for `@register_command`-decorated classes (the same pattern
`azext-aigateway` uses). See [docs/development.md](docs/development.md) and
[docs/source-code.md](docs/source-code.md) for the full architecture
walkthrough, and [PLAN.md](PLAN.md) for the API versions pinned, why, plus
every architecture decision and its evidence.

## More documentation

| Guide | Use it for |
|---|---|
| [CLI ergonomics reference](docs/cli-reference.md) | Every group, command, exact syntax, option, and default — generated, never drifts |
| [Operations](docs/operations.md) | Agent lifecycle, RBAC, connectors, and confirmed/unconfirmed runbook extension payload shapes |
| [Networking](docs/networking.md) | VNet injection, sandbox egress, and safe sequencing for `network update` |
| [Testing](docs/testing.md) | Coverage layers and the live-verification workflow (rebuild/reinstall, throwaway agents, round-trip shape confirmation) |
| [Development](docs/development.md) | Architecture, local validation, CLI reference regeneration, commit hook |
| [Source code guide](docs/source-code.md) | Repository layout, generated vs. hand-authored code, how a command flows, security boundaries |
| [Implementation plan](PLAN.md) | Control-plane/data-plane scope, architecture decisions, evidence, roadmap, and open blockers |


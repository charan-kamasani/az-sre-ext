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

Grant a teammate the built-in "Standard User" role (see
[`GrantAccess._ROLES`](src/sre/azext_sre/custom.py) for the full
`admin`/`user`/`author`/`reader` mapping — confirmed against real
`az role definition list` output, not the Portal's friendly labels):

```bash
az sre agent grant-access \
  --resource-group "$RG" \
  --agent-name "$AGENT" \
  --role user \
  --assignee someone@example.com
```

Inspect the agent's connection info and clean up:

```bash
az sre agent get-connection --resource-group "$RG" --name "$AGENT"

az sre agent delete --resource-group "$RG" --name "$AGENT" --yes
az group delete --subscription "$SUBSCRIPTION_ID" --name "$RG" --yes --no-wait
```

## What's implemented today

| Area | Commands | Status |
|---|---|---|
| Agent lifecycle | `create`/`show`/`list`/`update`/`delete`/`start`/`stop`/`wait` | Done, live-verified |
| Identity | `agent identity assign`/`show`/`remove` | Done, live-verified |
| RBAC | `agent grant-access --role admin\|user\|author\|reader` | Done, live-verified, regression-tested |
| Connectors | `agent connector create`/`update`/`delete`/`list`/`show` | Done, live-verified against a real Kusto cluster |
| Usage | `agent get-connection`, `agent list-usage` | Done, live-verified |
| Networking | `agent update-network` (VNet injection, sandbox egress) | Done — hand-written against the real `2026-11-01-preview` api-version, no public Swagger exists for it yet |
| Runbook extensions | `agent extension create`/`show`/`list`/`delete` | Mechanism done; 12 of 15 extension types (`tools`, `skills`, `commonPrompts`, etc.) are expected to work and awaiting a live end-to-end test; the other 3 (`subagents`, `hooks`, `scheduledTasks`) are intentionally portal-only by Microsoft's own design — see [Implementation plan](PLAN.md) |

Everything in this table is backed by the unit test suite described below, and
most rows have also been exercised against real Azure resources by hand.

## Testing

```bash
cd src/sre
python -m unittest discover -s azext_sre/tests -v
```

27+ offline, credential-free tests cover every hand-written command in
`custom.py`: RBAC role-name mapping, the networking GET-merge-PUT logic,
extension create/show/list/delete resource-ID and payload shape, the
base64/JSON extension-value codec, model-provider normalization, extension-type
enum completeness, command registration, and CLI-level argument enforcement
(invalid/missing arguments rejected by argparse before any handler runs) —
following the same pattern `azext-aigateway`'s own test suite uses.

GitHub Actions runs this same command on every push/PR (see
`.github/workflows/ci.yml`), then builds and uploads a wheel artifact.

## Development

```bash
cd src/sre
pip install azure-cli-core azure-cli-testsdk build setuptools wheel
python -m unittest discover -s azext_sre/tests
```

The generated AAZ recipes under `azext_sre/aaz/latest/` are produced from the
`Microsoft.App/agents` Swagger using `aaz-dev` and should not be hand-edited —
regenerate them instead. Everything hand-written lives in
`azext_sre/custom.py`, which `commands.py` auto-discovers by scanning
`vars(custom)` for `@register_command`-decorated classes (the same pattern
`azext-aigateway` uses). See [Implementation plan](PLAN.md) for the full list
of API versions pinned and why, plus every architecture decision and its
evidence.

## More documentation

| Guide | Use it for |
|---|---|
| [Implementation plan](PLAN.md) | Control-plane/data-plane scope, architecture decisions, evidence, roadmap, and open blockers |

# Networking guide

`network update` configures VNet injection (outbound) and sandbox
egress for an SRE Agent. It is **hand-written, not generated** — there is
no public Swagger for the api-version that actually supports these fields
in production (`2026-11-01-preview`; see `NETWORK_API_VERSION` in
`custom.py`). It performs a real ARM read-modify-write (GET then full PUT,
matching the pattern the generated `agent update` command itself uses for
every other property), merging only the networking properties the caller
actually supplied and leaving everything else on the resource untouched.

## Inspect current networking configuration

> [!WARNING]
> `agent show`/`agent list` query ARM at the pinned, older
> `API_VERSION = "2026-01-01"` (see `custom.py`), which does not expose
> `sandboxConfiguration`/`vnetConfiguration` at all. Live-verified: setting
> `--sandbox-configuration` via `network update` succeeds (confirmed in the
> PUT's own response body, which is read at `NETWORK_API_VERSION =
> "2026-11-01-preview"`), but a subsequent `agent show` on the same agent
> returns `null` for both fields — not because the write was lost, but
> because `agent show` is reading the wrong api-version to see them. There
> is currently **no command in this CLI that can read back** a
> previously-set networking configuration. Use `az rest` directly against
> the preview api-version as a workaround until a dedicated `network show`
> (or an `update`-equivalent read) is added:
>
> ```bash
> az rest --method get \
>   --url "https://management.azure.com/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.App/agents/<name>?api-version=2026-11-01-preview" \
>   --query "properties.{sandbox:sandboxConfiguration, vnet:vnetConfiguration}"
> ```

There is no dedicated `network show` — networking fields are part of
the main agent resource body, and today only readable at the preview
api-version (see warning above).

## Configure sandbox egress

```bash
az sre network update -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Unrestricted}}"

az sre network update -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}"
```

## Configure VNet injection

Use a dedicated subnet prepared for this agent, delegated to
`Microsoft.App/environments`. The example assumes an existing VNet and
subnet in the agent's region; replace the network resource names with your
approved resources. Do not change the delegation of a shared or in-use
subnet.

```bash
NETWORK_RG="network-rg"
VNET="agent-vnet"
SUBNET="agent-subnet"

az network vnet subnet update -g "$NETWORK_RG" --vnet-name "$VNET" \
  --name "$SUBNET" --delegations Microsoft.App/environments

SUBNET_ID=$(az network vnet subnet show -g "$NETWORK_RG" --vnet-name "$VNET" \
  --name "$SUBNET" --query id -o tsv)

az sre network update -g myrg --agent-name myagent \
  --vnet-configuration "{subnet-resource-id:$SUBNET_ID}" \
  --sandbox-configuration "{egress:{mode:AzureVNet}}"
```

The VNet configuration and `AzureVNet` sandbox egress mode must be applied
together; the subnet ID alone is not sufficient. Subnet delegation is a
separate prerequisite and is not performed by `az sre network update`.

## Important sequencing note

`network update` is itself a long-running operation — the agent enters
`provisioningState: InProgress` while it applies. Any other mutating
command issued against the same agent while this is in flight will be
rejected with a clean `OperationConflict` error
(`"Agent '<name>' is currently being provisioned and cannot be created or
updated."`). Wait for completion before issuing the next command:

```bash
az sre agent wait -g myrg -n myagent --updated --timeout 300
```

## Validation evidence

The exact property shape (`sandboxConfiguration`/`vnetConfiguration`
nesting, field names) was read directly from the internal control-plane
source (`AAPT-SREAgent-ControlPlane`,
`src/WebApi/Views/Version20261101Preview/AgentView.cs`), not from any
public spec. Live-verified against a disposable test agent
(`sre-network-verify`): `network update --sandbox-configuration
"{egress:{mode:Unrestricted}}"` returned `201`, correctly flipped
`provisioningState` to `InProgress`, and its own response body (read at
`2026-11-01-preview`) showed `sandboxConfiguration.egress.mode:
"Unrestricted"` immediately. `agent wait --updated` correctly settled back
to `provisioningState: Succeeded`. However, a subsequent `agent show` read
`null` for the same field — confirmed via `--debug` to be because `agent
show` queries `api-version=2026-01-01`, not the preview version the write
used — not a lost write. Re-verify the write path against that source if
the service's shape ever changes; there is no codegen drift check possible
for a hand-maintained, unspecced api-version. See the read-back gap noted
above before trusting `agent show` for networking state.

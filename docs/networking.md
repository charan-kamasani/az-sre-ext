# Networking guide

`network update` configures VNet injection (outbound) and sandbox
egress for an SRE Agent. It is **hand-written, not generated** — there is
no public Swagger for the api-version that actually supports these fields
in production (`2026-11-01-preview`; see `NETWORK_API_VERSION` in
`custom.py`). It performs a real ARM read-modify-write (GET then full PUT,
matching the pattern the generated `agent update` command itself uses for
every other property), replacing only the networking objects the caller
supplied (`vnetConfiguration` or `sandboxConfiguration`, each as a whole)
and leaving everything else on the resource untouched.

## Inspect current networking configuration

```bash
az sre network show -g myrg --agent-name myagent
```

This returns the VNet injection and sandbox egress settings. `az sre agent show` omits them: the service returns them at `2026-01-01` too, but the generated `agent show` schema doesn't model these fields, so they're dropped from its output. Use `network show` to read them back.

A new agent starts with `Limited` egress and a service-managed default allow list: 45 hosts on 2026-11-10 (Azure management, Microsoft Graph, Log Analytics, Kusto, GitHub, Azure DevOps and similar), the `pypi`, `npmjs`, `nuget-org` and `ubuntu` registries, the `Github`, `AzureDevOps` and `GithubEnterprise` code repositories, and `allowHttpMcpServerNetworkAccess: true`. Its `vnetConfiguration.subnetResourceId` is `null`.

## Configure sandbox egress

```bash
az sre network update -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Unrestricted}}"

az sre network update -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}"
```

`--sandbox-configuration` replaces the agent's whole `sandboxConfiguration`.
Any field you leave out is cleared, and the service doesn't restore its
defaults. For example, the `Limited` command above leaves `example.com` as
the only allowed host and clears the default registries, code repositories
and `allowHttpMcpServerNetworkAccess`. To add a host and keep the rest,
start from the current settings:

```bash
az sre network show -g myrg --agent-name myagent --query sandboxConfiguration > sandbox.json
# Edit sandbox.json: add your hosts and remove the fields whose value is
# null (network update can't parse "httpProxy": null).
az sre network update -g myrg --agent-name myagent --sandbox-configuration @sandbox.json
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
`null` for the same field. That was not a lost write: `agent show` uses the
generated `2026-01-01` code, whose schema doesn't model the networking
fields, so they're dropped from its output. A raw `2026-01-01` GET on
2026-11-10 returned them unchanged. Re-verify the write path against that
source if the service's shape ever changes; there is no codegen drift check
possible for a hand-maintained, unspecced api-version. Use `network show` to
read networking state back instead of `agent show`.

`network show` was live-verified on 2026-11-10 against a disposable agent
in a throwaway resource group. Its `id`, `name`, `type`,
`provisioningState`, `vnetConfiguration` and `sandboxConfiguration`
matched a raw ARM GET at `2026-11-01-preview` exactly: for the new agent's
defaults, after both sandbox egress examples above, and after a 46-host
update built from `network show` output. It reported `InProgress` while an
update was applying. VNet injection was not exercised. The run found one
mismatch: `resourceGroup` was always `null`. ARM doesn't return that field,
and setting it to `null` also stopped the Azure CLI from filling it in from
`id`. Both `network show` and `network update` now derive it from the
resource ID.

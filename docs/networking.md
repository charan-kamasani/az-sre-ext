# Networking guide

`agent update-network` configures VNet injection (outbound) and sandbox
egress for an SRE Agent. It is **hand-written, not generated** — there is
no public Swagger for the api-version that actually supports these fields
in production (`2026-11-01-preview`; see `NETWORK_API_VERSION` in
`custom.py`). It performs a real ARM read-modify-write (GET then full PUT,
matching the pattern the generated `agent update` command itself uses for
every other property), merging only the networking properties the caller
actually supplied and leaving everything else on the resource untouched.

## Inspect current networking configuration

```bash
az sre agent show -g myrg -n myagent --query properties
```

There is no dedicated `agent network show` — networking fields are part of
the main agent resource body.

## Configure sandbox egress

```bash
az sre agent update-network -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Unrestricted}}"

az sre agent update-network -g myrg --agent-name myagent \
  --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}"
```

## Configure VNet injection

```bash
az sre agent update-network -g myrg --agent-name myagent \
  --vnet-configuration "{subnet-resource-id:/subscriptions/.../subnets/mysubnet}"
```

## Important sequencing note

`update-network` is itself a long-running operation — the agent enters
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
public spec, and has been live-verified end-to-end: a real
`update-network` call against a disposable test agent correctly flipped
`provisioningState` to `InProgress` then back to `Succeeded`, and the
applied sandbox configuration round-tripped on a subsequent `agent show`.
Re-verify against that source if the service's shape ever changes — there
is no codegen drift check possible for a hand-maintained, unspecced
api-version.

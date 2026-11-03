<!--
GENERATED FILE - DO NOT EDIT.
Regenerate with: python3 scripts/generate_cli_reference.py
-->

# `az sre` CLI ergonomics reference

> [!IMPORTANT]
> This file is generated from the loaded extension command, help, and
> argument metadata. Do not edit it manually. Regenerate it with
> `python3 scripts/generate_cli_reference.py`.

Public surface: **23 groups** and **70 commands**.

## Important caveats

- This CLI only talks to the control plane (`Microsoft.App/agents` ARM resource). It never talks to the agent's own data plane (`*.azuresre.ai`) directly. See the [implementation plan](../PLAN.md).
- The overall noun/verb shape (why `agent` isn't a wrapper for every other noun, why there's one dedicated noun per runbook-extension type instead of a generic `extension --type`) is a deliberate decision with alternatives considered -- see the [shape design doc](shape-design.md).
- `network update` is hand-written against the real `2026-11-01-preview` api-version; there is no public Swagger for it yet. See the [networking guide](networking.md).
- `--value` JSON documents (e.g. `tool create`, `skill create`, `agent settings update`) are base64-encoded and sent as-is to the agent's data plane. Each extension type has its own dedicated front-door noun (`tool`, `skill`, `hook`, `instructions`, `plugin marketplace`/`plugin install`, `repo connect`, `agent settings`); there is no generic `extension` escape hatch anymore. See the [operations guide](operations.md).
- `connector list-secret` is the only command that can return connector secret material in plain text; everything else (`connector show`, `connector list`, `connector create`/`update` responses) redacts secret fields server-side.

## Global options

These Azure CLI global options apply to every command and are not repeated in each syntax line.

| Option | Description |
| --- | --- |
| `--debug` | Increase logging verbosity to show all debug logs. |
| `--help, -h` | Show this help message and exit. |
| `--only-show-errors` | Only show errors, suppressing warnings. |
| `--output, -o` | Output format: json, jsonc, none, table, tsv, yaml, or yamlc. |
| `--query` | JMESPath query string. |
| `--subscription` | Subscription name or ID; otherwise use the active subscription. |
| `--verbose` | Increase logging verbosity. |

## `az sre`

Manage Azure SRE Agent resources -- the agent itself, what it can access, how it's customized, who can use it, and how it's doing.

Windows PowerShell note: inline JSON passed to any --value/--extended-properties/--default-model/etc. argument (e.g. --value '{"key": "value"}') is unreliable on powershell.exe/pwsh -- PowerShell does not pass embedded double quotes through to az.cmd intact for multi-word strings, so the command fails with a confusing "unrecognized arguments" error. This is a PowerShell/.cmd-wrapper quoting quirk, not an az sre bug. Workaround: write the JSON to a file and pass --value @path\to\file.json instead of inline JSON. See docs/operations.md's "Windows PowerShell: JSON quoting" section for the full explanation and more examples.

| Subgroup | Summary |
| --- | --- |
| `access` | Control who can manage or use an SRE Agent. |
| `agent` | Manage the core lifecycle of an SRE Agent resource. |
| `automation` | Manage agent automations. |
| `connector` | Connect an SRE Agent to an external data source it can query or act on. |
| `endpoint` | Resolve the URL used to actually talk to an SRE Agent's data plane. |
| `hook` | Manage lifecycle hooks that run a prompt or script at a specific agent event. |
| `identity` | Manage the SRE Agent's own managed identity, used for its Azure RBAC-gated calls. |
| `incident-filter` | Manage incident filters (portal: Incidents > "Triggers & response |
| `instructions` | Manage the agent's always-on custom instructions. |
| `knowledge` | Add files or web pages the agent can read and reason over. |
| `managed-resource` | Let the agent's own managed identity monitor resources outside its own resource group. |
| `network` | Control an SRE Agent's sandbox networking (preview). |
| `plugin` | Manage community plugins that add skills, tools, and integrations. |
| `repo` | Connect a code repository so the agent can read source during investigations. |
| `skill` | Manage custom skills -- specialized capabilities the agent can use. |
| `tool` | Manage custom tools the agent can call. |
| `usage` | Read an SRE Agent's usage and billing stats. |

## `az sre access`

Control who can manage or use an SRE Agent.

Grants or revokes a built-in RBAC role (admin, user, author, or reader) on the agent itself, for a specific person, group, or service principal. Use 'sre access grant' to add someone, 'sre access list' to see who currently has access, and 'sre access revoke' to remove them. This is the mirror image of 'sre managed-resource', which grants the agent's own identity access to things outside itself -- not other people access to the agent.

| Verb | Exact syntax |
| --- | --- |
| `grant` | `az sre access grant --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |
| `list` | `az sre access list --name <value> --resource-group <value>` |
| `revoke` | `az sre access revoke --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |

### `az sre access grant`

Grant a built-in SRE Agent RBAC role to a user, group, or principal.

Thin convenience wrapper over 'az role assignment create' that builds the agent's full resource-ID scope for you (see running notes section 0's "Role assignment" row) -- not a new ARM operation, just a shortcut so callers do not need to construct the scope string by hand. Pass --assignee-me to grant yourself access without looking up your own object ID first.

**Syntax**

`az sre access grant --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to grant access on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--role` | String | Yes |  | `admin`, `user`, `author`, `reader` | Built-in role to grant: 'admin', 'user', 'author', or 'reader'. |
| `--assignee` | String | No |  |  | User, group, or service principal object ID/UPN to grant the role for. Required unless --assignee-me is passed instead. |
| `--assignee-me` | Boolean | No |  | `false`, `true` | Use the signed-in user as the assignee, resolved via 'az ad signed-in-user show'. Alternative to --assignee. |

**Examples**

- Grant yourself admin access to an agent

  `az sre access grant --name myagent --resource-group myrg --role admin --assignee-me`
- Grant a user read-only access

  `az sre access grant --name myagent --resource-group myrg --role reader --assignee someone@contoso.com`

### `az sre access list`

List who currently has access to an SRE Agent -- every role

assignment scoped to the agent itself, across all four built-in roles (admin, user, author, reader). Thin convenience wrapper over 'az role assignment list --scope <agent-resource-id>' (the agent's own resource ID, resolved for you via 'sre agent show'), the same way 'access grant'/'access revoke' build that scope automatically.

**Syntax**

`az sre access list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to list access on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List everyone with access to an agent

  `az sre access list --name myagent --resource-group myrg`

### `az sre access revoke`

Revoke a built-in SRE Agent RBAC role from a user, group, or principal.

Mirrors 'access grant': thin convenience wrapper over 'az role assignment delete' that builds the agent's full resource-ID scope for you, so callers do not need to construct the scope string (or look up their own object ID, via --assignee-me) by hand.

**Syntax**

`az sre access revoke --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to revoke access on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--role` | String | Yes |  | `admin`, `user`, `author`, `reader` | Built-in role to revoke: 'admin', 'user', 'author', or 'reader'. |
| `--assignee` | String | No |  |  | User, group, or service principal object ID/UPN to revoke the role for. Required unless --assignee-me is passed instead. |
| `--assignee-me` | Boolean | No |  | `false`, `true` | Use the signed-in user as the assignee, resolved via 'az ad signed-in-user show'. Alternative to --assignee. |

**Examples**

- Revoke a user's access to an agent

  `az sre access revoke --name myagent --resource-group myrg --role user --assignee someone@contoso.com`

## `az sre agent`

Manage the core lifecycle of an SRE Agent resource.

Create, show, list, update, delete, start, and stop an agent.

| Subgroup | Summary |
| --- | --- |
| `settings` | Manage an SRE Agent's global settings (preview). |

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre agent create [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>] [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] --location <value> [--tags <json-or-@file>] [--grant-access-to-me {admin,user,author,reader}]` |
| `delete` | `az sre agent delete [--no-wait] --name <value> --resource-group <value> [--yes]` |
| `list` | `az sre agent list [--next-token <value>] [--max-items <value>] [--resource-group <value>]` |
| `list-models` | `az sre agent list-models [--next-token <value>] [--max-items <value>] --location <value>` |
| `show` | `az sre agent show --name <value> --resource-group <value>` |
| `start` | `az sre agent start [--no-wait] --name <value> --resource-group <value>` |
| `stop` | `az sre agent stop [--no-wait] --name <value> --resource-group <value>` |
| `update` | `az sre agent update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --name <value> --resource-group <value> [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] [--tags <json-or-@file>]` |
| `wait` | `az sre agent wait --name <value> --resource-group <value>` |

### `az sre agent create`

Create an SRE Agent.

If neither --mi-system-assigned nor --mi-user-assigned is passed, this matches the Azure Portal's own default: it creates a brand-new Microsoft.ManagedIdentity/userAssignedIdentities resource for you and enables both system-assigned and user-assigned identities on the agent (identity.type = "SystemAssigned, UserAssigned"). Pass --mi-system-assigned/--mi-user-assigned explicitly to opt out of the auto-created identity.

**Syntax**

`az sre agent create [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>] [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] --location <value> [--tags <json-or-@file>] [--grant-access-to-me {admin,user,author,reader}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |
| `--action-configuration` | Object | No |  |  | Configuration for action |
| `--agent-identity` | Object | No |  |  | Agent identity configuration for accessing resources |
| `--default-model` | Object | No |  |  | Default AI model configuration for the agent |
| `--incident-management-configuration` | Object | No |  |  | Incident management configurations |
| `--knowledge-graph-configuration` | Object | No |  |  | Knowledge graph configuration for agent |
| `--log-configuration` | Object | No |  |  | Log configurations |
| `--upgrade-channel` | String | No |  | `Preview`, `Stable` | The upgrade channel of the agent |
| `--location`, `-l` | String | Yes |  |  | The geo-location where the resource lives |
| `--tags` | Dictionary | No |  |  | Resource tags. |
| `--grant-access-to-me` | String | No |  | `admin`, `user`, `author`, `reader` | Grant the signed-in user a built-in SRE Agent role immediately after creating the agent: 'admin', 'user', 'author', or 'reader'. Resolves your object ID via 'az ad signed-in-user show' automatically -- equivalent to running 'sre access grant --assignee <your-object-id>' as a separate, manual follow-up command. Cannot be combined with --no-wait (the grant runs in post_operations, which the no-wait code path never reaches). |

**Examples**

- Create an agent with an Anthropic default model

  `az sre agent create --name myagent --resource-group myrg \ --location eastus2 --default-model "{provider:anthropic,name:automatic}"`

### `az sre agent delete`

Delete an SRE Agent.

**Syntax**

`az sre agent delete [--no-wait] --name <value> --resource-group <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre agent list`

List SRE Agents in a subscription or resource group.

**Syntax**

`az sre agent list [--next-token <value>] [--max-items <value>] [--resource-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--resource-group`, `-g` | String | No |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent list-models`

List the model providers/names supported for new SRE Agents in a region.

Use this before 'sre agent create' to confirm --default-model is supported in the region you're deploying to.

**Syntax**

`az sre agent list-models [--next-token <value>] [--max-items <value>] --location <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--location`, `-l` | String | Yes |  |  | Location. Values from: `az account list-locations`. You can configure the default location using `az configure --defaults location=<location>`. |

**Examples**

- See which models are available in East US

  `az sre agent list-models --location eastus`

### `az sre agent show`

Show the details of an SRE Agent.

**Syntax**

`az sre agent show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent start`

Start a stopped SRE Agent.

**Syntax**

`az sre agent start [--no-wait] --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent stop`

Stop a running SRE Agent.

**Syntax**

`az sre agent stop [--no-wait] --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent update`

Update an SRE Agent.

**Syntax**

`az sre agent update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --name <value> --resource-group <value> [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] [--tags <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--add` | String | No |  |  | Add an object to a list of objects by specifying a path and key value pairs. Example: `--add property.listProperty <key=value, string or JSON string>` |
| `--set` | String | No |  |  | Update an object by specifying a property path and value to set. Example: `--set property1.property2=<value>` |
| `--remove` | String | No |  |  | Remove a property or an element from a list. Example: `--remove property.list <indexToRemove>` OR `--remove propertyToRemove` |
| `--force-string` | String | No |  | `true`, `t`, `yes`, `y`, `1`, `false`, `f`, `no`, `n`, `0` | When using 'set' or 'add', preserve string literals instead of attempting to convert to JSON. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--action-configuration` | Object | No |  |  | Configuration for action |
| `--agent-identity` | Object | No |  |  | Agent identity configuration for accessing resources |
| `--default-model` | Object | No |  |  | Default AI model configuration for the agent |
| `--incident-management-configuration` | Object | No |  |  | Incident management configurations |
| `--knowledge-graph-configuration` | Object | No |  |  | Knowledge graph configuration for agent |
| `--log-configuration` | Object | No |  |  | Log configurations |
| `--upgrade-channel` | String | No |  | `Preview`, `Stable` | The upgrade channel of the agent |
| `--tags` | Dictionary | No |  |  | Resource tags. |

### `az sre agent wait`

Place the CLI in a waiting state until a condition is met.

**Syntax**

`az sre agent wait --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

## `az sre automation`

Manage agent automations.

Covers scheduled tasks (run the agent on a timer) and HTTP triggers (run the agent from an inbound webhook) -- confirmed against the portal's own "Automation" tab, which holds exactly these two things. Incident filters live under 'az sre incident-filter' instead (portal: Incidents > "Triggers & response plans" -- a different top-level section, not Automation; confirmed by walking the live portal nav). Subagents are CONFIRMED NOT buildable here: the portal's real "Create a custom agent" dialog bypasses the ARM extensions proxy entirely and PUTs a raw YAML document (kind: AgentConfiguration) straight to the agent's data-plane 'api/v1/extendedAgent/apply' endpoint -- a route this ARM-only CLI never reaches (confirmed live: 'extension create --extension-type subagents' does reach the data plane's ARM-proxied ExtendedAgentView route, but that is the wrong/ unsupported schema and is rejected). Use the portal or srectl to create subagents instead. Release triggers, S360 triggers, and incident retrospectives are data-plane-only features of the agent's own runtime (confirmed via sreagent-runtime's Agent.Web v1 controllers) with no corresponding ARM resource -- they are out of scope for this ARM-based control-plane CLI entirely.

| Subgroup | Summary |
| --- | --- |
| `http-trigger` | Manage HTTP triggers: run the agent against a prompt from an inbound |
| `scheduled-task` | Manage scheduled tasks: run the agent on a timer (cron) against a |

## `az sre connector`

Connect an SRE Agent to an external data source it can query or act on.

Supports Azure Data Explorer/Kusto (direct or via the Azure MCP server), the generic MCP server type (portal name: 'MCP server', a.k.a. 'User provided connector' -- GitHub, PagerDuty, ServiceNow, and other MCP-compatible endpoints), Office 365 Outlook, Microsoft Teams, IcM connector (incident management), DGrep, Log Analytics Workspace, EV2, Geneva Metrics, S360 connector, Documentation connector, and knowledge sources (text/file/web page/repository). Use 'sre connector create' to add one, 'sre connector list'/'sre connector show' to see what's connected (including OAuth consent status for connectors that need a sign-in). Note: this only covers the fixed, ARM-reachable connector catalog listed above. The portal's much larger "Additional connectors" catalog (Gmail, Yammer, OneDrive, SharePoint, Box, Power BI, Confluence, and 20+ others, almost all marked Preview) is a real, separate Connector Gateway platform the agent also integrates with, but it has no public control-plane API yet -- those connectors can only be created through the portal today, not this CLI. See docs/operations.md.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}] [--tool-access {false,true}]` |
| `delete` | `az sre connector delete [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--yes]` |
| `list` | `az sre connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>` |
| `list-secret` | `az sre connector list-secret --agent-name <value> --name <value> --resource-group <value>` |
| `show` | `az sre connector show --agent-name <value> --name <value> --resource-group <value>` |
| `update` | `az sre connector update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>]` |

### `az sre connector create`

Create an Agent Connector.

**Syntax**

`az sre connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}] [--tool-access {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-connector-type` | String | No |  |  | Type of the data connector. Portal display name shown first, wire/API value in parentheses (both accepted, case-insensitive): 'Azure Data Explorer' (KustoClient -- the default type, matching the portal's own 'Azure Data Explorer' option exactly; no --data-source needed), 'Azure Data Explorer Cluster' (Kusto -- legacy, pinned to one cluster via --data-source, no portal entry point), 'MCP server' (Mcp, a.k.a. 'User provided connector' -- possibly also PagerDuty/ServiceNow/etc. via a custom endpoint, not a separate type; note Datadog/Splunk/S360/EV2 have their own dedicated portal cards and may not actually route through this generic type -- unverified), 'Office 365 Outlook' (Outlook), 'Microsoft Teams' (Teams), 'IcM connector' (Icm, a.k.a. 'Microsoft IcM', singleton per agent), 'DGrep' (Dgrep, a.k.a. 'Microsoft DGrep', singleton per agent), 'Log Analytics Workspace' (LogAnalytics), 'EV2' (Ev2Mcp), 'Geneva Metrics' (GenevaMetrics -- restricted to Microsoft's 13 known first-party tenants, matching the portal's own connector-picker gate), 'S360 connector' (S360), 'Documentation connector' (Documentation), 'Database query connector (user)' (KustoUser -- correlation not create-and-inspect confirmed), 'Database indexing connector' (KustoDataIndexer -- same caveat), 'Azure DevOps AI Search' (AzureDevOpsBuiltinMcp -- same caveat), and four knowledge-item types that need --extended-properties instead of --data-source: 'KnowledgeText', 'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository' (none of these four appear in the portal's Connectors picker -- they live in a separate portal section). Also accepts 'TsgCrawler', 'ConnectorGateway', 'AzureMonitor', 'MonitorClient' (no portal picker card found for any of these), and one of 'AppInsights'/'ApplicationInsights' (the portal shows a single 'Application Insights' card, but which of these two wire values it persists as is not yet confirmed -- both are accepted here). |
| `--data-source` | String | No |  |  | Data source connection string or endpoint. For 'Kusto' (Azure Data Explorer Cluster), this must include a database name, e.g. 'https://cluster.kusto.windows.net/databasename' -- a bare cluster URL with no database is rejected server-side with 'Kusto DataSource must include a database name'. |
| `--endpoint` | String | No |  |  | Endpoint of the connector |
| `--extended-properties` | Dictionary | No |  |  | Additional properties for the data connector which can be used to store custom key-value pairs |
| `--identity` | String | No |  |  | Identity used to access the data source |
| `--file-path` | String | No |  |  | Local file to ingest, instead of hand-building --extended-properties yourself. For --data-connector-type KnowledgeFile, the CLI reads and base64-encodes the file into extended-properties.fileContent/fileName. For KnowledgeText, the CLI reads the file as UTF-8 text into extended-properties.content. |
| `--mcp-endpoint` | String | No |  |  | For --data-connector-type Mcp: the MCP server's HTTP endpoint URL. Builds both --data-source and the nested extended-properties.transport/endpoint the service actually requires (confirmed live: a bare --data-source alone is rejected with 'Endpoint value is required for MCP connector with HTTP transport.'). |
| `--github` | Boolean | No |  | `false`, `true` | For --data-connector-type Mcp: shortcut for --mcp-endpoint pointed at the real public GitHub Copilot MCP server (https://api.githubcopilot.com/mcp/). |
| `--tool-access` | Boolean | No |  | `false`, `true` | For --data-connector-type KustoClient/'Azure Data Explorer': shortcut for the portal's 'Allow agent to use query tools from this connector' checkbox (Review + add step). Builds extended-properties.toolsVisibleToMetaAgent -- true sets it to ['*'], false to [] (confirmed live: both values persist and read back correctly). |

**Examples**

- Connect an agent to Azure Data Explorer -- matches the portal's

  `"Add connector" > "Azure Data Explorer" flow exactly: just a name and type, no --data-source or --mcp-endpoint needed (uses the agent's system-assigned identity by default, same as the portal) az sre connector create --agent-name myagent --resource-group myrg \ --name azure-data-explorer --data-connector-type "Azure Data Explorer"`
- Same, but with a user-assigned identity (portal's "Add identity")

  `az sre connector create --agent-name myagent --resource-group myrg \ --name azure-data-explorer --data-connector-type "Azure Data Explorer" \ --identity /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity>`
- Connect an agent's GitHub MCP connector using your own gh auth

  `az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp --data-connector-type Mcp --github true`

### `az sre connector delete`

Delete an Agent Connector.

**Syntax**

`az sre connector delete [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre connector list`

List an SRE Agent's Connectors, including OAuth consent status

(consentStatus: Consented/PendingConsent) for EntraOAuth-backed Mcp connectors.

**Syntax**

`az sre connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre connector list-secret`

Get a Data Connector's details including its secret(s) in plain text.

Unlike 'sre connector show'/'sre connector list', which redact secret fields server-side, this command returns them unredacted.

**Syntax**

`az sre connector list-secret --agent-name <value> --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Read back a Kusto connector's secret after creating it

  `az sre connector list-secret --agent-name myagent --resource-group myrg --name conn-kusto`

### `az sre connector show`

Show the details of an Agent Connector, including OAuth consent

status (consentStatus: Consented/PendingConsent) for EntraOAuth-backed Mcp connectors. If PendingConsent, a warning is printed with a portal link to finish the sign-in -- the CLI cannot complete OAuth consent itself, since the service only exposes it as an interactive browser flow, not a public ARM action.

**Syntax**

`az sre connector show --agent-name <value> --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre connector update`

Update an Agent Connector.

**Syntax**

`az sre connector update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--add` | String | No |  |  | Add an object to a list of objects by specifying a path and key value pairs. Example: `--add property.listProperty <key=value, string or JSON string>` |
| `--set` | String | No |  |  | Update an object by specifying a property path and value to set. Example: `--set property1.property2=<value>` |
| `--remove` | String | No |  |  | Remove a property or an element from a list. Example: `--remove property.list <indexToRemove>` OR `--remove propertyToRemove` |
| `--force-string` | String | No |  | `true`, `t`, `yes`, `y`, `1`, `false`, `f`, `no`, `n`, `0` | When using 'set' or 'add', preserve string literals instead of attempting to convert to JSON. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-connector-type` | String | No |  |  | Type of the data connector. Portal display name shown first, wire/API value in parentheses (both accepted, case-insensitive): 'Azure Data Explorer' (KustoClient -- the default type, matching the portal's own 'Azure Data Explorer' option exactly; no --data-source needed), 'Azure Data Explorer Cluster' (Kusto -- legacy, pinned to one cluster via --data-source, no portal entry point), 'MCP server' (Mcp, a.k.a. 'User provided connector' -- possibly also PagerDuty/ServiceNow/etc. via a custom endpoint, not a separate type; note Datadog/Splunk/S360/EV2 have their own dedicated portal cards and may not actually route through this generic type -- unverified), 'Office 365 Outlook' (Outlook), 'Microsoft Teams' (Teams), 'IcM connector' (Icm, a.k.a. 'Microsoft IcM', singleton per agent), 'DGrep' (Dgrep, a.k.a. 'Microsoft DGrep', singleton per agent), 'Log Analytics Workspace' (LogAnalytics), 'EV2' (Ev2Mcp), 'Geneva Metrics' (GenevaMetrics -- restricted to Microsoft's 13 known first-party tenants, matching the portal's own connector-picker gate), 'S360 connector' (S360), 'Documentation connector' (Documentation), 'Database query connector (user)' (KustoUser -- correlation not create-and-inspect confirmed), 'Database indexing connector' (KustoDataIndexer -- same caveat), 'Azure DevOps AI Search' (AzureDevOpsBuiltinMcp -- same caveat), and four knowledge-item types that need --extended-properties instead of --data-source: 'KnowledgeText', 'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository' (none of these four appear in the portal's Connectors picker -- they live in a separate portal section). Also accepts 'TsgCrawler', 'ConnectorGateway', 'AzureMonitor', 'MonitorClient' (no portal picker card found for any of these), and one of 'AppInsights'/'ApplicationInsights' (the portal shows a single 'Application Insights' card, but which of these two wire values it persists as is not yet confirmed -- both are accepted here). |
| `--data-source` | String | No |  |  | Data source connection string or endpoint. For 'Kusto' (Azure Data Explorer Cluster), this must include a database name, e.g. 'https://cluster.kusto.windows.net/databasename' -- a bare cluster URL with no database is rejected server-side with 'Kusto DataSource must include a database name'. |
| `--endpoint` | String | No |  |  | Endpoint of the connector |
| `--extended-properties` | Dictionary | No |  |  | Additional properties for the data connector which can be used to store custom key-value pairs |
| `--identity` | String | No |  |  | Identity used to access the data source |

## `az sre endpoint`

Resolve the URL used to actually talk to an SRE Agent's data plane.

Every agent has a control-plane (ARM) resource and a separate data-plane endpoint it runs on. Use 'sre endpoint show' to look up and save that live endpoint -- for example, before calling the agent directly or configuring another tool to talk to it.

| Verb | Exact syntax |
| --- | --- |
| `show` | `az sre endpoint show --name <value> --resource-group <value> [--data-plane-audience <value>]` |

### `az sre endpoint show`

Resolve and save an SRE Agent's data-plane connection.

Reads the agent's control-plane resource (ARM), extracts the 'agentEndpoint' property (the data-plane base URL, pattern 'https://{name}--{id}.{hash}.{region}.azuresre.ai' -- see running notes section 1a), and writes it to a local connections file for the separate, standalone data-plane 'sre' CLI to read. Mirrors 'az aks get-credentials' writing kubeconfig for kubectl: the control plane and data plane are two different CLIs/binaries by design (see running notes section 1), and this command is their only bridge. Renamed from 'sre connection show' to 'sre endpoint show' per live naming feedback: seeing 'connection' and 'connector' listed next to each other in the command reference was a guaranteed source of confusion, and this command is really just resolving the agent's endpoint URL.

**Syntax**

`az sre endpoint show --name <value> --resource-group <value> [--data-plane-audience <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to connect to. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-plane-audience` | String | No | https://azuresre.dev |  | Audience used to request the data-plane access token. The data plane uses a separate token from the control plane -- see running notes section 1a. |

**Examples**

- Resolve and save the data-plane endpoint for an agent

  `az sre endpoint show --agent-name myagent --resource-group myrg`

## `az sre hook`

Manage lifecycle hooks that run a prompt or script at a specific agent event.

Fires on one of four events (Start, PreToolUse, PostToolUse, Stop) and runs either an LLM prompt or a bash/Python command. See 'sre hook create -h' for the full --value shape and the portal-vs-API note.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre hook create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre hook delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre hook list --name <value> --resource-group <value>` |
| `show` | `az sre hook show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre hook create`

Create or update a hook.

**Syntax**

`az sre hook create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Hook configuration as a JSON document, e.g. {"eventType": "Stop", "activationMode": "always", "description": "...", "hook": {"type": "prompt", "prompt": "..."}} -- top-level fields: eventType ("Start", "PreToolUse", "PostToolUse", or "Stop"; the portal UI only offers the latter two today)/activationMode ("always" or "onDemand", lowercase)/description, plus a nested "hook" object: type ("prompt" or "command")/prompt/command/script/matcher/model/timeout/failMode ("Allow" or "Block" -- what happens if the hook itself errors/times out, not its decision)/maxRejections/sources. Live-confirmed shape -- do not put hookType/prompt at the top level, they must be nested under "hook". IMPORTANT: --value.hook.matcher (a tool-name regex, e.g. "Bash.*") is required when eventType is "PreToolUse" or "PostToolUse" -- the real API rejects an otherwise-identical payload without it; not required for "Start"/"Stop". |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Create a prompt-based hook that runs after every Bash tool call (live-verified payload)

  `az sre hook create --agent-name myagent --resource-group myrg --name post-tool-check \ --value '{"eventType": "PostToolUse", "activationMode": "always", "description": "Flag risky commands", "hook": {"type": "prompt", "prompt": "Review the last tool call. If it looks destructive, warn the user.", "matcher": "Bash.*", "failMode": "Allow"}}'`
- Create a command-based hook that runs after every Bash tool call (live-verified payload)

  `az sre hook create --agent-name myagent --resource-group myrg --name post-tool-echo \ --value '{"eventType": "PostToolUse", "activationMode": "always", "description": "Blocks dangerous commands", "hook": {"type": "command", "command": "echo ok", "matcher": "Bash.*", "timeout": 30, "failMode": "Allow"}}'`

### `az sre hook delete`

Delete a hook.

**Syntax**

`az sre hook delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre hook list`

List hooks.

**Syntax**

`az sre hook list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre hook show`

Show a hook.

**Syntax**

`az sre hook show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre identity`

Manage the SRE Agent's own managed identity, used for its Azure RBAC-gated calls.

A managed identity is the credential the agent itself runs as when it calls Azure APIs on your behalf (for example, to read a monitored resource). Use 'sre identity assign' to turn one on (system-assigned and/or user-assigned), 'sre identity show' to see what's assigned, and 'sre identity remove' to turn it off. Not to be confused with 'sre access' (who can manage/use the agent) or 'sre repo connect' (repo auth).

| Verb | Exact syntax |
| --- | --- |
| `assign` | `az sre identity assign [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `remove` | `az sre identity remove [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `show` | `az sre identity show --name <value> --resource-group <value>` |

### `az sre identity assign`

Assign a system- and/or user-assigned managed identity to an SRE Agent.

**Syntax**

`az sre identity assign [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |

**Examples**

- Turn on the agent's system-assigned identity

  `az sre identity assign --agent-name myagent --resource-group myrg --system-assigned`
- Assign one or more user-assigned identities

  `az sre identity assign --agent-name myagent --resource-group myrg \ --user-assigned "/subscriptions/.../resourceGroups/myrg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/myid"`

### `az sre identity remove`

Remove a system- and/or user-assigned managed identity from an SRE Agent.

**Syntax**

`az sre identity remove [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |

**Examples**

- Turn off the agent's system-assigned identity

  `az sre identity remove --agent-name myagent --resource-group myrg --system-assigned`

### `az sre identity show`

Show the managed identity (-ies) currently assigned to an SRE Agent.

**Syntax**

`az sre identity show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

## `az sre incident-filter`

Manage incident filters (portal: Incidents > "Triggers & response

plans"): match incoming incidents by platform/title/team/etc. and route matches to a handling agent. Incident handlers are a legacy predecessor to incident filters that the service itself is migrating away from (confirmed via its own 'DeleteLegacyIncidentHandlerDocument'/'MigrateLegacyIncidentHandler' admin actions) -- intentionally not exposed here to avoid steering anyone onto a deprecated path. Note: live create against a fresh sandbox agent was rejected in our testing with a generic "extension configuration is invalid" error even with a matching data connector configured -- this is consistent with needing real IcM/PagerDuty team-identity resolution the sandbox tenant doesn't have, not a shape problem (the same payload shape is used successfully by the service's own PagerDutySetupFixture.cs/ IcmSetupFixture.cs E2E tests). See _validate_incident_filters_shape in this file for the shape-level validation that does run locally.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre incident-filter create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre incident-filter delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre incident-filter list --name <value> --resource-group <value>` |
| `show` | `az sre incident-filter show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre incident-filter create`

Create or update an incident filter.

**Syntax**

`az sre incident-filter create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Incident filter configuration as a JSON document. Fields: "incidentPlatform" ("Icm", "AzMonitor", "PagerDuty", "ServiceNow"), "impactedService", "priorities" (array), "incidentTypes" (array; singular "incidentType" still accepted for compatibility), "alertId", "titleContains" (a single substring) OR "titleContainsAll"/"titleContainsAny" (arrays, AND/OR logic -- mutually exclusive with titleContains), "titleNotContains" (array; excludes a match even if other criteria hit, useful for a catch-all filter that should skip incidents already handled by a more specific filter), "agentMode", "handlingAgents" (array; singular "handlingAgent" still accepted), "owningTeamIds" (array; singular "owningTeamId" still accepted), "maxAutomatedInvestigationAttempts" (int -- after this many failed automated RCA attempts on a recurring alert, the agent asks the user for input instead of retrying forever), "mergeEnabled"/"mergeWindowHours" (AzMonitor-only: re-firing alerts merge into the existing thread instead of starting a new investigation, within a 1-24 hour cooldown window), "isEnabled", "icmFilterSettings" (Icm-only object: "monitorIds" (array), "createdBys" (array), "customField": {"customFieldId": <int>, "stringValue": <string>}, "assignableOnly"/"withOnCallRotationsOnly" (bool), "triggerEvents" (array, e.g. "IncidentCreatedOrTransferred", "DiscussionEntry", "IncidentMitigated", "IncidentReactivated", "IncidentResolved", "HitCountIncreased", "IncidentSeverityChanged" -- defaults to ["IncidentCreatedOrTransferred"]), "discussionEntryAuth" ("OnCallOnly" default, "TeamMembers", "AllowlistOnly"), "discussionEntryAllowlist" (array, additive on top of discussionEntryAuth)), "azMonitorFilterSettings" (AzMonitor-only object: "targetResourceType", "targetResource"). Example: {"incidentPlatform": "Icm", "titleContains": "disk space", "handlingAgents": ["storage-oncall-agent"], "isEnabled": true}. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre incident-filter delete`

Delete an incident filter.

**Syntax**

`az sre incident-filter delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre incident-filter list`

List incident filters.

**Syntax**

`az sre incident-filter list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre incident-filter show`

Show an incident filter.

**Syntax**

`az sre incident-filter show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre instructions`

Manage the agent's always-on custom instructions.

A single free-text block (up to 16384 bytes) appended to the agent's default system prompt.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre instructions create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre instructions delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre instructions list --name <value> --resource-group <value>` |
| `show` | `az sre instructions show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre instructions create`

Create or update the agent's custom instructions.

There is only one instructions block per agent; use the same --name (e.g. "default") each time to update it in place, or pass --overwrite to replace an existing one.

**Syntax**

`az sre instructions create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Instructions as a JSON document of the form {"prompt": "..."} -- the "prompt" field holds the free text (confirmed live round-trip). |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre instructions delete`

Delete the agent's custom instructions.

**Syntax**

`az sre instructions delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre instructions list`

List the agent's custom instructions entries.

**Syntax**

`az sre instructions list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre instructions show`

Show the agent's custom instructions.

**Syntax**

`az sre instructions show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre knowledge`

Add files or web pages the agent can read and reason over.

Use 'sre knowledge create --type file' or '--type webpage' to add one. Repository knowledge sources use 'sre repo connect' instead.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre knowledge create --agent-name <value> --resource-group <value> --name <value> --type {file,text,webpage,repository} [--file-path <value>] [--url <value>] [--data-source <value>] [--overwrite {false,true}]` |
| `delete` | `az sre knowledge delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre knowledge list --name <value> --resource-group <value>` |
| `show` | `az sre knowledge show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre knowledge create`

Add a knowledge source (file or web page) to an SRE Agent.

**Syntax**

`az sre knowledge create --agent-name <value> --resource-group <value> --name <value> --type {file,text,webpage,repository} [--file-path <value>] [--url <value>] [--data-source <value>] [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n` | String | Yes |  |  | Name of this knowledge source. |
| `--type` | String | Yes |  | `file`, `text`, `webpage`, `repository` | Kind of knowledge source. One of: file, repository, text, webpage. |
| `--file-path` | String | No |  |  | Local file to ingest. Required for --type file/text. |
| `--url` | String | No |  |  | Web page URL to ingest. Required for --type webpage. Live-confirmed wire shape: forwarded as extended-properties url=<url> only (never --data-source, which the service rejects with a 500 for this connector type). |
| `--data-source` | String | No |  |  | Raw --data-source passthrough, for --type repository or any case --file-path/--url don't cover. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing knowledge source of the same name. |

**Examples**

- Add a local file as a knowledge source

  `az sre knowledge create --agent-name myagent --resource-group myrg \ --name runbook-md --type file --file-path ./runbook.md`
- Add a web page as a knowledge source

  `az sre knowledge create --agent-name myagent --resource-group myrg \ --name docs-site --type webpage --url https://learn.microsoft.com/azure/`

### `az sre knowledge delete`

Remove a knowledge source.

**Syntax**

`az sre knowledge delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n` | String | Yes |  |  | Name of the knowledge source. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre knowledge list`

List an SRE Agent's knowledge sources (files and web pages).

Self-invokes 'sre connector list' (knowledge items are connectors under the hood -- see module comment above) and filters to just the Knowledge* dataConnectorType values, so non-knowledge connectors (Kusto/Mcp/etc.) configured on the same agent don't show up here.

**Syntax**

`az sre knowledge list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre knowledge show`

Show a knowledge source.

**Syntax**

`az sre knowledge show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n` | String | Yes |  |  | Name of the knowledge source. |

## `az sre managed-resource`

Let the agent's own managed identity monitor resources outside its own resource group.

Grants/revokes the built-in 'Reader' + 'Monitoring Contributor' roles together (the same pair, no individual role choice) on a subscription, resource group, or management group. Use 'sre managed-resource grant' to add a scope, 'sre managed-resource list' to see what's granted, and 'sre managed-resource revoke' to remove it.

| Verb | Exact syntax |
| --- | --- |
| `grant` | `az sre managed-resource grant --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]` |
| `list` | `az sre managed-resource list --name <value> --resource-group <value>` |
| `revoke` | `az sre managed-resource revoke --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]` |

### `az sre managed-resource grant`

Grant the agent's managed identity Reader + Monitoring Contributor on a scope.

**Syntax**

`az sre managed-resource grant --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent (NOT the target scope -- use --target-resource-group for that). |
| `--scope` | String | No |  |  | Full resource ID of the scope to grant access on/from. Alternative to --target-subscription/--target-resource-group/--management-group. |
| `--target-subscription` | String | No |  |  | Target subscription name or ID. Used alone for subscription-level scope, or with --target-resource-group for resource-group-level scope. (Named --target-subscription, not --subscription, because the latter is a reserved global az CLI argument.) |
| `--target-resource-group` | String | No |  |  | Target resource group name (requires --target-subscription). Distinct from --resource-group, which locates the agent itself. |
| `--management-group` | String | No |  |  | Target management group name/ID. |

**Examples**

- Grant on a subscription

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --target-subscription my-sub`
- Grant on a resource group

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --target-subscription my-sub --target-resource-group monitored-rg`
- Grant on a management group

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --management-group my-mg`

### `az sre managed-resource list`

List the external scopes the agent's managed identity currently has

access to (i.e. every role assignment where the agent is the assignee).

**Syntax**

`az sre managed-resource list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent. |

**Examples**

- List what an agent can currently monitor

  `az sre managed-resource list --agent-name myagent --resource-group myrg`

### `az sre managed-resource revoke`

Revoke the agent's managed identity's Reader + Monitoring Contributor on a scope.

**Syntax**

`az sre managed-resource revoke --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent (NOT the target scope -- use --target-resource-group for that). |
| `--scope` | String | No |  |  | Full resource ID of the scope to revoke access on/from. Alternative to --target-subscription/--target-resource-group/--management-group. |
| `--target-subscription` | String | No |  |  | Target subscription name or ID. Used alone for subscription-level scope, or with --target-resource-group for resource-group-level scope. (Named --target-subscription, not --subscription, because the latter is a reserved global az CLI argument.) |
| `--target-resource-group` | String | No |  |  | Target resource group name (requires --target-subscription). Distinct from --resource-group, which locates the agent itself. |
| `--management-group` | String | No |  |  | Target management group name/ID. |

**Examples**

- Revoke access to a resource group

  `az sre managed-resource revoke --agent-name myagent --resource-group myrg \ --target-subscription my-sub --target-resource-group monitored-rg`

## `az sre network`

Control an SRE Agent's sandbox networking (preview).

Configures VNet injection and the sandbox's outbound (egress) allowlist -- the network the agent's own sandboxed tool/code execution can reach, not the agent resource's own inbound access. Use 'sre network update' to change these settings.

| Verb | Exact syntax |
| --- | --- |
| `update` | `az sre network update --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]` |

### `az sre network update`

Configure VNet injection and sandbox egress for an SRE Agent (preview).

Hand-written, NOT generated -- there is no public swagger for the api-version that actually supports these fields in production (2026-11-01-preview; see NETWORK_API_VERSION comment above). Does a real ARM read-modify-write (GET then full PUT, matching the pattern the generated 'agent update' command itself uses for every other property) directly against that api-version, merging only the networking properties the caller actually supplied and leaving everything else on the resource untouched.

**Syntax**

`az sre network update --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to configure networking on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--vnet-configuration` | Object | No |  |  | VNet injection for the agent itself. Shorthand JSON, e.g. --vnet-configuration "{subnet-resource-id:/subscriptions/.../subnets/mysubnet}". |
| `--sandbox-configuration` | Object | No |  |  | Sandbox egress/package configuration for code the agent runs. Shorthand JSON, e.g. --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}". |

**Examples**

- Limit the agent's sandbox egress to one allowed host

  `az sre network update --name myagent --resource-group myrg \ --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}"`

## `az sre plugin`

Manage community plugins that add skills, tools, and integrations.

Two separate steps: connecting a marketplace (a GitHub/Azure DevOps/GitLab repo of plugins, via 'sre plugin marketplace') and installing a specific plugin from one (via 'sre plugin install').

| Subgroup | Summary |
| --- | --- |
| `install` | Install a specific plugin from an already-connected marketplace. |
| `marketplace` | Connect a repo of plugins as a marketplace the agent can install from. |

## `az sre repo`

Connect a code repository so the agent can read source during investigations.

'sre repo connect' supports GitHub and Azure DevOps in a single step (it wires up both the auth and the repository extension for you). GitLab repos are also supported at the data-plane level (a 'repositories' extension resource, same as GitHub/Azure DevOps), but this CLI doesn't yet expose a path to create one.

| Verb | Exact syntax |
| --- | --- |
| `connect` | `az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-account <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]` |

### `az sre repo connect`

Connect a GitHub or Azure DevOps repo to an SRE Agent in one step.

Fetches your existing 'gh auth login' credential (GitHub) or mints a fresh PAT via the Azure DevOps REST API (Azure DevOps) and wires up both the auth extension and the repositories extension for you, instead of requiring two manual hand-built JSON payloads.

**Syntax**

`az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-account <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--repo-url` | String | Yes |  |  | HTTPS clone URL of the repo, e.g. https://github.com/org/repo or https://dev.azure.com/org/project/_git/repo. |
| `--provider` | String | No |  | `GitHub`, `AzureDevOps` | Repo provider. Auto-detected from --repo-url's host when omitted. |
| `--display-name`, `--name`, `-n` | String | No |  |  | Display name for the repo. Defaults to the last path segment of --repo-url. |
| `--branch` | String | No |  |  | Branch to check out. Defaults to the repo's default branch. |
| `--github-account` | String | No |  |  | GitHub account to use when 'gh' is logged into more than one (GitHub repos only; passed to 'gh auth token --user'). |
| `--devops-organization` | String | No |  |  | Azure DevOps organization name, e.g. 'contoso' for dev.azure.com/contoso (Azure DevOps repos only; auto-detected from --repo-url when it is a dev.azure.com URL). |
| `--devops-auth-type` | String | No | pat | `pat`, `managed-identity` | Azure DevOps auth mechanism. 'pat' (default) mints a PAT via the vssps REST API -- some orgs block this with a 'DisablePatCreationPolicyViolation' org policy, in which case use 'managed-identity' with --devops-identity instead (the identity must already be added as a user/group member of the Azure DevOps org -- this command does not grant that membership). |
| `--devops-identity` | String | No |  |  | Resource ID of the user- or system-assigned managed identity to authenticate with Azure DevOps as (required when --devops-auth-type managed-identity). Typically the SRE Agent's own identity -- see 'az sre agent show --query identity'. |
| `--devops-federated-client-id` | String | No |  |  | Federated client ID, only needed alongside --devops-federated-tenant-id for a user-assigned identity in a different tenant than the Azure DevOps org (managed-identity auth only; both or neither must be set). |
| `--devops-federated-tenant-id` | String | No |  |  | Federated tenant ID, only needed alongside --devops-federated-client-id (managed-identity auth only; both or neither must be set). |

**Examples**

- Connect a GitHub repo (provider auto-detected from the URL)

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://github.com/contoso/my-service`
- Connect an Azure DevOps repo

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo`

## `az sre skill`

Manage custom skills -- specialized capabilities the agent can use.

Built-in skills are toggled on/off separately, not created here; use 'sre skill create --file-path SKILL.md' to author a custom one, then 'sre skill list'/'sre skill show' to see it.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre skill create --agent-name <value> --resource-group <value> --name <value> [--value <value>] [--overwrite {false,true}] [--file-path <value>] [--tools <json-or-@file>] [--description <value>]` |
| `delete` | `az sre skill delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre skill list --name <value> --resource-group <value>` |
| `show` | `az sre skill show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre skill create`

Create or update a custom skill.

**Syntax**

`az sre skill create --agent-name <value> --resource-group <value> --name <value> [--value <value>] [--overwrite {false,true}] [--file-path <value>] [--tools <json-or-@file>] [--description <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | No |  |  | Skill configuration as a JSON document. Alternative to --file-path (specify exactly one of the two). |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |
| `--file-path` | String | No |  |  | Path to a SKILL.md-style file -- an optional '---'-delimited frontmatter block with a 'description:' line, followed by the skill's markdown instructions body. Alternative to --value. |
| `--tools` | List | No |  |  | Space-separated tool names this skill can use when active. Only used with --file-path; defaults to none. |
| `--description` | String | No |  |  | Skill description. Only used with --file-path; overrides the SKILL.md frontmatter's 'description:' line if both are given. |

**Examples**

- Create a skill from a SKILL.md file

  `az sre skill create --agent-name myagent --resource-group myrg --name my-skill \ --file-path SKILL.md --tools kusto-query log-search`
- Create a skill from a raw JSON value

  `az sre skill create --agent-name myagent --resource-group myrg --name my-skill \ --value '{"description": "...", "tools": [], "skillContent": "# My skill\n..."}'`

### `az sre skill delete`

Delete a custom skill.

**Syntax**

`az sre skill delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre skill list`

List custom skills.

**Syntax**

`az sre skill list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre skill show`

Show a custom skill.

**Syntax**

`az sre skill show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre tool`

Manage custom tools the agent can call.

Built-in tools and MCP servers/services are configured separately and are not yet exposed by this CLI.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre tool create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre tool delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre tool list --name <value> --resource-group <value>` |
| `show` | `az sre tool show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre tool create`

Create or update a custom tool.

**Syntax**

`az sre tool create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Tool configuration as a JSON document. Discriminator field is "type" (not "toolType"), one of: KustoTool/LinkTool/PythonTool/HttpClientTool. Common fields: type/name/description/connector/toolMode/parameters. Per-type fields -- LinkTool: "template" (not "url") e.g. {"type": "LinkTool", "name": "docs", "description": "...", "template": "https://..."}; KustoTool: database/query/clusterHint; HttpClientTool: url/method/body/headers/auth (this is the one type that really does use "url"); PythonTool: functionCode/timeoutSeconds/dependencies/authEnabled/authScopes. Live-confirmed shape -- "toolType"/"url" at the top level (an earlier, now-fixed example) silently fails server-side with an opaque InternalServerError, only "type"/"template" works for LinkTool. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre tool delete`

Delete a custom tool.

**Syntax**

`az sre tool delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre tool list`

List custom tools.

**Syntax**

`az sre tool list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre tool show`

Show a custom tool.

**Syntax**

`az sre tool show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre usage`

Read an SRE Agent's usage and billing stats.

Token counts and request counts, for a month or broken down by day. Use 'sre usage list' to see how much an agent has used.

| Verb | Exact syntax |
| --- | --- |
| `list` | `az sre usage list --name <value> --resource-group <value> [--daily {false,true}]` |

### `az sre usage list`

List monthly or daily agent-unit usage for an SRE Agent.

Wraps the dedicated 'usages'/'dailyusages' read-only ARM child collections (confirmed real in running notes section 1a) -- these are plain GETs with no Create/Update verb, so aaz-dev-tools has nothing to anchor a generated command group on. Hand-written instead.

**Syntax**

`az sre usage list --name <value> --resource-group <value> [--daily {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to report usage for. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--daily` | Boolean | No | false | `false`, `true` | Report daily usage (dailyusages) instead of monthly (usages). |

**Examples**

- List this month's usage for an agent

  `az sre usage list --agent-name myagent --resource-group myrg`

## `az sre agent settings`

Manage an SRE Agent's global settings (preview).

A single, agent-wide settings object covering tool/skill allow-ask-deny permissions, custom instructions, and approval-expiration behavior.

| Verb | Exact syntax |
| --- | --- |
| `show` | `az sre agent settings show --name <value> --resource-group <value>` |
| `update` | `az sre agent settings update --name <value> --resource-group <value> --value <value>` |

### `az sre agent settings show`

Show an SRE Agent's global settings.

**Syntax**

`az sre agent settings show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent settings update`

Create or update an SRE Agent's global settings.

Always targets the agent's single settings object (there is no --name -- an agent has exactly one). Safe to call repeatedly; each call replaces the whole settings object, so include every field you want to keep, not just the one you're changing.

**Syntax**

`az sre agent settings update --name <value> --resource-group <value> --value <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--value` | String | Yes |  |  | Global settings as a JSON document (confirmed via the control plane's own real round-trip integration test, GlobalSettingsExtensionTests.cs). All top-level fields are optional: toolPermissions, toolStatuses/skillStatuses (arrays of {"name": ..., "enabled": true/false}), customInstructions (string), approvalExpirationSetting ({"enabled": true/false, "approvalExpirationInMinutes": <number>}). CAUTION: if you include toolPermissions at all, it must have all three of 'allow'/'ask'/'deny' (each an array of tool-name strings, [] if unused) -- live-confirmed the real API rejects a partial toolPermissions object (e.g. just 'deny') with a misleading "unrecognized property" error. |

## `az sre automation http-trigger`

Manage HTTP triggers: run the agent against a prompt from an inbound

webhook call instead of a schedule.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre automation http-trigger create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre automation http-trigger delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre automation http-trigger list --name <value> --resource-group <value>` |
| `show` | `az sre automation http-trigger show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre automation http-trigger create`

Create or update an HTTP trigger.

**Syntax**

`az sre automation http-trigger create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | HTTP trigger configuration as a JSON document. Fields: "agentPrompt" (what to ask the agent when the webhook fires), "description", "agent" (name of a connected sub-agent to target instead of the primary agent), "threadId" (continue an existing conversation thread instead of starting a new one each call -- same unset-vs-pinned behavior as scheduled-task's threadId above), "modelTier", "agentMode". Example: {"agentPrompt": "Investigate the attached alert payload", "description": "Webhook from external monitor"}. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre automation http-trigger delete`

Delete an HTTP trigger.

**Syntax**

`az sre automation http-trigger delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre automation http-trigger list`

List HTTP triggers.

**Syntax**

`az sre automation http-trigger list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre automation http-trigger show`

Show an HTTP trigger.

**Syntax**

`az sre automation http-trigger show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre automation scheduled-task`

Manage scheduled tasks: run the agent on a timer (cron) against a

prompt, optionally bounded to a time window or a maximum run count.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre automation scheduled-task create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre automation scheduled-task delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre automation scheduled-task list --name <value> --resource-group <value>` |
| `show` | `az sre automation scheduled-task show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre automation scheduled-task create`

Create or update a scheduled task.

**Syntax**

`az sre automation scheduled-task create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Scheduled task configuration as a JSON document. Fields: "cronExpression" (standard 5-field cron, e.g. "0 */6 * * *" for every 6 hours), "agentPrompt" (what to ask the agent each run), "description", "agent" (name of a connected sub-agent to target instead of the primary agent), "threadId" (continue an existing conversation thread instead of starting a new one each run -- confirmed via sreagent-runtime: leaving this unset lets each run get its own thread, pinning it to a fixed value reuses that one thread across every run (the portal's "Message grouping for updates" dropdown is UI sugar over this same field)), "startTime"/"endTime" (ISO 8601, bound the schedule's active window), "maxExecutions" (stop after N runs), "notificationChannel", "modelTier", "agentMode". Example: {"cronExpression": "0 9 * * 1-5", "agentPrompt": "Summarize overnight alerts", "description": "Daily alert digest"}. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre automation scheduled-task delete`

Delete a scheduled task.

**Syntax**

`az sre automation scheduled-task delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre automation scheduled-task list`

List scheduled tasks.

**Syntax**

`az sre automation scheduled-task list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre automation scheduled-task show`

Show a scheduled task.

**Syntax**

`az sre automation scheduled-task show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre plugin install`

Install a specific plugin from an already-connected marketplace.

Run 'sre plugin marketplace create' first if you haven't connected a marketplace yet.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre plugin install create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre plugin install delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre plugin install list --name <value> --resource-group <value>` |
| `show` | `az sre plugin install show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre plugin install create`

Install a plugin from a connected marketplace.

**Syntax**

`az sre plugin install create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Plugin install configuration as a JSON document, e.g. {"marketplaceName": "<name from 'sre plugin marketplace list'>", "pluginName": "<plugin>"}. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre plugin install delete`

Uninstall a plugin.

**Syntax**

`az sre plugin install delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre plugin install list`

List installed plugins.

**Syntax**

`az sre plugin install list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre plugin install show`

Show an installed plugin.

**Syntax**

`az sre plugin install show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

## `az sre plugin marketplace`

Connect a repo of plugins as a marketplace the agent can install from.

Supports GitHub, Azure DevOps, and GitLab repos. Use 'sre plugin install' afterward to actually install a plugin from the connected marketplace.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre plugin marketplace create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre plugin marketplace delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre plugin marketplace list --name <value> --resource-group <value>` |
| `show` | `az sre plugin marketplace show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre plugin marketplace create`

Connect a plugin marketplace.

**Syntax**

`az sre plugin marketplace create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Marketplace configuration as a JSON document, e.g. {"sourceType": "github", "sourceUrl": "https://github.com/owner/repo"}. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

### `az sre plugin marketplace delete`

Disconnect a plugin marketplace.

**Syntax**

`az sre plugin marketplace delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

### `az sre plugin marketplace list`

List connected plugin marketplaces.

**Syntax**

`az sre plugin marketplace list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre plugin marketplace show`

Show a connected plugin marketplace.

**Syntax**

`az sre plugin marketplace show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

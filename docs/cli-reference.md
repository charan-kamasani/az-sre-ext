<!--
GENERATED FILE - DO NOT EDIT.
Regenerate with: python3 scripts/generate_cli_reference.py
-->

# `az sre` CLI ergonomics reference

> [!IMPORTANT]
> This file is generated from the loaded extension command, help, and
> argument metadata. Do not edit it manually. Regenerate it with
> `python3 scripts/generate_cli_reference.py`.

Public surface: **7 groups** and **31 commands**.

## Important caveats

- This CLI only talks to the control plane (`Microsoft.App/agents` ARM resource). It never talks to the agent's own data plane (`*.azuresre.ai`) directly. See the [implementation plan](../PLAN.md).
- `agent update-network` is hand-written against the real `2026-11-01-preview` api-version; there is no public Swagger for it yet. See the [networking guide](networking.md).
- `agent extension create/show/list/delete` accept a `--value` JSON document that is base64-encoded and sent as-is to the agent's data plane. Only `commonPrompts`, `globalSettings`, and `pluginMarketplaces` have live-verified payload shapes today; see the [operations guide](operations.md).
- `agent connector list-secret` and `agent list-connectors-with-secret` are the only commands that can return connector secret material; everything else recursively redacts secrets from output.

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

Manage App

| Subgroup | Summary |
| --- | --- |
| `agent` | Manage Agent |
| `supported-agent-model` | Manage Supported Agent Model |

## `az sre agent`

Manage Agent

| Subgroup | Summary |
| --- | --- |
| `connector` | Manage Connector |
| `extension` |  |
| `identity` | Manage Identity |
| `repo` |  |

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre agent create [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>] [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] --location <value> [--tags <json-or-@file>] [--grant-access-to-me {admin,user,author,reader}]` |
| `delete` | `az sre agent delete [--no-wait] --name <value> --resource-group <value> [--yes]` |
| `get-connection` | `az sre agent get-connection --name <value> --resource-group <value> [--data-plane-audience <value>]` |
| `grant-access` | `az sre agent grant-access --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |
| `list` | `az sre agent list [--next-token <value>] [--max-items <value>] [--resource-group <value>]` |
| `list-connectors-with-secret` | `az sre agent list-connectors-with-secret --agent-name <value> --resource-group <value>` |
| `list-usage` | `az sre agent list-usage --name <value> --resource-group <value> [--daily {false,true}]` |
| `revoke-access` | `az sre agent revoke-access --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |
| `show` | `az sre agent show --name <value> --resource-group <value>` |
| `start` | `az sre agent start [--no-wait] --agent-name <value> --resource-group <value>` |
| `stop` | `az sre agent stop [--no-wait] --agent-name <value> --resource-group <value>` |
| `update` | `az sre agent update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --name <value> --resource-group <value> [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] [--tags <json-or-@file>]` |
| `update-network` | `az sre agent update-network --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]` |
| `wait` | `az sre agent wait --name <value> --resource-group <value>` |

### `az sre agent create`

Create an SRE Agent.

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
| `--grant-access-to-me` | String | No |  | `admin`, `user`, `author`, `reader` | Grant the signed-in user a built-in SRE Agent role immediately after creating the agent: 'admin', 'user', 'author', or 'reader'. Resolves your object ID via 'az ad signed-in-user show' automatically -- equivalent to running 'sre agent grant-access --assignee <your-object-id>' as a separate, manual follow-up command. |

**Examples**

- Create an agent with an Anthropic default model

  `az sre agent create --name myagent --resource-group myrg \ --location eastus2 --default-model "{provider:anthropic,name:claude-sonnet-4-5}"`

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

### `az sre agent get-connection`

Resolve and save an SRE Agent's data-plane connection.

Reads the agent's control-plane resource (ARM), extracts the 'agentEndpoint' property (the data-plane base URL, pattern 'https://{name}--{id}.{hash}.{region}.azuresre.ai' -- see running notes section 1a), and writes it to a local connections file for the separate, standalone data-plane 'sre' CLI to read. Mirrors 'az aks get-credentials' writing kubeconfig for kubectl: the control plane and data plane are two different CLIs/binaries by design (see running notes section 1), and this command is their only bridge.

**Syntax**

`az sre agent get-connection --name <value> --resource-group <value> [--data-plane-audience <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to connect to. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-plane-audience` | String | No | https://azuresre.dev |  | Audience used to request the data-plane access token. The data plane uses a separate token from the control plane -- see running notes section 1a. |

### `az sre agent grant-access`

Grant a built-in SRE Agent RBAC role to a user, group, or principal.

Thin convenience wrapper over 'az role assignment create' that builds the agent's full resource-ID scope for you (see running notes section 0's "Role assignment" row) -- not a new ARM operation, just a shortcut so callers do not need to construct the scope string by hand. Pass --assignee-me to grant yourself access without looking up your own object ID first.

**Syntax**

`az sre agent grant-access --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to grant access on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--role` | String | Yes |  | `admin`, `user`, `author`, `reader` | Built-in role to grant: 'admin', 'user', 'author', or 'reader'. |
| `--assignee` | String | No |  |  | User, group, or service principal object ID/UPN to grant the role for. Required unless --assignee-me is passed instead. |
| `--assignee-me` | Boolean | No |  | `false`, `true` | Use the signed-in user as the assignee, resolved via 'az ad signed-in-user show'. Alternative to --assignee. |

### `az sre agent list`

List SRE Agents in a subscription or resource group.

**Syntax**

`az sre agent list [--next-token <value>] [--max-items <value>] [--resource-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--resource-group`, `-g` | String | No |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent list-connectors-with-secret`

List all Data Connectors with secrets from an Agent

**Syntax**

`az sre agent list-connectors-with-secret --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- AgentsConnectors_ListWithSecretsByAgent

  `az app agent list-connectors-with-secret --resource-group examplerg --agent-name testAgent`

### `az sre agent list-usage`

List monthly or daily agent-unit usage for an SRE Agent.

Wraps the dedicated 'usages'/'dailyusages' read-only ARM child collections (confirmed real in running notes section 1a) -- these are plain GETs with no Create/Update verb, so aaz-dev-tools has nothing to anchor a generated command group on. Hand-written the same way azext-aigateway wraps metrics it has no generated recipe for.

**Syntax**

`az sre agent list-usage --name <value> --resource-group <value> [--daily {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to report usage for. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--daily` | Boolean | No | false | `false`, `true` | Report daily usage (dailyusages) instead of monthly (usages). |

### `az sre agent revoke-access`

Revoke a built-in SRE Agent RBAC role from a user, group, or principal.

Mirrors 'grant-access': thin convenience wrapper over 'az role assignment delete' that builds the agent's full resource-ID scope for you, so callers do not need to construct the scope string (or look up their own object ID, via --assignee-me) by hand.

**Syntax**

`az sre agent revoke-access --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to revoke access on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--role` | String | Yes |  | `admin`, `user`, `author`, `reader` | Built-in role to revoke: 'admin', 'user', 'author', or 'reader'. |
| `--assignee` | String | No |  |  | User, group, or service principal object ID/UPN to revoke the role for. Required unless --assignee-me is passed instead. |
| `--assignee-me` | Boolean | No |  | `false`, `true` | Use the signed-in user as the assignee, resolved via 'az ad signed-in-user show'. Alternative to --assignee. |

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

`az sre agent start [--no-wait] --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent stop`

Stop a running SRE Agent.

**Syntax**

`az sre agent stop [--no-wait] --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
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

### `az sre agent update-network`

Configure VNet injection and sandbox egress for an SRE Agent (preview).

Hand-written, NOT generated -- there is no public swagger for the api-version that actually supports these fields in production (2026-11-01-preview; see NETWORK_API_VERSION comment above). Does a real ARM read-modify-write (GET then full PUT, matching the pattern the generated 'agent update' command itself uses for every other property) directly against that api-version, merging only the networking properties the caller actually supplied and leaving everything else on the resource untouched.

**Syntax**

`az sre agent update-network --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to configure networking on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--vnet-configuration` | Object | No |  |  | VNet injection for the agent itself. Shorthand JSON, e.g. --vnet-configuration "{subnet-resource-id:/subscriptions/.../subnets/mysubnet}". |
| `--sandbox-configuration` | Object | No |  |  | Sandbox egress/package configuration for code the agent runs. Shorthand JSON, e.g. --sandbox-configuration "{egress:{mode:Limited,allowed-hosts:[example.com]}}". |

### `az sre agent wait`

Place the CLI in a waiting state until a condition is met.

**Syntax**

`az sre agent wait --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

## `az sre supported-agent-model`

Manage Supported Agent Model

| Verb | Exact syntax |
| --- | --- |
| `list` | `az sre supported-agent-model list [--next-token <value>] [--max-items <value>] --location <value>` |

### `az sre supported-agent-model list`

List SupportedAgentModel resources by SubscriptionLocationResource

**Syntax**

`az sre supported-agent-model list [--next-token <value>] [--max-items <value>] --location <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--location`, `-l` | String | Yes |  |  | Location. Values from: `az account list-locations`. You can configure the default location using `az configure --defaults location=<location>`. |

**Examples**

- SupportedAgentModels_ListByLocation

  `az app supported-agent-model list --location eastus`

## `az sre agent connector`

Manage Connector

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre agent connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}]` |
| `delete` | `az sre agent connector delete [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--yes]` |
| `list` | `az sre agent connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>` |
| `list-secret` | `az sre agent connector list-secret --agent-name <value> --connector-name <value> --resource-group <value>` |
| `show` | `az sre agent connector show --agent-name <value> --name <value> --resource-group <value>` |
| `update` | `az sre agent connector update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>]` |
| `wait` | `az sre agent connector wait --agent-name <value> --name <value> --resource-group <value>` |

### `az sre agent connector create`

Create an Agent Connector.

**Syntax**

`az sre agent connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-connector-type` | String | No |  |  | Type of the data connector. Real API values: 'Kusto' (covers Azure Data Explorer, App Insights, and Log Analytics -- differentiated by --data-source, not a separate type), 'Mcp' (PagerDuty/ServiceNow/Datadog/Splunk/S360/Ev2/etc. -- differentiated by endpoint, not a separate type), 'Outlook', 'Teams', 'Icm' (singleton per agent), 'KustoClient' (Kusto via the @azure/mcp server; no --data-source needed), 'Dgrep' (singleton per agent), and four knowledge-item types that need --extended-properties instead of --data-source: 'KnowledgeText', 'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository'. Case-insensitive. |
| `--data-source` | String | No |  |  | Data source connection string or endpoint |
| `--endpoint` | String | No |  |  | Endpoint of the connector |
| `--extended-properties` | Dictionary | No |  |  | Additional properties for the data connector which can be used to store custom key-value pairs |
| `--identity` | String | No |  |  | Identity used to access the data source |
| `--file-path` | String | No |  |  | Local file to ingest, instead of hand-building --extended-properties yourself. For --data-connector-type KnowledgeFile, the CLI reads and base64-encodes the file into extended-properties.fileContent/fileName. For KnowledgeText, the CLI reads the file as UTF-8 text into extended-properties.content. |
| `--mcp-endpoint` | String | No |  |  | For --data-connector-type Mcp: the MCP server's HTTP endpoint URL. Builds both --data-source and the nested extended-properties.transport/endpoint the service actually requires (confirmed live: a bare --data-source alone is rejected with 'Endpoint value is required for MCP connector with HTTP transport.'). |
| `--github` | Boolean | No |  | `false`, `true` | For --data-connector-type Mcp: shortcut for --mcp-endpoint pointed at the real public GitHub Copilot MCP server (https://api.githubcopilot.com/mcp/). |

### `az sre agent connector delete`

Delete an Agent Connector

**Syntax**

`az sre agent connector delete [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

**Examples**

- AgentsConnectors_Delete

  `az app agent connector delete --resource-group examplerg --agent-name testAgent --connector-name sql-connector`

### `az sre agent connector list`

List an SRE Agent's Connectors, including OAuth consent status

(consentStatus: Consented/PendingConsent) for EntraOAuth-backed Mcp connectors.

**Syntax**

`az sre agent connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent connector list-secret`

Get a Data Connector with secrets from an Agent

**Syntax**

`az sre agent connector list-secret --agent-name <value> --connector-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- AgentsConnectors_ListSecrets

  `az app agent connector list-secret --resource-group examplerg --agent-name testAgent --connector-name kusto-connector`

### `az sre agent connector show`

Show the details of an Agent Connector, including OAuth consent

status (consentStatus: Consented/PendingConsent) for EntraOAuth-backed Mcp connectors.

**Syntax**

`az sre agent connector show --agent-name <value> --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

### `az sre agent connector update`

Update an Agent Connector.

**Syntax**

`az sre agent connector update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>]`

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
| `--data-connector-type` | String | No |  |  | Type of the data connector. Real API values: 'Kusto' (covers Azure Data Explorer, App Insights, and Log Analytics -- differentiated by --data-source, not a separate type), 'Mcp' (PagerDuty/ServiceNow/Datadog/Splunk/S360/Ev2/etc. -- differentiated by endpoint, not a separate type), 'Outlook', 'Teams', 'Icm' (singleton per agent), 'KustoClient' (Kusto via the @azure/mcp server; no --data-source needed), 'Dgrep' (singleton per agent), and four knowledge-item types that need --extended-properties instead of --data-source: 'KnowledgeText', 'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository'. Case-insensitive. |
| `--data-source` | String | No |  |  | Data source connection string or endpoint |
| `--endpoint` | String | No |  |  | Endpoint of the connector |
| `--extended-properties` | Dictionary | No |  |  | Additional properties for the data connector which can be used to store custom key-value pairs |
| `--identity` | String | No |  |  | Identity used to access the data source |

### `az sre agent connector wait`

Place the CLI in a waiting state until a condition is met.

**Syntax**

`az sre agent connector wait --agent-name <value> --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

## `az sre agent extension`



| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre agent extension create --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre agent extension delete --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value>` |
| `list` | `az sre agent extension list --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings}` |
| `show` | `az sre agent extension show --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value>` |

### `az sre agent extension create`

Create or update an SRE Agent extension (subagent/tool/skill/etc.).

By default, refuses to silently overwrite an existing extension of the same --extension-type/--extension-name (there is no separate 'extension update' command, so an unguarded PUT here would clobber an existing repo/auth/tool registration with no warning). Pass --overwrite to update an existing one intentionally.

**Syntax**

`az sre agent extension create --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--extension-type`, `--type` | String | Yes |  | `subagents`, `tools`, `skills`, `scheduledTasks`, `incidentFilters`, `commonPrompts`, `hooks`, `incidentHandlers`, `httpTriggers`, `repositories`, `pluginMarketplaces`, `pluginInstallations`, `githubAuths`, `azureDevOpsAuths`, `globalSettings` | Kind of agent extension. One of: subagents, tools, skills, scheduledTasks, incidentFilters, commonPrompts, hooks, incidentHandlers, httpTriggers, repositories, pluginMarketplaces, pluginInstallations, githubAuths, azureDevOpsAuths, globalSettings. |
| `--extension-name`, `--name`, `-n` | String | Yes |  |  | Name of the extension instance. |
| `--value` | String | Yes |  |  | Extension configuration as a JSON document (the CLI base64-encodes it for you -- the wire format is properties.value = base64(json), confirmed via the internal control-plane repo's Agents.http examples). For --extension-type commonPrompts, the confirmed shape is a JSON object {"prompt": "..."} (one prompt per ARM resource name, e.g. 'default'). For globalSettings, the confirmed shape is a JSON object with optional toolPermissions/toolStatuses/skillStatuses/customInstructions/approvalExpirationSetting fields. 14 of 15 extension types now have confirmed inner shapes (source-cited in custom.py's _validate_*_shape functions; 12 also live-round-tripped against a real agent) -- only 'subagents' remains unconfirmed (believed server/portal-managed, not CLI-creatable). See issue #13 for the full findings and evidence. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing extension of the same --extension-type/--extension-name. Without this flag, 'extension create' refuses to overwrite an existing extension. |

### `az sre agent extension delete`

Delete an SRE Agent extension.

**Syntax**

`az sre agent extension delete --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--extension-type`, `--type` | String | Yes |  | `subagents`, `tools`, `skills`, `scheduledTasks`, `incidentFilters`, `commonPrompts`, `hooks`, `incidentHandlers`, `httpTriggers`, `repositories`, `pluginMarketplaces`, `pluginInstallations`, `githubAuths`, `azureDevOpsAuths`, `globalSettings` | Kind of agent extension. One of: subagents, tools, skills, scheduledTasks, incidentFilters, commonPrompts, hooks, incidentHandlers, httpTriggers, repositories, pluginMarketplaces, pluginInstallations, githubAuths, azureDevOpsAuths, globalSettings. |
| `--extension-name`, `--name`, `-n` | String | Yes |  |  | Name of the extension instance. |

### `az sre agent extension list`

List an SRE Agent's extensions of a given type.

**Syntax**

`az sre agent extension list --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings}`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--extension-type`, `--type` | String | Yes |  | `subagents`, `tools`, `skills`, `scheduledTasks`, `incidentFilters`, `commonPrompts`, `hooks`, `incidentHandlers`, `httpTriggers`, `repositories`, `pluginMarketplaces`, `pluginInstallations`, `githubAuths`, `azureDevOpsAuths`, `globalSettings` | Kind of agent extension. One of: subagents, tools, skills, scheduledTasks, incidentFilters, commonPrompts, hooks, incidentHandlers, httpTriggers, repositories, pluginMarketplaces, pluginInstallations, githubAuths, azureDevOpsAuths, globalSettings. |

### `az sre agent extension show`

Show an SRE Agent extension.

**Syntax**

`az sre agent extension show --agent-name <value> --resource-group <value> --extension-type {subagents,tools,skills,scheduledTasks,incidentFilters,commonPrompts,hooks,incidentHandlers,httpTriggers,repositories,pluginMarketplaces,pluginInstallations,githubAuths,azureDevOpsAuths,globalSettings} --extension-name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--extension-type`, `--type` | String | Yes |  | `subagents`, `tools`, `skills`, `scheduledTasks`, `incidentFilters`, `commonPrompts`, `hooks`, `incidentHandlers`, `httpTriggers`, `repositories`, `pluginMarketplaces`, `pluginInstallations`, `githubAuths`, `azureDevOpsAuths`, `globalSettings` | Kind of agent extension. One of: subagents, tools, skills, scheduledTasks, incidentFilters, commonPrompts, hooks, incidentHandlers, httpTriggers, repositories, pluginMarketplaces, pluginInstallations, githubAuths, azureDevOpsAuths, globalSettings. |
| `--extension-name`, `--name`, `-n` | String | Yes |  |  | Name of the extension instance. |

## `az sre agent identity`

Manage Identity

| Verb | Exact syntax |
| --- | --- |
| `assign` | `az sre agent identity assign [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `remove` | `az sre agent identity remove [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `show` | `az sre agent identity show --name <value> --resource-group <value>` |
| `wait` | `az sre agent identity wait --name <value> --resource-group <value>` |

### `az sre agent identity assign`

Assign the user or system managed identities.

**Syntax**

`az sre agent identity assign [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |

**Examples**

- Agents_CreateOrUpdate

  `az app agent identity assign --resource-group examplerg --agent-name testAgent`

### `az sre agent identity remove`

Remove the user or system managed identities.

**Syntax**

`az sre agent identity remove [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |

**Examples**

- Agents_CreateOrUpdate

  `az app agent identity remove --resource-group examplerg --agent-name testAgent`

### `az sre agent identity show`

Show the details of managed identities.

**Syntax**

`az sre agent identity show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Agents_Get

  `az app agent identity show --resource-group examplerg --agent-name testAgent`

### `az sre agent identity wait`

Place the CLI in a waiting state until a condition is met.

**Syntax**

`az sre agent identity wait --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

## `az sre agent repo`



| Verb | Exact syntax |
| --- | --- |
| `connect` | `az sre agent repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-account <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]` |

### `az sre agent repo connect`

Connect a GitHub or Azure DevOps repo to an SRE Agent in one step.

Mirrors 'az aigateway mcp create --github true': fetches your existing 'gh auth login' credential (GitHub) or mints a fresh PAT via the Azure DevOps REST API (Azure DevOps) and wires up both the auth extension and the repositories extension for you, instead of requiring two manual 'sre agent extension create' calls with hand-built JSON --value payloads.

**Syntax**

`az sre agent repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-account <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]`

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

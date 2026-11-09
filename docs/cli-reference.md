<!--
GENERATED FILE - DO NOT EDIT.
Regenerate with: python3 scripts/generate_cli_reference.py
-->

# `az sre` CLI ergonomics reference

> [!IMPORTANT]
> This file is generated from the loaded extension command, help, and
> argument metadata. Do not edit it manually. Regenerate it with
> `python3 scripts/generate_cli_reference.py`.

Public surface: **24 groups** and **78 commands**.

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

Manage Azure SRE Agent resources.

In PowerShell, pass JSON with --value @file.json instead of inline.

| Subgroup | Summary |
| --- | --- |
| `access` | Control who can manage or use an SRE Agent. |
| `agent` | Manage the core lifecycle of an SRE Agent resource. |
| `automation` | Manage agent automations. |
| `connector` | Connect an SRE Agent to an external data source it can query or act on. |
| `endpoint` | Resolve the URL used to actually talk to an SRE Agent's data plane. |
| `hook` | Manage lifecycle hooks that run a prompt or script at a specific agent event. |
| `identity` | Manage the agent's own managed identity. |
| `instructions` | Manage named, reusable prompt snippets ('commonPrompts'). |
| `knowledge` | Add files or web pages the agent can read and reason over. |
| `managed-resource` | Let the agent monitor resources outside its resource group. |
| `network` | Control an SRE Agent's sandbox networking (preview). |
| `plugin` | Manage community plugins that add skills, tools, and integrations. |
| `repo` | Connect a code repository so the agent can read source during investigations. |
| `response-plan` | Route incidents to a subagent (portal: Triggers & response plans). |
| `skill` | Manage custom skills -- specialized capabilities the agent can use. |
| `subagent` | Manage named sub-agents the meta-agent can hand off work to. |
| `tool` | Manage custom tools the agent can call. |
| `usage` | Read an SRE Agent's usage and billing stats. |

## `az sre access`

Control who can manage or use an SRE Agent.

This is the mirror image of 'sre managed-resource': that group grants the agent's own identity access to things outside itself, while this group grants other people/principals access to the agent itself.

| Verb | Exact syntax |
| --- | --- |
| `grant` | `az sre access grant --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |
| `list` | `az sre access list --name <value> --resource-group <value>` |
| `revoke` | `az sre access revoke --name <value> --resource-group <value> --role {admin,user,author,reader} [--assignee <value>] [--assignee-me {false,true}]` |

### `az sre access grant`

Grant an agent role to a user, group or principal.

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

assignment scoped to the agent itself.

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

Revoke an agent role from a user, group or principal.

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

**Syntax**

`az sre agent create [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>] [--action-configuration <json-or-@file>] [--agent-identity <json-or-@file>] [--default-model <json-or-@file>] [--incident-management-configuration <json-or-@file>] [--knowledge-graph-configuration <json-or-@file>] [--log-configuration <json-or-@file>] [--upgrade-channel {Preview,Stable}] --location <value> [--tags <json-or-@file>] [--grant-access-to-me {admin,user,author,reader}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Enable the system-assigned identity. Default: a user-assigned identity is created and both are enabled. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | User-assigned identities to attach. |
| `--action-configuration` | Object | No |  |  | Configuration for action |
| `--agent-identity` | Object | No |  |  | Agent identity configuration for accessing resources |
| `--default-model` | Object | No |  |  | Default AI model configuration for the agent |
| `--incident-management-configuration` | Object | No |  |  | Incident management configurations |
| `--knowledge-graph-configuration` | Object | No |  |  | Knowledge graph configuration for agent |
| `--log-configuration` | Object | No |  |  | Application Insights link for traces. Without it, a warning is shown and trace view is unavailable. |
| `--upgrade-channel` | String | No |  | `Preview`, `Stable` | The upgrade channel of the agent |
| `--location`, `-l` | String | Yes |  |  | The geo-location where the resource lives |
| `--tags` | Dictionary | No |  |  | Resource tags. |
| `--grant-access-to-me` | String | No |  | `admin`, `user`, `author`, `reader` | Grant yourself a built-in role after creation. Cannot be used with --no-wait. |

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

**Examples**

- Delete an agent after confirming interactively

  `az sre agent delete --name myagent --resource-group myrg`
- Delete an agent without an interactive confirmation prompt

  `az sre agent delete --name myagent --resource-group myrg --yes`

### `az sre agent list`

List SRE Agents in a subscription or resource group.

**Syntax**

`az sre agent list [--next-token <value>] [--max-items <value>] [--resource-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--resource-group`, `-g` | String | No |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List all agents in a resource group

  `az sre agent list --resource-group myrg`
- List all agents in the current subscription

  `az sre agent list`

### `az sre agent list-models`

List the models supported for new agents in a region.

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

**Examples**

- Show one agent's details

  `az sre agent show --name myagent --resource-group myrg`

### `az sre agent start`

Start a stopped SRE Agent.

**Syntax**

`az sre agent start [--no-wait] --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Start a stopped agent

  `az sre agent start --name myagent --resource-group myrg`

### `az sre agent stop`

Stop a running SRE Agent.

**Syntax**

`az sre agent stop [--no-wait] --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Stop a running agent

  `az sre agent stop --name myagent --resource-group myrg`

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

**Examples**

- Switch an agent's default model to MicrosoftFoundry

  `az sre agent update --name myagent --resource-group myrg \ --default-model "{provider:MicrosoftFoundry,name:gpt-5}"`
- Connect PagerDuty as the incident platform (portal: Incidents

  `> Connect an incident platform > PagerDuty). This is a plain ARM PATCH on the agent resource -- confirmed via the control plane's own AgentDocument.cs model and real E2E fixtures (PagerDutySetupFixture.cs) -- not the separate, portal-only Connector Gateway (which Jira/Slack/ SharePoint/etc. use). --connection-key is the PagerDuty REST API access key from the tutorial; --obo-user is the user whose identity the agent acts under when resolving/commenting on incidents. az sre agent update --name myagent --resource-group myrg \ --incident-management-configuration "{type:PagerDuty,connection-name:pagerduty,connection-key:<api-key>,obo-user:oncall@contoso.com}"`
- Connect ServiceNow as the incident platform (Basic Auth; set

  `--connection-url to the instance URL and --connection-key to the credentials, per the tutorial's "instance URL and credentials" step) az sre agent update --name myagent --resource-group myrg \ --incident-management-configuration "{type:ServiceNow,connection-name:servicenow,connection-url:https://contoso.service-now.com,connection-key:<credentials>}" Azure Monitor needs no configuration here -- it connects automatically when the agent is created (confirmed by the tutorial and by AzMonitor being the enum's implicit default).`

### `az sre agent wait`

Place the CLI in a waiting state until a condition is met.

**Syntax**

`az sre agent wait --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Wait until the agent finishes provisioning

  `az sre agent wait -g myrg --agent-name myagent --created`

## `az sre automation`

Manage agent automations.

Covers scheduled tasks and HTTP triggers. Response plans live under 'az sre response-plan' instead.

| Subgroup | Summary |
| --- | --- |
| `http-trigger` | Manage HTTP triggers that run the agent on a webhook call. |
| `scheduled-task` | Manage scheduled tasks that run the agent on a cron timer. |

## `az sre connector`

Connect an SRE Agent to an external data source it can query or act on.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}] [--tool-access {false,true}] [--bearer-token <value>] [--managed-identity-auth {false,true}] [--mi-token-scope <value>] [--oauth-dcr {false,true}] [--oauth-scopes <value>] [--oauth-client-name <value>]` |
| `delete` | `az sre connector delete [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--yes]` |
| `list` | `az sre connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>` |
| `list-secret` | `az sre connector list-secret --agent-name <value> --name <value> --resource-group <value>` |
| `show` | `az sre connector show --agent-name <value> --name <value> --resource-group <value>` |
| `update` | `az sre connector update [--no-wait] [--add <value>] [--set <value>] [--remove <value>] [--force-string {true,t,yes,y,1,false,f,no,n,0}] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>]` |

### `az sre connector create`

Create an Agent Connector.

**Syntax**

`az sre connector create [--no-wait] --agent-name <value> --name <value> --resource-group <value> [--data-connector-type <value>] [--data-source <value>] [--endpoint <value>] [--extended-properties <json-or-@file>] [--identity <value>] [--file-path <value>] [--mcp-endpoint <value>] [--github {false,true}] [--tool-access {false,true}] [--bearer-token <value>] [--managed-identity-auth {false,true}] [--mi-token-scope <value>] [--oauth-dcr {false,true}] [--oauth-scopes <value>] [--oauth-client-name <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--no-wait` | Flag | No |  |  | Do not wait for the long-running operation to finish. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-connector-type` | String | No |  |  | Connector type, by portal name (case-insensitive): Azure Data Explorer, Database query connector (user), Log Analytics Workspace, Application Insights, MCP server, Office 365 Outlook, Microsoft Teams, EV2, Azure DevOps AI Search, IcM connector, DGrep, Geneva Metrics, S360 connector. For knowledge sources use 'az sre knowledge create'. |
| `--data-source` | String | No |  |  | Connection string or endpoint. For Kusto, include the database: https://cluster.kusto.windows.net/database. |
| `--endpoint` | String | No |  |  | Endpoint URL, used by endpoint-based connector types such as Mcp. |
| `--extended-properties` | Dictionary | No |  |  | Type-specific settings as JSON or shorthand. |
| `--identity` | String | No |  |  | Managed identity resource ID used to reach the data source. Default: the agent's system-assigned identity. |
| `--file-path` | String | No |  |  | Local file to ingest. For knowledge sources use 'az sre knowledge create'. |
| `--mcp-endpoint` | String | No |  |  | For Mcp: the MCP server's HTTP endpoint URL. |
| `--github` | Boolean | No |  | `false`, `true` | For Mcp: connect the public GitHub Copilot MCP server (https://api.githubcopilot.com/mcp/). |
| `--tool-access` | Boolean | No |  | `false`, `true` | For KustoClient: let the agent use query tools from this connector (portal 'Allow agent to use query tools'). |
| `--bearer-token` | String | No |  |  | For Mcp: static bearer token, PAT or API key sent with every request. |
| `--managed-identity-auth` | Boolean | No |  | `false`, `true` | For Mcp: authenticate with the agent's managed identity. Use --identity for a user-assigned one. |
| `--mi-token-scope` | String | No |  |  | For Mcp with --managed-identity-auth: token scope to request. Default: https://management.azure.com/.default. |
| `--oauth-dcr` | Boolean | No |  | `false`, `true` | For Mcp: use OAuth with dynamic client registration. Finish consent in the portal. |
| `--oauth-scopes` | String | No |  |  | For Mcp with --oauth-dcr: comma-separated OAuth scopes to request. |
| `--oauth-client-name` | String | No |  |  | For Mcp with --oauth-dcr: client name to register. Optional. |

**Examples**

- Connect Azure Data Explorer

  `az sre connector create --agent-name myagent --resource-group myrg \ --name adx --data-connector-type "Azure Data Explorer"`
- Connect the GitHub MCP server

  `az sre connector create --agent-name myagent --resource-group myrg \ --name github --data-connector-type Mcp --github true`
- Connect a custom MCP server with a bearer token

  `az sre connector create --agent-name myagent --resource-group myrg \ --name mcp --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp" \ --bearer-token "$MY_SERVER_TOKEN"`
- Connect a custom MCP server with the agent's managed identity

  `az sre connector create --agent-name myagent --resource-group myrg \ --name mcp --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp" \ --managed-identity-auth true`
- Connect one Kusto cluster and database

  `az sre connector create --agent-name myagent --resource-group myrg \ --name kusto --data-connector-type "Azure Data Explorer" \ --data-source "https://mycluster.westus.kusto.windows.net/mydatabase"`

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

**Examples**

- Delete a connector without a prompt

  `az sre connector delete -g myrg --agent-name myagent -n conn-kusto --yes`

### `az sre connector list`

List connectors, including OAuth consent status.

consentStatus (Consented/PendingConsent) is shown for EntraOAuth-backed Mcp connectors.

**Syntax**

`az sre connector list [--next-token <value>] [--max-items <value>] --agent-name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--next-token` | String | No |  |  | Token to specify where to start paginating. This is the token value from a previously truncated response. |
| `--max-items` | String | No |  |  | Total number of items to return in the command's output. If the total number of items available is more than the value specified, a token is provided in the command's output. To resume pagination, provide the token value in `--next-token` argument of a subsequent command. |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's connectors

  `az sre connector list -g myrg --agent-name myagent`

### `az sre connector list-secret`

Show a connector with its secrets in plain text.

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

Show a connector, including OAuth consent status.

consentStatus is shown for EntraOAuth-backed Mcp connectors.

**Syntax**

`az sre connector show --agent-name <value> --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | The name of the Agent |
| `-n`, `--name`, `--connector-name` | String | Yes |  |  | The name of the AgentConnector |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Show one connector

  `az sre connector show -g myrg --agent-name myagent -n conn-kusto`

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
| `--data-connector-type` | String | No |  |  | Connector type, by portal name (case-insensitive): Azure Data Explorer, Database query connector (user), Log Analytics Workspace, Application Insights, MCP server, Office 365 Outlook, Microsoft Teams, EV2, Azure DevOps AI Search, IcM connector, DGrep, Geneva Metrics, S360 connector. For knowledge sources use 'az sre knowledge create'. |
| `--data-source` | String | No |  |  | Connection string or endpoint. For Kusto, include the database: https://cluster.kusto.windows.net/database. |
| `--endpoint` | String | No |  |  | Endpoint URL, used by endpoint-based connector types such as Mcp. |
| `--extended-properties` | Dictionary | No |  |  | Type-specific settings as JSON or shorthand. |
| `--identity` | String | No |  |  | Managed identity resource ID used to reach the data source. Default: the agent's system-assigned identity. |

**Examples**

- Point a Kusto connector at a different database

  `az sre connector update -g myrg --agent-name myagent -n conn-kusto \ --data-connector-type "Azure Data Explorer" \`

## `az sre endpoint`

Resolve the URL used to actually talk to an SRE Agent's data plane.

Use 'sre endpoint show' to look up and save that live endpoint.

| Verb | Exact syntax |
| --- | --- |
| `show` | `az sre endpoint show --name <value> --resource-group <value> [--data-plane-audience <value>]` |

### `az sre endpoint show`

Save an agent's data-plane endpoint for other tools.

Like 'az aks get-credentials', it writes the connection details that data-plane tools read.

**Syntax**

`az sre endpoint show --name <value> --resource-group <value> [--data-plane-audience <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to connect to. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--data-plane-audience` | String | No | https://azuresre.dev |  | Audience for the data-plane access token. |

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
| `--value` | String | Yes |  |  | Hook configuration as JSON: eventType, activationMode, description and a nested "hook" object. hook.matcher is required for PreToolUse and PostToolUse. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Run a prompt after every Bash tool call

  `az sre hook create --agent-name myagent --resource-group myrg --name post-tool-check \ --value @hook.json hook.json: {"eventType": "PostToolUse", "activationMode": "always", "description": "Flag risky commands", "hook": {"type": "prompt", "prompt": "Warn if the last tool call looks destructive.", "matcher": "Bash.*", "failMode": "Allow"}}`
- Run a command instead of a prompt

  `--value @hook.json, with "hook": {"type": "command", "command": "echo ok", "matcher": "Bash.*", "timeout": 30}`

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

**Examples**

- Delete a hook

  `az sre hook delete -g myrg --agent-name myagent --name post-tool-check`

### `az sre hook list`

List hooks.

**Syntax**

`az sre hook list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's hooks

  `az sre hook list -g myrg --agent-name myagent`

### `az sre hook show`

Show a hook.

**Syntax**

`az sre hook show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one hook

  `az sre hook show -g myrg --agent-name myagent --name post-tool-check`

## `az sre identity`

Manage the agent's own managed identity.

Used for the agent's Azure RBAC-gated calls. Not to be confused with 'sre access' (who can manage/use the agent) or 'sre repo connect' (repo auth).

| Verb | Exact syntax |
| --- | --- |
| `assign` | `az sre identity assign [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `remove` | `az sre identity remove [--no-wait] --name <value> --resource-group <value> [--system-assigned <value>] [--user-assigned <json-or-@file>]` |
| `show` | `az sre identity show --name <value> --resource-group <value>` |

### `az sre identity assign`

Assign a managed identity to an agent.

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

Remove a managed identity from an agent.

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

Show the managed identities assigned to an agent.

**Syntax**

`az sre identity show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | The name of the Agent |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Show an agent's identities

  `az sre identity show -g myrg --agent-name myagent`

## `az sre instructions`

Manage named, reusable prompt snippets ('commonPrompts').

WARNING -- this is NOT the portal's single "Custom instructions" text box. That is a different field, 'customInstructions', on the agent's global settings object -- set it with 'az sre agent settings update'.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre instructions create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]` |
| `delete` | `az sre instructions delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre instructions list --name <value> --resource-group <value>` |
| `show` | `az sre instructions show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre instructions create`

Create or update a reusable prompt snippet.

WARNING -- this does NOT set the portal's single "Custom instructions" text box. Use 'az sre agent settings update' for that instead. Use the same --name (e.g. "default") each time to update a given snippet in place, or pass --overwrite to replace an existing one.

**Syntax**

`az sre instructions create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Prompt snippet as JSON: {"prompt": "..."}. For custom instructions, use 'az sre agent settings update'. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Set an agent's global custom instructions (the portal's real

  `singleton text box -- NOT this command; shown here to avoid the mix-up) az sre agent settings update -g myrg --agent-name myagent \ --value '{"customInstructions": "Always cite the runbook section you used."}'`
- Create a named, reusable prompt snippet instead (what this

  `command actually does) az sre instructions create -g myrg --agent-name myagent --name default \ --value '{"prompt": "Always cite the runbook section you used."}'`
- Windows PowerShell -- same --value @file pattern as 'sre hook

  `create' (live-verified, recommended; see 'sre hook create -h' for why) '{"prompt": "Be concise."}' \| Set-Content -Path "$env:TEMP\instructions.json" az sre instructions create -g myrg --agent-name myagent --name default --value "@$env:TEMP\instructions.json" --overwrite true`
- Windows PowerShell -- alternative 'cmd /c' wrapper, if you'd

  `rather not write a temp file (live-verified, also works) cmd /c 'az sre instructions create --agent-name myagent --resource-group myrg --name default --value "{\"prompt\": \"Be concise.\"}" --overwrite true'`

### `az sre instructions delete`

Delete a named, reusable prompt snippet ('commonPrompts').

WARNING -- NOT the portal's "Custom instructions" box; see 'sre instructions create -h'. To clear the real singleton instead, use 'az sre agent settings update --value \'{"customInstructions": ""}\''.

**Syntax**

`az sre instructions delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

**Examples**

- Delete an agent's custom instructions

  `az sre instructions delete -g myrg --agent-name myagent --name default`

### `az sre instructions list`

List an agent's reusable prompt snippets.

WARNING -- NOT the portal's "Custom instructions" box; see 'sre instructions create -h'.

**Syntax**

`az sre instructions list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's custom instructions entries

  `az sre instructions list -g myrg --agent-name myagent`

### `az sre instructions show`

Show a named, reusable prompt snippet ('commonPrompts').

WARNING -- NOT the portal's "Custom instructions" box; see 'sre instructions create -h'. For the real singleton, use 'az sre agent settings show' and read its 'customInstructions' field.

**Syntax**

`az sre instructions show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show an agent's current custom instructions

  `az sre instructions show -g myrg --agent-name myagent --name default`

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
| `--url` | String | No |  |  | Web page URL to ingest. Required for --type webpage. Cannot be combined with --data-source. |
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

**Examples**

- Remove a knowledge source

  `az sre knowledge delete -g myrg --agent-name myagent --name docs-site`

### `az sre knowledge list`

List an SRE Agent's knowledge sources (files and web pages).

**Syntax**

`az sre knowledge list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List knowledge sources

  `az sre knowledge list -g myrg --agent-name myagent`

### `az sre knowledge show`

Show a knowledge source.

**Syntax**

`az sre knowledge show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n` | String | Yes |  |  | Name of the knowledge source. |

**Examples**

- Show one knowledge source

  `az sre knowledge show -g myrg --agent-name myagent --name docs-site`

## `az sre managed-resource`

Let the agent monitor resources outside its resource group.

Grants/revokes the built-in 'Reader' + 'Monitoring Contributor' roles together on a subscription, resource group, or management group. Defaults to the system-assigned identity. Use --identity with an assigned user-assigned identity's ARM resource ID to target it instead.

| Verb | Exact syntax |
| --- | --- |
| `grant` | `az sre managed-resource grant [--identity <value>] --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]` |
| `list` | `az sre managed-resource list [--identity <value>] --name <value> --resource-group <value>` |
| `revoke` | `az sre managed-resource revoke [--identity <value>] --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]` |

### `az sre managed-resource grant`

Give the agent Reader and Monitoring Contributor on a scope.

Targets the system-assigned identity by default. Use --identity to select an assigned user-assigned identity without changing runtime settings.

**Syntax**

`az sre managed-resource grant [--identity <value>] --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--identity` | String | No | system |  | Agent identity to target: 'system' (default), or the full ARM resource ID of an assigned user-assigned identity. Does not change the agent's runtime identity. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent (NOT the target scope -- use --target-resource-group for that). |
| `--scope` | String | No |  |  | Full resource ID of the scope to grant access on/from. Alternative to --target-subscription/--target-resource-group/--management-group. |
| `--target-subscription` | String | No |  |  | Target subscription name or ID. Alone: subscription scope. With --target-resource-group: resource-group scope. |
| `--target-resource-group` | String | No |  |  | Target resource group name (requires --target-subscription). Distinct from --resource-group, which locates the agent itself. |
| `--management-group` | String | No |  |  | Target management group name/ID. |

**Examples**

- Grant on a subscription

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --target-subscription my-sub`
- Grant on a resource group

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --target-subscription my-sub --target-resource-group monitored-rg`
- Grant on a management group

  `az sre managed-resource grant --agent-name myagent --resource-group myrg \ --management-group my-mg`
- Grant an assigned user-assigned identity access to a resource group

  `az sre managed-resource grant -g myrg --agent-name myagent \ --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime \ --target-subscription my-sub --target-resource-group monitored-rg`

### `az sre managed-resource list`

List the scopes the agent's managed identity can access.

Shows role assignments under the current subscription for the selected identity, not just Reader and Monitoring Contributor. Defaults to the system-assigned identity. Use --identity to select an assigned user-assigned identity.

**Syntax**

`az sre managed-resource list [--identity <value>] --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--identity` | String | No | system |  | Agent identity to target: 'system' (default), or the full ARM resource ID of an assigned user-assigned identity. Does not change the agent's runtime identity. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent. |

**Examples**

- List what an agent can currently monitor

  `az sre managed-resource list --agent-name myagent --resource-group myrg`
- List an assigned user-assigned identity's role assignments

  `az sre managed-resource list -g myrg --agent-name myagent \ --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime`

### `az sre managed-resource revoke`

Remove the agent's Reader and Monitoring Contributor on a scope.

Only removes these two roles for the selected identity on the exact requested scope. Other identities, roles, and scopes are unaffected. Defaults to the system-assigned identity.

**Syntax**

`az sre managed-resource revoke [--identity <value>] --name <value> --resource-group <value> [--scope <value>] [--target-subscription <value>] [--target-resource-group <value>] [--management-group <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--identity` | String | No | system |  | Agent identity to target: 'system' (default), or the full ARM resource ID of an assigned user-assigned identity. Does not change the agent's runtime identity. |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Resource group of the SRE Agent (NOT the target scope -- use --target-resource-group for that). |
| `--scope` | String | No |  |  | Full resource ID of the scope to revoke access on/from. Alternative to --target-subscription/--target-resource-group/--management-group. |
| `--target-subscription` | String | No |  |  | Target subscription name or ID. Alone: subscription scope. With --target-resource-group: resource-group scope. |
| `--target-resource-group` | String | No |  |  | Target resource group name (requires --target-subscription). Distinct from --resource-group, which locates the agent itself. |
| `--management-group` | String | No |  |  | Target management group name/ID. |

**Examples**

- Revoke access to a resource group

  `az sre managed-resource revoke --agent-name myagent --resource-group myrg \ --target-subscription my-sub --target-resource-group monitored-rg`
- Revoke an assigned user-assigned identity's access

  `az sre managed-resource revoke -g myrg --agent-name myagent \ --identity /subscriptions/<sub-id>/resourceGroups/identity-rg/providers/Microsoft.ManagedIdentity/userAssignedIdentities/runtime \ --target-subscription my-sub --target-resource-group monitored-rg`

## `az sre network`

Control an SRE Agent's sandbox networking (preview).

Configures VNet injection and outbound egress for the agent's own sandboxed tool/code execution -- not the agent resource's inbound access.

| Verb | Exact syntax |
| --- | --- |
| `show` | `az sre network show --name <value> --resource-group <value>` |
| `update` | `az sre network update --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]` |

### `az sre network show`

Show VNet injection and sandbox egress settings (preview).

'az sre agent show' omits these because it uses an older API version.

**Syntax**

`az sre network show --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to show networking settings for. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- Show an agent's networking settings

  `az sre network show --name myagent --resource-group myrg`

### `az sre network update`

Configure VNet injection and sandbox egress (preview).

**Syntax**

`az sre network update --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent to configure networking on. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--vnet-configuration` | Object | No |  |  | VNet injection for the agent itself. Shorthand JSON, e.g. --vnet-configuration "{subnet-resource-id:/subscriptions/.../subnets/mysubnet}". |
| `--sandbox-configuration` | Object | No |  |  | Sandbox egress and packages. Shorthand, e.g. "{egress:{mode:Limited,allowed-hosts:[example.com]}}". |

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

Supports GitHub and Azure DevOps. GitLab isn't exposed by this CLI yet.

| Verb | Exact syntax |
| --- | --- |
| `connect` | `az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-token <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]` |

### `az sre repo connect`

Connect a GitHub or Azure DevOps repo to an agent.

**Syntax**

`az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-token <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--repo-url` | String | Yes |  |  | HTTPS clone URL of the repo. |
| `--provider` | String | No |  | `GitHub`, `AzureDevOps` | Repo provider. Auto-detected from --repo-url's host when omitted. |
| `--display-name`, `--name`, `-n` | String | No |  |  | Display name for the repo. Defaults to the last path segment of --repo-url. |
| `--branch` | String | No |  |  | Branch to check out. Defaults to the repo's default branch. |
| `--github-token` | String | No |  |  | GitHub token. Default: GITHUB_TOKEN/GH_TOKEN, else browser sign-in. |
| `--devops-organization` | String | No |  |  | Azure DevOps organization. Default: taken from --repo-url. |
| `--devops-auth-type` | String | No | pat | `pat`, `managed-identity` | Azure DevOps auth method. Use managed-identity if your org blocks PAT creation. |
| `--devops-identity` | String | No |  |  | Managed identity resource ID. Required with --devops-auth-type managed-identity. |
| `--devops-federated-client-id` | String | No |  |  | Federated client ID, for an identity in a different tenant. Use with --devops-federated-tenant-id. |
| `--devops-federated-tenant-id` | String | No |  |  | Federated tenant ID. Use with --devops-federated-client-id. |

**Examples**

- Connect a GitHub repo

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://github.com/contoso/my-service`
- Connect a GitHub repo with a token

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://github.com/contoso/my-service \ --github-token $env:GITHUB_TOKEN`
- Connect an Azure DevOps repo

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo`
- Connect an Azure DevOps repo with a managed identity

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo \ --devops-auth-type managed-identity --devops-identity <agent-identity-resource-id>`

## `az sre response-plan`

Route incidents to a subagent (portal: Triggers & response plans).

Match criteria use ARM; linked instructions use the agent API.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre response-plan create --agent-name <value> --resource-group <value> --name <value> --platform <value> --subagent <value> [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--incident-type <json-or-@file>] [--impacted-service <value>] [--owning-team <json-or-@file>] [--merge-enabled {false,true}] [--merge-window-hours <integer>] [--instructions <value>] [--processing-guide <json-or-@file>] [--mode <value>] [--disabled {false,true}] [--overwrite {false,true}]` |
| `delete` | `az sre response-plan delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `disable` | `az sre response-plan disable --agent-name <value> --resource-group <value> --name <value>` |
| `enable` | `az sre response-plan enable --agent-name <value> --resource-group <value> --name <value>` |
| `list` | `az sre response-plan list [--name <value>] [--resource-group <value>] [--agent-url <value>]` |
| `show` | `az sre response-plan show [--agent-name <value>] [--resource-group <value>] [--agent-url <value>] --name <value>` |
| `update` | `az sre response-plan update --agent-name <value> --resource-group <value> --name <value> [--platform <value>] [--subagent <value>] [--mode <value>] [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--incident-type <json-or-@file>] [--impacted-service <value>] [--owning-team <json-or-@file>] [--merge-enabled {false,true}] [--merge-window-hours <integer>] [--instructions <value>] [--processing-guide <json-or-@file>]` |

### `az sre response-plan create`

Create or update an incident response plan.

Routes matching incidents to a subagent. Connect the incident platform and create the subagent first.

**Syntax**

`az sre response-plan create --agent-name <value> --resource-group <value> --name <value> --platform <value> --subagent <value> [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--incident-type <json-or-@file>] [--impacted-service <value>] [--owning-team <json-or-@file>] [--merge-enabled {false,true}] [--merge-window-hours <integer>] [--instructions <value>] [--processing-guide <json-or-@file>] [--mode <value>] [--disabled {false,true}] [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of the response plan. |
| `--platform` | String | Yes |  |  | Incident platform: AzMonitor, PagerDuty, ServiceNow, Icm. Icm is Microsoft-internal only. |
| `--subagent` | String | Yes |  |  | Name of the existing subagent that handles matched incidents. |
| `--priority` | List | No |  |  | Space-separated priority or severity levels to match (for example Sev0 Sev1 or P1 P2). Default: all. |
| `--title-contains` | String | No |  |  | Only match incidents whose title contains this text. |
| `--title-not-contains` | List | No |  |  | Space-separated texts; skip incidents whose title contains any of them. |
| `--incident-type` | List | No |  |  | Space-separated incident types to match (for example LiveSite). Portal: Incident type. |
| `--impacted-service` | String | No |  |  | Only match incidents for this service. Portal: Owning service. |
| `--owning-team` | List | No |  |  | Space-separated owning team IDs (IcM team IDs are numeric). Portal: Owning team. |
| `--merge-enabled` | Boolean | No |  | `false`, `true` | Merge related incidents into one investigation thread. Service default: true. |
| `--merge-window-hours` | Integer | No |  |  | Hours within which related incidents are merged. Service default: 3. |
| `--instructions` | String | No |  |  | Custom instructions the subagent follows for matched incidents. |
| `--processing-guide` | List | No |  |  | Quoted step-by-step guidance for the subagent, one value per step. |
| `--mode` | String | No | autonomous |  | Agent autonomy: autonomous (portal default) or review (agent proposes, you approve). |
| `--disabled` | Boolean | No |  | `false`, `true` | Create the plan turned off. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing response plan. |

**Examples**

- Route high-severity Azure Monitor incidents to a subagent in review mode

  `az sre response-plan create -g myrg --agent-name myagent -n sev1-api \ --platform AzMonitor --subagent incident-responder --priority Sev0 Sev1 \ --title-contains api --mode review`
- Skip noisy incidents and give the subagent step-by-step guidance

  `az sre response-plan create -g myrg --agent-name myagent -n api-errors \ --platform AzMonitor --subagent incident-responder --priority Sev1 Sev2 \ --title-not-contains test synthetic \ --processing-guide "Check recent deployments" "Query error rates in App Insights"`
- Change an existing plan

  `az sre response-plan update -g myrg --agent-name myagent -n api-errors --mode autonomous`

### `az sre response-plan delete`

Delete a response plan and its linked instructions.

**Syntax**

`az sre response-plan delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of the response plan. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

**Examples**

- Delete a plan

  `az sre response-plan delete -g myrg --agent-name myagent -n sev1-api`

### `az sre response-plan disable`

Turn off a response plan without deleting it.

**Syntax**

`az sre response-plan disable --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this incident filter. |

**Examples**

- Disable a plan

  `az sre response-plan disable -g myrg --agent-name myagent -n sev1-api`

### `az sre response-plan enable`

Turn on a response plan.

**Syntax**

`az sre response-plan enable --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this incident filter. |

**Examples**

- Enable a plan

  `az sre response-plan enable -g myrg --agent-name myagent -n sev1-api`

### `az sre response-plan list`

List response plans.

**Syntax**

`az sre response-plan list [--name <value>] [--resource-group <value>] [--agent-url <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | No |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | No |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--agent-url` | String | No |  |  | Agent endpoint URL (https://<agent>.<hash>.<region>.azuresre.ai) for a shared agent that is not in your subscription. Read-only commands only. |

**Examples**

- List an agent's response plans

  `az sre response-plan list -g myrg --agent-name myagent`

### `az sre response-plan show`

Show a response plan and its instructions.

**Syntax**

`az sre response-plan show [--agent-name <value>] [--resource-group <value>] [--agent-url <value>] --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | No |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | No |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--agent-url` | String | No |  |  | Agent endpoint URL (https://<agent>.<hash>.<region>.azuresre.ai) for a shared agent that is not in your subscription. Read-only commands only. |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of the response plan. |

**Examples**

- Show one plan

  `az sre response-plan show -g myrg --agent-name myagent -n sev1-api`

### `az sre response-plan update`

Update a response plan. Only the flags you pass change.

Passing a list flag (for example --priority) replaces that whole list. Use 'enable' or 'disable' to turn a plan on or off.

**Syntax**

`az sre response-plan update --agent-name <value> --resource-group <value> --name <value> [--platform <value>] [--subagent <value>] [--mode <value>] [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--incident-type <json-or-@file>] [--impacted-service <value>] [--owning-team <json-or-@file>] [--merge-enabled {false,true}] [--merge-window-hours <integer>] [--instructions <value>] [--processing-guide <json-or-@file>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of the response plan. |
| `--platform` | String | No |  |  | Incident platform: AzMonitor, PagerDuty, ServiceNow, Icm. |
| `--subagent` | String | No |  |  | Name of the existing subagent that handles matched incidents. |
| `--mode` | String | No |  |  | Agent autonomy: autonomous or review. |
| `--priority` | List | No |  |  | Space-separated priority or severity levels to match (for example Sev0 Sev1 or P1 P2). Default: all. |
| `--title-contains` | String | No |  |  | Only match incidents whose title contains this text. |
| `--title-not-contains` | List | No |  |  | Space-separated texts; skip incidents whose title contains any of them. |
| `--incident-type` | List | No |  |  | Space-separated incident types to match (for example LiveSite). Portal: Incident type. |
| `--impacted-service` | String | No |  |  | Only match incidents for this service. Portal: Owning service. |
| `--owning-team` | List | No |  |  | Space-separated owning team IDs (IcM team IDs are numeric). Portal: Owning team. |
| `--merge-enabled` | Boolean | No |  | `false`, `true` | Merge related incidents into one investigation thread. Service default: true. |
| `--merge-window-hours` | Integer | No |  |  | Hours within which related incidents are merged. Service default: 3. |
| `--instructions` | String | No |  |  | Custom instructions the subagent follows for matched incidents. |
| `--processing-guide` | List | No |  |  | Quoted step-by-step guidance for the subagent, one value per step. |

**Examples**

- Change the autonomy mode and the merge window

  `az sre response-plan update -g myrg --agent-name myagent -n sev1-api \ --mode autonomous --merge-window-hours 6`
- Point a plan at a different subagent and replace its severities

  `az sre response-plan update -g myrg --agent-name myagent -n sev1-api \ --subagent other-responder --priority Sev0 Sev1`

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

**Examples**

- Delete a custom skill

  `az sre skill delete -g myrg --agent-name myagent --name triage-skill`

### `az sre skill list`

List custom skills.

**Syntax**

`az sre skill list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's custom skills

  `az sre skill list -g myrg --agent-name myagent`

### `az sre skill show`

Show a custom skill.

**Syntax**

`az sre skill show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one custom skill

  `az sre skill show -g myrg --agent-name myagent --name triage-skill`

## `az sre subagent`

Manage named sub-agents the meta-agent can hand off work to.

A sub-agent is a scoped specialist with its own instructions, tools, and skills -- the portal's Agent Canvas "Create subagent" dialog.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre subagent create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}] [--pre-tool-use-script-file <value>]` |
| `delete` | `az sre subagent delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `list` | `az sre subagent list --name <value> --resource-group <value>` |
| `show` | `az sre subagent show --agent-name <value> --resource-group <value> --name <value>` |

### `az sre subagent create`

Create or update a named sub-agent.

**Syntax**

`az sre subagent create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}] [--pre-tool-use-script-file <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Sub-agent configuration as JSON. Required: instructions, handoffDescription, tools, mcpTools, commonTools, allowedSkills, allowParallelToolCalls. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |
| `--pre-tool-use-script-file` | String | No |  |  | Path to a script file to run before every tool call this sub-agent makes (the portal's "Manage Hooks" > "Pre Tool Use" button inside the subagent dialog). Merged into --value.hooks.PreToolUse with matcher "(?s:.*)" (every tool), timeout 30s, failMode "block" -- pass --value.hooks directly instead for other matchers/timeouts. |

**Examples**

- Create a read-only evidence-gathering sub-agent (live-verified payload)

  `az sre subagent create --agent-name myagent --resource-group myrg --name app-investigator \ --value '{"instructions": "You are the application evidence specialist. Read supplied reference files with ReadFile and return source-backed observations.", "handoffDescription": "Use for read-only application request/error/dependency evidence.", "tools": ["ReadFile"], "mcpTools": [], "commonTools": [], "allowedSkills": ["zava-application-evidence"], "allowParallelToolCalls": true}'`
- Same, plus a PreToolUse hook script read from a file (live-verified)

  `az sre subagent create --agent-name myagent --resource-group myrg --name app-investigator \ --value "@value.json" --pre-tool-use-script-file readonly-evidence.py`

### `az sre subagent delete`

Delete a sub-agent.

**Syntax**

`az sre subagent delete --agent-name <value> --resource-group <value> --name <value> [--yes]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--yes`, `-y` | Flag | No | false |  | Do not prompt for confirmation. |

**Examples**

- Delete a sub-agent

  `az sre subagent delete -g myrg --agent-name myagent --name app-investigator`

### `az sre subagent list`

List sub-agents.

**Syntax**

`az sre subagent list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's sub-agents

  `az sre subagent list -g myrg --agent-name myagent`

### `az sre subagent show`

Show a sub-agent.

**Syntax**

`az sre subagent show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one sub-agent

  `az sre subagent show -g myrg --agent-name myagent --name app-investigator`

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

Create a custom tool, or update one with --overwrite.

**Syntax**

`az sre tool create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Tool configuration as JSON. New tools: KustoTool, LinkTool or PythonFunctionTool. PythonTool is a legacy alias for PythonFunctionTool. HttpClientTool is update-only: pass --overwrite for an existing HttpClientTool of the same name. Use PythonFunctionTool or an MCP server for new HTTP integrations. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Create a link tool

  `az sre tool create -g myrg --agent-name myagent --name docs-link \ --value '{"type": "LinkTool", "name": "docs", "description": "Link to docs", "template": "https://learn.microsoft.com/azure/"}'`

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

**Examples**

- Delete a custom tool

  `az sre tool delete -g myrg --agent-name myagent --name docs-link`

### `az sre tool list`

List custom tools.

**Syntax**

`az sre tool list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's custom tools

  `az sre tool list -g myrg --agent-name myagent`

### `az sre tool show`

Show a custom tool.

**Syntax**

`az sre tool show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one custom tool

  `az sre tool show -g myrg --agent-name myagent --name docs-link`

## `az sre usage`

Read an SRE Agent's usage and billing stats.

Token counts and request counts, for a month or broken down by day. Use 'sre usage list' to see how much an agent has used.

| Verb | Exact syntax |
| --- | --- |
| `list` | `az sre usage list --name <value> --resource-group <value> [--daily {false,true}]` |

### `az sre usage list`

List monthly or daily agent-unit usage for an SRE Agent.

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

**Examples**

- Show an agent's global settings

  `az sre agent settings show --agent-name myagent --resource-group myrg`

### `az sre agent settings update`

Create or update an SRE Agent's global settings.

Always targets the agent's single settings object (there is no --name). Each call replaces the whole object, so include every field you want to keep. Sets the portal's "Custom instructions" box via --value.customInstructions (unrelated to 'sre instructions create').

**Syntax**

`az sre agent settings update --name <value> --resource-group <value> --value <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--value` | String | Yes |  |  | Settings as JSON. Optional fields: customInstructions, toolPermissions, toolStatuses, skillStatuses, approvalExpirationSetting. If you set toolPermissions, include all of allow, ask and deny (use [] if unused). |

**Examples**

- Set the portal's "Custom instructions" text box

  `az sre agent settings update -g myrg --agent-name myagent \ --value '{"customInstructions": "Always cite the runbook section you used."}'`
- Allow, ask for approval, or deny specific tools

  `--value '{"toolPermissions": {"allow": ["kusto-query"], "ask": [], "deny": ["run-shell"]}}'`

## `az sre automation http-trigger`

Manage HTTP triggers that run the agent on a webhook call.

Runs the agent against a prompt when an inbound webhook call arrives, instead of on a schedule.

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
| `--value` | String | Yes |  |  | Trigger configuration as JSON. Fields: agentPrompt, description, agent, threadId. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Create a webhook that runs the agent against a prompt

  `az sre automation http-trigger create -g myrg --agent-name myagent --name alert-webhook \ --value '{"agentPrompt": "Investigate the attached alert payload"}'`

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

**Examples**

- Delete an HTTP trigger

  `az sre automation http-trigger delete -g myrg --agent-name myagent --name alert-webhook`

### `az sre automation http-trigger list`

List HTTP triggers.

**Syntax**

`az sre automation http-trigger list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's HTTP triggers

  `az sre automation http-trigger list -g myrg --agent-name myagent`

### `az sre automation http-trigger show`

Show an HTTP trigger.

**Syntax**

`az sre automation http-trigger show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one HTTP trigger

  `az sre automation http-trigger show -g myrg --agent-name myagent --name alert-webhook`

## `az sre automation scheduled-task`

Manage scheduled tasks that run the agent on a cron timer.

Runs the agent against a prompt, optionally bounded to a time window or a maximum run count.

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
| `--value` | String | Yes |  |  | Task configuration as JSON. Fields: cronExpression, agentPrompt, description, agent, threadId, startTime, endTime, maxExecutions. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Run the agent on a timer against a prompt

  `az sre automation scheduled-task create -g myrg --agent-name myagent --name daily-digest \ --value '{"cronExpression": "0 9 * * 1-5", "agentPrompt": "Summarize overnight alerts"}'`

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

**Examples**

- Delete a scheduled task

  `az sre automation scheduled-task delete -g myrg --agent-name myagent --name daily-digest`

### `az sre automation scheduled-task list`

List scheduled tasks.

**Syntax**

`az sre automation scheduled-task list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's scheduled tasks

  `az sre automation scheduled-task list -g myrg --agent-name myagent`

### `az sre automation scheduled-task show`

Show a scheduled task.

**Syntax**

`az sre automation scheduled-task show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one scheduled task

  `az sre automation scheduled-task show -g myrg --agent-name myagent --name daily-digest`

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

Unlike other extension types, 'marketplaceName'/'pluginName' alone are not enough -- supply the full 'source' block ({"type", "repo", "url"}) naming the plugin's exact path in the marketplace repo. This CLI writes the installation record directly and does not run the portal's install pipeline, so the result is missing 'importedSkills'/ 'sourceCommit'/a resolved 'mcpConnectorStatus' compared to a portal install.

**Syntax**

`az sre plugin install create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Plugin install configuration as JSON. Requires marketplaceName, pluginName and a "source" block. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Install a plugin from a connected marketplace

  `az sre plugin install create -g myrg --agent-name myagent --name datadog \ --value '{"marketplaceName": "contoso-plugins", "pluginName": "datadog", \ "source": {"type": "relative", "repo": "contoso/sre-plugins", "url": "plugins/datadog"}}'`

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

**Examples**

- Uninstall a plugin

  `az sre plugin install delete -g myrg --agent-name myagent --name datadog`

### `az sre plugin install list`

List installed plugins.

**Syntax**

`az sre plugin install list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's installed plugins

  `az sre plugin install list -g myrg --agent-name myagent`

### `az sre plugin install show`

Show an installed plugin.

**Syntax**

`az sre plugin install show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one installed plugin

  `az sre plugin install show -g myrg --agent-name myagent --name datadog`

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
| `--value` | String | Yes |  |  | Marketplace configuration as JSON. Fields: sourceType ("github"), sourceUrl ("owner/repo", not a full URL), owner, description. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing one of the same name. Without this flag, creation refuses to overwrite an existing instance. |

**Examples**

- Connect a GitHub repo as a plugin marketplace

  `az sre plugin marketplace create -g myrg --agent-name myagent --name contoso-plugins \ --value '{"sourceType": "github", "sourceUrl": "owner/repo"}'`

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

**Examples**

- Disconnect a plugin marketplace

  `az sre plugin marketplace delete -g myrg --agent-name myagent --name contoso-plugins`

### `az sre plugin marketplace list`

List connected plugin marketplaces.

**Syntax**

`az sre plugin marketplace list --name <value> --resource-group <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `-n`, `--name`, `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |

**Examples**

- List an agent's connected plugin marketplaces

  `az sre plugin marketplace list -g myrg --agent-name myagent`

### `az sre plugin marketplace show`

Show a connected plugin marketplace.

**Syntax**

`az sre plugin marketplace show --agent-name <value> --resource-group <value> --name <value>`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |

**Examples**

- Show one connected plugin marketplace

  `az sre plugin marketplace show -g myrg --agent-name myagent --name contoso-plugins`

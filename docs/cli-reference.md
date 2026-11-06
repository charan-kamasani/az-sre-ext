<!--
GENERATED FILE - DO NOT EDIT.
Regenerate with: python3 scripts/generate_cli_reference.py
-->

# `az sre` CLI ergonomics reference

> [!IMPORTANT]
> This file is generated from the loaded extension command, help, and
> argument metadata. Do not edit it manually. Regenerate it with
> `python3 scripts/generate_cli_reference.py`.

Public surface: **24 groups** and **76 commands**.

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

Windows PowerShell note: inline JSON in --value/etc. (e.g. --value '{"key": "value"}') can fail with a confusing "unrecognized arguments" error -- a PowerShell/.cmd quoting quirk, not an az sre bug. Workaround: pass --value @path\to\file.json instead.

| Subgroup | Summary |
| --- | --- |
| `access` | Control who can manage or use an SRE Agent. |
| `agent` | Manage the core lifecycle of an SRE Agent resource. |
| `automation` | Manage agent automations. |
| `connector` | Connect an SRE Agent to an external data source it can query or act on. |
| `endpoint` | Resolve the URL used to actually talk to an SRE Agent's data plane. |
| `hook` | Manage lifecycle hooks that run a prompt or script at a specific agent event. |
| `identity` | Manage the SRE Agent's own managed identity, used for its Azure RBAC-gated calls. |
| `instructions` | Manage named, reusable prompt snippets ('commonPrompts'). |
| `knowledge` | Add files or web pages the agent can read and reason over. |
| `managed-resource` | Let the agent's own managed identity monitor resources outside its own resource group. |
| `network` | Control an SRE Agent's sandbox networking (preview). |
| `plugin` | Manage community plugins that add skills, tools, and integrations. |
| `repo` | Connect a code repository so the agent can read source during investigations. |
| `response-plan` | Manage incident response plans (portal: Incidents > "Triggers & |
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

Grant a built-in SRE Agent RBAC role to a user, group, or principal.

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

Revoke a built-in SRE Agent RBAC role from a user, group, or principal.

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
| `--system-assigned`, `--mi-system-assigned` | String | No |  |  | Set the system managed identity. |
| `--user-assigned`, `--mi-user-assigned` | List | No |  |  | Set the user managed identities. |
| `--action-configuration` | Object | No |  |  | Configuration for action |
| `--agent-identity` | Object | No |  |  | Agent identity configuration for accessing resources |
| `--default-model` | Object | No |  |  | Default AI model configuration for the agent |
| `--incident-management-configuration` | Object | No |  |  | Incident management configurations |
| `--knowledge-graph-configuration` | Object | No |  |  | Knowledge graph configuration for agent |
| `--log-configuration` | Object | No |  |  | Log configurations. If omitted, the agent is created without an Application Insights link (not required by the service, but you lose trace view -- a warning is printed). |
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

  `--connection-url to the instance URL and --connection-key to the credentials, per the tutorial's "instance URL and credentials" step) az sre agent update --name myagent --resource-group myrg \ --incident-management-configuration "{type:ServiceNow,connection-name:servicenow,connection-url:https://contoso.service-now.com,connection-key:<credentials>}" Azure Monitor needs no configuration here -- it connects automatically when the agent is created (confirmed by the tutorial and by AzMonitor being the enum's implicit default). Icm is this CLI's own sandbox/ first-party path, set the same way with type=Icm.`

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

Covers scheduled tasks and HTTP triggers. Response plans live under 'az sre response-plan' instead.

| Subgroup | Summary |
| --- | --- |
| `http-trigger` | Manage HTTP triggers: run the agent against a prompt from an inbound |
| `scheduled-task` | Manage scheduled tasks: run the agent on a timer (cron) against a |

## `az sre connector`

Connect an SRE Agent to an external data source it can query or act on.

Use 'sre connector create' to add one, 'sre connector list'/'show' to see what's connected (see --help on those for the full supported type list). The portal's larger "Additional connectors" catalog (Gmail, SharePoint, OneDrive, etc.) has no public API yet -- portal-only.

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
| `--data-connector-type` | String | No |  |  | Type of the data connector. Portal display name shown first, wire/API value in parentheses (both accepted, case-insensitive): 'Azure Data Explorer' (KustoClient -- the default type, matching the portal's own 'Azure Data Explorer' option exactly; no --data-source needed), 'Azure Data Explorer Cluster' (Kusto -- legacy, pinned to one cluster via --data-source, no portal entry point), 'MCP server' (Mcp, a.k.a. 'User provided connector' -- possibly also PagerDuty/ServiceNow/etc. via a custom endpoint, not a separate type; note Datadog/Splunk/S360/EV2 have their own dedicated portal cards and may not actually route through this generic type -- unverified), 'Office 365 Outlook' (Outlook), 'Microsoft Teams' (Teams), 'IcM connector' (Icm, a.k.a. 'Microsoft IcM', singleton per agent), 'DGrep' (Dgrep, a.k.a. 'Microsoft DGrep', singleton per agent), 'Log Analytics Workspace' (LogAnalytics), 'EV2' (Ev2Mcp), 'Geneva Metrics' (GenevaMetrics -- restricted to Microsoft's 13 known first-party tenants, matching the portal's own connector-picker gate), 'S360 connector' (S360), 'Documentation connector' (Documentation), 'Database query connector (user)' (KustoUser -- correlation not create-and-inspect confirmed), 'Database indexing connector' (KustoDataIndexer -- same caveat), 'Azure DevOps AI Search' (AzureDevOpsBuiltinMcp -- same caveat), and four knowledge-item types that need --extended-properties instead of --data-source: 'KnowledgeText', 'KnowledgeFile', 'KnowledgeWebPage', 'KnowledgeRepository' (none of these four appear in the portal's Connectors picker -- they live in a separate portal section). Also accepts 'TsgCrawler', 'ConnectorGateway', 'AzureMonitor', 'MonitorClient' (no portal picker card found for any of these), and one of 'AppInsights'/'ApplicationInsights' (the portal shows a single 'Application Insights' card, but which of these two wire values it persists as is not yet confirmed -- both are accepted here). |
| `--data-source` | String | No |  |  | Data source connection string or endpoint. For 'Kusto' (Azure Data Explorer Cluster), this must include a database name, e.g. 'https://cluster.kusto.windows.net/databasename' -- a bare cluster URL with no database is rejected server-side with 'Kusto DataSource must include a database name'. |
| `--endpoint` | String | No |  |  | Endpoint of the connector |
| `--extended-properties` | Dictionary | No |  |  | Additional properties for the data connector which can be used to store custom key-value pairs |
| `--identity` | String | No |  |  | Identity used to access the data source |
| `--file-path` | String | No |  |  | Local file to ingest, instead of hand-building --extended-properties yourself. For --data-connector-type KnowledgeFile, the CLI reads and base64-encodes the file into extended-properties.fileContent/fileName. For KnowledgeText, the CLI reads the file as UTF-8 text into extended-properties.content. |
| `--mcp-endpoint` | String | No |  |  | For --data-connector-type Mcp: the MCP server's HTTP endpoint URL. Builds both --data-source and the nested extended-properties.transport/endpoint the service actually requires (confirmed live: a bare --data-source alone is rejected with 'Endpoint value is required for MCP connector with HTTP transport.'). |
| `--github` | Boolean | No |  | `false`, `true` | For --data-connector-type Mcp: shortcut for --mcp-endpoint pointed at the real public GitHub Copilot MCP server (https://api.githubcopilot.com/mcp/). |
| `--tool-access` | Boolean | No |  | `false`, `true` | For --data-connector-type KustoClient/'Azure Data Explorer': shortcut for the portal's 'Allow agent to use query tools from this connector' checkbox (Review + add step). Builds extended-properties.toolsVisibleToMetaAgent -- true sets it to ['*'], false to [] (confirmed live: both values persist and read back correctly). |
| `--bearer-token` | String | No |  |  | For --data-connector-type Mcp: a static bearer token/PAT/API key sent on every request to the MCP server (the portal wizard's 'Bearer token' authentication method). Builds extended-properties.authType=BearerToken + bearerToken. |
| `--managed-identity-auth` | Boolean | No |  | `false`, `true` | For --data-connector-type Mcp: authenticate to the MCP server using the agent's managed identity (the portal wizard's 'Managed identity' authentication method; combine with --identity to pick a user-assigned identity instead of the system-assigned default, same as other connector types). Builds extended-properties.authType=AzureARM. Implied by --mi-token-scope if that is passed alone. |
| `--mi-token-scope` | String | No |  |  | For --data-connector-type Mcp with --managed-identity-auth: the Azure AD token scope/audience to request (the portal wizard's 'Azure AD token scope' free-text field). Builds extended-properties.armScope. Defaults to 'https://management.azure.com/.default' if omitted, matching the portal's own default. |
| `--oauth-dcr` | Boolean | No |  | `false`, `true` | For --data-connector-type Mcp: use OAuth with Dynamic Client Registration (the portal wizard's 'OAuth (dynamic client registration)' authentication method -- the one that shows a real browser 'Authorize' consent redirect; pre-registered client IDs/secrets are not supported, matching the portal's own text). Builds extended-properties.authType=SpecOAuth. Consent is completed afterwards in the portal, not by this command. |
| `--oauth-scopes` | String | No |  |  | For --data-connector-type Mcp with --oauth-dcr true: comma-separated OAuth scopes to request during the DCR consent flow. Builds extended-properties.scopes. |
| `--oauth-client-name` | String | No |  |  | For --data-connector-type Mcp with --oauth-dcr true: the client name to register during Dynamic Client Registration. Builds extended-properties.dcrClientName. Optional -- the service picks a default name if omitted. |

**Examples**

- Connect an agent to Azure Data Explorer -- matches the portal's

  `"Add connector" > "Azure Data Explorer" flow exactly: just a name and type, no --data-source or --mcp-endpoint needed (uses the agent's system-assigned identity by default, same as the portal) az sre connector create --agent-name myagent --resource-group myrg \ --name azure-data-explorer --data-connector-type "Azure Data Explorer"`
- Same, but with a user-assigned identity (portal's "Add identity")

  `az sre connector create --agent-name myagent --resource-group myrg \ --name azure-data-explorer --data-connector-type "Azure Data Explorer" \ --identity /subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.ManagedIdentity/userAssignedIdentities/<identity>`
- Connect an agent's GitHub MCP connector using your own gh auth

  `az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp --data-connector-type Mcp --github true`
- Connect a custom MCP server by its own endpoint (live-verified payload)

  `az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp-custom --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp"`
- Connect a custom MCP server using a static bearer token/PAT

  `(portal's "Bearer token" authentication method) az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp-bearer --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp" \ --bearer-token "$MY_SERVER_TOKEN"`
- Connect a custom MCP server using the agent's managed identity

  `(portal's "Managed identity" authentication method; combine with --identity to use a user-assigned identity instead of the system-assigned default) az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp-mi --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp" \ --managed-identity-auth true --mi-token-scope "api://myserver/.default"`
- Connect a custom MCP server using OAuth with Dynamic Client

  `Registration (portal's "OAuth (dynamic client registration)" authentication method -- finish consent afterwards in the portal) az sre connector create --agent-name myagent --resource-group myrg \ --name conn-mcp-oauth --data-connector-type Mcp \ --mcp-endpoint "https://myserver.contoso.com/mcp" --oauth-dcr true`
- Connect a single Kusto/Azure Data Explorer cluster+database directly

  `(legacy 'Kusto' type, as opposed to the default 'KustoClient'/"Azure Data Explorer" type above -- --data-source must include the database name, live-verified payload) az sre connector create --agent-name myagent --resource-group myrg \ --name my-cluster --data-connector-type Kusto \ --data-source "https://mycluster.westus.kusto.windows.net/mydatabase"`

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

status for EntraOAuth-backed Mcp connectors.

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

Use 'sre endpoint show' to look up and save that live endpoint.

| Verb | Exact syntax |
| --- | --- |
| `show` | `az sre endpoint show --name <value> --resource-group <value> [--data-plane-audience <value>]` |

### `az sre endpoint show`

Resolve and save an SRE Agent's data-plane connection.

Mirrors 'az aks get-credentials' writing kubeconfig for kubectl: the control plane and data plane are separate CLIs/binaries, and this command is their only bridge.

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
- Windows PowerShell -- inline JSON with embedded quotes does not

  `survive az.cmd's batch-file argument re-tokenizing here. Recommended fix: write the JSON to a file and pass --value @path instead (live-verified, no quoting at all, works in plain powershell.exe/pwsh) @' {"eventType": "PostToolUse", "activationMode": "always", "description": "Flag risky commands", "hook": {"type": "prompt", "prompt": "Review the last tool call. If it looks destructive, warn the user.", "matcher": "Bash.*", "failMode": "Allow"}} '@ \| Set-Content -Path "$env:TEMP\hook.json" az sre hook create --agent-name myagent --resource-group myrg --name post-tool-check --value "@$env:TEMP\hook.json" --overwrite true`
- Windows PowerShell -- alternative if you'd rather not write a

  `temp file: wrap the whole command in 'cmd /c' and backslash-escape the inner double quotes (live-verified, also works, but --value @path above is simpler and preferred) cmd /c 'az sre hook create --agent-name myagent --resource-group myrg --name post-tool-check --value "{\"eventType\": \"PostToolUse\", \"activationMode\": \"always\", \"description\": \"Flag risky commands\", \"hook\": {\"type\": \"prompt\", \"prompt\": \"Review the last tool call. If it looks destructive, warn the user.\", \"matcher\": \"Bash.*\", \"failMode\": \"Allow\"}}" --overwrite true'`

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

Manage the SRE Agent's own managed identity, used for its Azure RBAC-gated calls.

Not to be confused with 'sre access' (who can manage/use the agent) or 'sre repo connect' (repo auth).

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

Create or update a named, reusable prompt snippet ('commonPrompts').

WARNING -- this does NOT set the portal's single "Custom instructions" text box. Use 'az sre agent settings update' for that instead. Use the same --name (e.g. "default") each time to update a given snippet in place, or pass --overwrite to replace an existing one.

**Syntax**

`az sre instructions create --agent-name <value> --resource-group <value> --name <value> --value <value> [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of this instance. |
| `--value` | String | Yes |  |  | Prompt snippet as a JSON document of the form {"prompt": "..."} -- the "prompt" field holds the free text (confirmed live round-trip). NOT the portal's 'Custom instructions' box -- use 'az sre agent settings update --value \'{"customInstructions": "..."}\'' for that. |
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

List an agent's named, reusable prompt snippets ('commonPrompts').

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

Let the agent's own managed identity monitor resources outside its own resource group.

Grants/revokes the built-in 'Reader' + 'Monitoring Contributor' roles together on a subscription, resource group, or management group.

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

Configures VNet injection and outbound egress for the agent's own sandboxed tool/code execution -- not the agent resource's inbound access.

| Verb | Exact syntax |
| --- | --- |
| `update` | `az sre network update --name <value> --resource-group <value> [--vnet-configuration <json-or-@file>] [--sandbox-configuration <json-or-@file>]` |

### `az sre network update`

Configure VNet injection and sandbox egress for an SRE Agent (preview).

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

Supports GitHub and Azure DevOps. GitLab isn't exposed by this CLI yet.

| Verb | Exact syntax |
| --- | --- |
| `connect` | `az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-token <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]` |

### `az sre repo connect`

Connect a GitHub or Azure DevOps repo to an SRE Agent in one step.

**Syntax**

`az sre repo connect --agent-name <value> --resource-group <value> --repo-url <value> [--provider {GitHub,AzureDevOps}] [--display-name <value>] [--branch <value>] [--github-token <value>] [--devops-organization <value>] [--devops-auth-type {pat,managed-identity}] [--devops-identity <value>] [--devops-federated-client-id <value>] [--devops-federated-tenant-id <value>]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--repo-url` | String | Yes |  |  | HTTPS clone URL of the repo, e.g. https://github.com/org/repo or https://dev.azure.com/org/project/_git/repo. |
| `--provider` | String | No |  | `GitHub`, `AzureDevOps` | Repo provider. Auto-detected from --repo-url's host when omitted. |
| `--display-name`, `--name`, `-n` | String | No |  |  | Display name for the repo. Defaults to the last path segment of --repo-url. |
| `--branch` | String | No |  |  | Branch to check out. Defaults to the repo's default branch. |
| `--github-token` | String | No |  |  | GitHub token to use directly (GitHub repos only). No 'gh' CLI or Azure CLI needed when this, or the GITHUB_TOKEN/GH_TOKEN env vars, are set. If omitted, this command falls back to a native GitHub OAuth Device Flow in your browser -- no 'gh' required. |
| `--devops-organization` | String | No |  |  | Azure DevOps organization name, e.g. 'contoso' for dev.azure.com/contoso (Azure DevOps repos only; auto-detected from --repo-url when it is a dev.azure.com URL). |
| `--devops-auth-type` | String | No | pat | `pat`, `managed-identity` | Azure DevOps auth mechanism. 'pat' (default) mints a PAT via the vssps REST API -- some orgs block this with a 'DisablePatCreationPolicyViolation' org policy, in which case use 'managed-identity' with --devops-identity instead (the identity must already be added as a user/group member of the Azure DevOps org -- this command does not grant that membership). |
| `--devops-identity` | String | No |  |  | Resource ID of the user- or system-assigned managed identity to authenticate with Azure DevOps as (required when --devops-auth-type managed-identity). Typically the SRE Agent's own identity -- see 'az sre agent show --query identity'. |
| `--devops-federated-client-id` | String | No |  |  | Federated client ID, only needed alongside --devops-federated-tenant-id for a user-assigned identity in a different tenant than the Azure DevOps org (managed-identity auth only; both or neither must be set). |
| `--devops-federated-tenant-id` | String | No |  |  | Federated tenant ID, only needed alongside --devops-federated-client-id (managed-identity auth only; both or neither must be set). |

**Examples**

- Connect a GitHub repo (provider auto-detected from the URL;

  `resolves a token automatically -- explicit flag, or a browser-based device-flow prompt, in that order) az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://github.com/contoso/my-service`
- Connect a GitHub repo with an explicit token (e.g. in CI, where

  `no interactive browser is available) az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://github.com/contoso/my-service \ --github-token $env:GITHUB_TOKEN`
- Connect an Azure DevOps repo

  `az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo`
- Azure DevOps org blocks PAT creation ("org has a policy

  `blocking PAT creation") -- use the agent's own managed identity instead az sre repo connect --agent-name myagent --resource-group myrg \ --repo-url https://dev.azure.com/contoso/my-project/_git/my-repo \ --devops-auth-type managed-identity --devops-identity <agent-identity-resource-id>`

## `az sre response-plan`

Manage incident response plans (portal: Incidents > "Triggers &

response plans"). A plan routes matching incidents to a subagent.

| Verb | Exact syntax |
| --- | --- |
| `create` | `az sre response-plan create --agent-name <value> --resource-group <value> --name <value> --platform <value> --subagent <value> [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--mode <value>] [--disabled {false,true}] [--instructions <value>] [--processing-guide <json-or-@file>] [--overwrite {false,true}]` |
| `delete` | `az sre response-plan delete --agent-name <value> --resource-group <value> --name <value> [--yes]` |
| `disable` | `az sre response-plan disable --agent-name <value> --resource-group <value> --name <value>` |
| `enable` | `az sre response-plan enable --agent-name <value> --resource-group <value> --name <value>` |
| `list` | `az sre response-plan list [--name <value>] [--resource-group <value>] [--agent-url <value>]` |
| `show` | `az sre response-plan show [--agent-name <value>] [--resource-group <value>] [--agent-url <value>] --name <value>` |

### `az sre response-plan create`

Create or update an incident response plan.

Routes incidents that match the criteria to a subagent. Connect the incident platform first ('az sre agent update --incident-management-configuration') and create the subagent first ('az sre subagent create'). Behind the scenes this writes an incident filter, plus an incident handler when --instructions or --processing-guide is given.

**Syntax**

`az sre response-plan create --agent-name <value> --resource-group <value> --name <value> --platform <value> --subagent <value> [--priority <json-or-@file>] [--title-contains <value>] [--title-not-contains <json-or-@file>] [--mode <value>] [--disabled {false,true}] [--instructions <value>] [--processing-guide <json-or-@file>] [--overwrite {false,true}]`

| Option / aliases | Type | Required | Default | Allowed values | Description |
| --- | --- | --- | --- | --- | --- |
| `--agent-name` | String | Yes |  |  | Name of the SRE Agent. |
| `--resource-group`, `-g` | String | Yes |  |  | Name of resource group. You can configure the default group using `az configure --defaults group=<name>` |
| `--name`, `-n`, `--extension-name` | String | Yes |  |  | Name of the response plan. |
| `--platform` | String | Yes |  |  | Incident platform: AzMonitor, PagerDuty, ServiceNow, Icm. |
| `--subagent` | String | Yes |  |  | Name of the existing subagent that handles matched incidents. |
| `--priority` | List | No |  |  | Space-separated priority or severity levels to match (for example Sev0 Sev1 or P1 P2). Default: all. |
| `--title-contains` | String | No |  |  | Only match incidents whose title contains this text. |
| `--title-not-contains` | List | No |  |  | Space-separated texts; skip incidents whose title contains any of them. |
| `--mode` | String | No | autonomous |  | Agent autonomy: autonomous (portal default) or review (agent proposes, you approve). |
| `--disabled` | Boolean | No |  | `false`, `true` | Create the plan turned off. |
| `--instructions` | String | No |  |  | Custom instructions the subagent follows for matched incidents. |
| `--processing-guide` | List | No |  |  | Quoted step-by-step guidance for the subagent, one value per step. |
| `--overwrite` | Boolean | No |  | `false`, `true` | Allow replacing an existing response plan. |

**Examples**

- Route high-severity Azure Monitor incidents to a subagent in review mode

  `az sre response-plan create -g myrg --agent-name myagent -n sev1-api \ --platform AzMonitor --subagent incident-responder --priority Sev0 Sev1 \ --title-contains api --mode review`

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

Show a response plan and its instructions. Use --agent-url to read a shared agent.

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
| `--value` | String | Yes |  |  | Sub-agent configuration as a JSON document. Required fields: instructions/handoffDescription (strings), tools/mcpTools/commonTools/allowedSkills (arrays of strings -- 'tools' is this sub-agent's base tool allowlist, typically just ["ReadFile"] for a read-only specialist), allowParallelToolCalls (bool). Optional: hooks -- {"PreToolUse": [{"type": "command", "matcher": "(?s:.*)", "timeout": 30, "failMode": "block", "script": "..."}]} (also settable via --pre-tool-use-script-file). Live-confirmed shape -- the server echoes back a much richer schema on read (handoffs, connectors, agentsAsTools, maxReflectionCount, temperature, llmModelName, permissions, etc.), all server-defaulted to null when omitted here. |
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

**Examples**

- Create an HTTP tool

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
| `--value` | String | Yes |  |  | Global settings as a JSON document (confirmed via the control plane's own real round-trip integration test, GlobalSettingsExtensionTests.cs). All top-level fields are optional: toolPermissions, toolStatuses/skillStatuses (arrays of {"name": ..., "enabled": true/false}), customInstructions (string), approvalExpirationSetting ({"enabled": true/false, "approvalExpirationInMinutes": <number>}). CAUTION: if you include toolPermissions at all, it must have all three of 'allow'/'ask'/'deny' (each an array of tool-name strings, [] if unused) -- live-confirmed the real API rejects a partial toolPermissions object (e.g. just 'deny') with a misleading "unrecognized property" error. |

**Examples**

- Set the portal's "Custom instructions" text box

  `az sre agent settings update -g myrg --agent-name myagent \ --value '{"customInstructions": "Always cite the runbook section you used."}'`

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
| `--value` | String | Yes |  |  | Plugin install configuration as a JSON document, e.g. {"marketplaceName": "<name from 'sre plugin marketplace list'>", "pluginName": "<plugin>", "source": {"type": "relative", "repo": "<marketplace sourceUrl>", "url": "<plugin's path in the repo>"}}. The 'source' block is required on create -- the service does not auto-resolve it from marketplaceName/pluginName alone. |
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
| `--value` | String | Yes |  |  | Marketplace configuration as a JSON document. Fields: sourceType ("github"), sourceUrl ("owner/repo" short form, NOT a full https:// URL -- a full URL is rejected server-side as an invalid extension configuration), owner ({"name": "..."}), description. Example: {"sourceType": "github", "sourceUrl": "owner/repo", "owner": {"name": "owner"}, "description": "..."}. |
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

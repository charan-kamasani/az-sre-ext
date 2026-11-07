# Connector types

`az sre connector create --data-connector-type` takes the values below. Matching is
case-insensitive, and the portal's names are accepted too.

| Value | Portal name | Notes |
|---|---|---|
| `KustoClient` (default) | Azure Data Explorer | Queries clusters the agent's identity can reach |
| `Kusto` | Azure Data Explorer Cluster | Pins the connector to one cluster; requires `--data-source` |
| `LogAnalytics` | Log Analytics Workspace | |
| `Mcp` | MCP server | Use `--mcp-endpoint`, or `--github` for the GitHub MCP server |
| `Outlook` | Office 365 Outlook | Needs OAuth consent in the portal |
| `Teams` | Microsoft Teams | Needs OAuth consent in the portal |
| `Icm` | IcM connector | |
| `Dgrep` | DGrep | |
| `Ev2Mcp` | EV2 | |
| `GenevaMetrics` | Geneva Metrics | |
| `S360` | S360 connector | |
| `Documentation` | Documentation connector | |
| `AppInsights` | Application Insights | |
| `KnowledgeText` | Knowledge: text | Use `--file-path` |
| `KnowledgeFile` | Knowledge: file | Use `--file-path` |
| `KnowledgeWebPage` | Knowledge: web page | |
| `KnowledgeRepository` | Knowledge: repository | |

The portal's "Additional connectors" catalog (Gmail, SharePoint, OneDrive and others)
has no public API yet, so `az sre` can't create those.

Creating a connector links it to the agent. Check `consentStatus` with
`az sre connector show`, and grant the agent's identity access to the data source.

.. :changelog:

Release History
===============

1.0.0b1
++++++
* Initial release.
* `az sre access list` shows principal object IDs instead of display names by default, so it no longer calls Microsoft Graph. Add `--show-names` to fill in display names from Graph.
* `--assignee-me`, `az sre agent create --grant-access-to-me` and `az sre managed-resource grant/revoke/list` no longer call Microsoft Graph, and `--assignee-me` now resolves the signed-in account in the tenant of `--subscription`.
* `az sre connector update` refuses an update that would clear settings the service never returns. Pass `--data-source` and `--identity` again on every update (`null` for one the connector doesn't have), and all of `--extended-properties` for an MCP connector. Knowledge sources are changed with `az sre knowledge create --overwrite` instead.
* Connector and knowledge commands refuse names such as `..`, which sent the request to the agent itself, before sending anything. New connector names must follow the service's naming rule.
* `az sre knowledge show`, `delete` and `create --overwrite` refuse to act on connectors that aren't knowledge sources.
* `az sre connector list-secret` prints `dataSource`, which Azure CLI hid before.
* Errors from nested `az` commands no longer repeat their arguments, and `az sre knowledge create` keeps its `--data-source` value out of debug logs.
* `az sre connector create --oauth-dcr true` prints the portal link where the sign-in is finished.
* `az sre tool`, `skill`, `hook`, `instructions`, `subagent`, `plugin` and `automation` commands refuse names that are empty, only dots, or contain slashes or control characters before sending anything. Tool and plugin commands show credentials as `******`, keep them out of `--debug` logs, and won't save that mask back as a credential. `az sre skill create` reads SKILL.md frontmatter as YAML, including `tools`, `az sre subagent create --pre-tool-use-script-file` keeps existing PreToolUse hooks, `az sre plugin install create` requires `source`, and list commands return every page. `az sre automation http-trigger invoke` sends your token only to the agent's own endpoint, doesn't follow redirects, and reports a reply that isn't JSON instead of failing. `az sre subagent` commands now work on agents in tenants outside Microsoft: when Azure Resource Manager refuses them, they use the agent's own API, like the other extension commands.
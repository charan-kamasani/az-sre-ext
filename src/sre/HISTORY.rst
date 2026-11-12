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
* `az sre response-plan delete` deletes the match rules before the instructions, uses the agent's own API only when Azure refuses the delete with `AuthorizationFailed`, and fails when the plan wasn't deleted. `az sre response-plan update` removes a criterion or clears the instructions when given an empty value, such as `--title-contains=""`.
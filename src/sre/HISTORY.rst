.. :changelog:

Release History
===============

1.0.0b1
++++++
* Initial release.
* `az sre access list` shows principal object IDs instead of display names by default, so it no longer calls Microsoft Graph. Add `--show-names` to fill in display names from Graph.
* `--assignee-me`, `az sre agent create --grant-access-to-me` and `az sre managed-resource grant/revoke/list` no longer call Microsoft Graph, and `--assignee-me` now resolves the signed-in account in the tenant of `--subscription`.
* `az sre response-plan delete` deletes the match rules before the instructions, uses the agent's own API only when Azure refuses the delete with `AuthorizationFailed`, and fails when the plan wasn't deleted. `az sre response-plan update` removes a criterion or clears the instructions when given an empty value, such as `--title-contains=""`.
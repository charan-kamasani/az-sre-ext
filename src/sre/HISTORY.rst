.. :changelog:

Release History
===============

1.0.0b1
++++++
* Initial release.
* `az sre access list` shows principal object IDs instead of display names by default, so it no longer calls Microsoft Graph. Add `--show-names` to fill in display names from Graph.
* `--assignee-me`, `az sre agent create --grant-access-to-me` and `az sre managed-resource grant/revoke/list` no longer call Microsoft Graph, and `--assignee-me` now resolves the signed-in account in the tenant of `--subscription`.
* `az sre agent create` fails if the agent already exists instead of replacing it; use `az sre agent update`.
* `az sre identity assign/remove` send a PATCH of only the identity block, so they work on agents linked to Application Insights and no longer reset other settings. `identity remove --user-assigned <id>` removes only that identity, and both commands need `--system-assigned` or `--user-assigned`.
* `az sre identity remove` refuses to remove an agent's last identity before sending anything. The service rejects that request but still deletes the system-assigned identity's service principal.
* `az sre agent wait`, `az sre identity wait` and `az sre connector wait` fail when `--timeout` passes instead of exiting 0.
* `az sre agent update` accepts `null` to clear a property, and also clears it on agents linked to Application Insights, where the update is sent as a PATCH.
* `az sre usage list` returns a list of usage items from every page instead of the raw first page. Scripts that read `value` from the old output, such as `--query value`, need to drop it, as in `--query "[]"`.
* `az sre network update` fails when a configuration sets nothing, since null fields can't clear a setting.
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
* `az sre agent create` fails if the agent already exists instead of replacing it; use `az sre agent update`.
* `az sre identity assign/remove` send a PATCH of only the identity block, so they work on agents linked to Application Insights and no longer reset other settings. `identity remove --user-assigned <id>` removes only that identity, and both commands need `--system-assigned` or `--user-assigned`.
* `az sre agent wait`, `az sre identity wait` and `az sre connector wait` fail when `--timeout` passes instead of exiting 0.
* `az sre agent update` accepts `null` to clear a property, and also clears it on agents linked to Application Insights, where the update is sent as a PATCH.
* `az sre usage list` returns a list of usage items from every page instead of the raw first page. Scripts that read `value` from the old output, such as `--query value`, need to drop it, as in `--query "[]"`.
* `az sre network update` fails when a configuration sets nothing, since null fields can't clear a setting.
* `az sre response-plan delete` deletes the match rules before the instructions, uses the agent's own API only when Azure refuses the delete with `AuthorizationFailed`, and fails when the plan wasn't deleted. `az sre response-plan update` removes a criterion or clears the instructions when given an empty value, such as `--title-contains=""`.
* `az sre repo connect` stops before fetching a token when the agent already has a repository with the same display name that points to a different URL. Pass `--display-name` for another name, or the new `--overwrite` to replace it. Running it again for the same URL keeps the repository's other settings, such as its branch, sparse checkout paths and feed credentials; feed credentials whose PAT the agent doesn't return are dropped with a warning. A warning names the other repositories that share the GitHub or Azure DevOps credential being saved.
* `az sre repo connect` only accepts plain https URLs on github.com, dev.azure.com and `<organization>.visualstudio.com`, also with `--provider`, and rejects URLs that contain a user name or token. It reports when the Azure DevOps PAT it creates expires (after 30 days, also as `patExpiresOn` in the output), shows why Azure DevOps refused to create one, and revokes it when interrupted before it is saved.
* `az sre endpoint show` keys entries in `sreAgentConnections.json` by subscription, resource group and agent name, so same-named agents in two subscriptions no longer replace each other. It writes the file in one step and reads files saved with a UTF-8 byte order mark.

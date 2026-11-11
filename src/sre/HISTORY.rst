.. :changelog:

Release History
===============

1.0.0b1
++++++
* Initial release.
* `az sre access list` shows principal object IDs instead of display names by default, so it no longer calls Microsoft Graph. Add `--show-names` to fill in display names from Graph.
* `--assignee-me`, `az sre agent create --grant-access-to-me` and `az sre managed-resource grant/revoke/list` no longer call Microsoft Graph, and `--assignee-me` now resolves the signed-in account in the tenant of `--subscription`.
* `az sre repo connect` stops before fetching a token when the agent already has a repository with the same display name that points to a different URL. Pass `--display-name` for another name, or the new `--overwrite` to replace it. A warning names the other repositories that share the GitHub or Azure DevOps credential being saved.
* `az sre repo connect` only accepts plain https URLs on github.com, dev.azure.com and `<organization>.visualstudio.com`, also with `--provider`, and rejects URLs that contain a user name or token. It reports when the Azure DevOps PAT it creates expires (after 30 days, also as `patExpiresOn` in the output), shows why Azure DevOps refused to create one, and revokes it when interrupted before it is saved.
* `az sre endpoint show` keys entries in `sreAgentConnections.json` by subscription, resource group and agent name, so same-named agents in two subscriptions no longer replace each other. It writes the file in one step and reads files saved with a UTF-8 byte order mark.
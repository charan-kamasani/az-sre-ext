# CLI shape design: alternatives and decisions

This document records the structural ("shape") decisions behind the `az sre`
command surface -- not what each command does, but how the whole noun/verb
hierarchy is organized, what alternatives were considered, and why we picked
what we picked. Written in response to Paul's shape-review feedback (points
#1 and #13): decide and document the shape as priority zero, and show
alternatives/tradeoffs rather than just the final answer.

See [docs/cli-reference.md](cli-reference.md) for the generated, exhaustive
listing of the resulting shape (23 groups, 69 commands).

## Decision 1: Is `agent` a useful top-level group for everything?

**Question Paul raised:** should every agent-scoped resource (connectors,
tools, skills, hooks, etc.) live *under* `agent` -- e.g.
`az sre agent connector create` -- or stand on their own as flat, top-level
nouns -- e.g. `az sre connector create`?

### Alternative A: Nest everything under `agent`

```
az sre agent create
az sre agent connector create
az sre agent tool create
az sre agent skill create
az sre agent identity assign
az sre agent access grant
```

**Pros:**
- Mirrors the underlying ARM resource hierarchy exactly (every one of these
  is a sub-resource, or an extension, of a single `Microsoft.App/agents`
  resource) -- arguably the most "honest" shape.
- One mental anchor: "everything starts with `az sre agent ...`."
- Matches how a few other `az` extensions nest tightly-coupled children under
  their parent resource (e.g. `az webapp config ...`).

**Cons:**
- Every command line gets longer and more repetitive (`agent` appears in
  100% of commands, carrying zero information once the user already knows
  this is the SRE Agent CLI).
- Tab-completion and `--help` under `az sre agent` would have to list 10+
  unrelated subgroups (`connector`, `tool`, `skill`, `hook`, `identity`,
  `access`, `knowledge`, `managed-resource`, `network`, `repo`, `plugin`,
  `usage`, `endpoint`, `workflow`...) in one flat list -- the opposite of the
  discoverability Paul asked for; it just moves the flat list one level
  deeper instead of removing it.
- Inconsistent with how the Azure CLI generally treats child/extension
  resources of a parent ARM resource when there are many unrelated ones
  (most `az` extensions with >5 child resource types promote them to
  top-level nouns once the list gets large -- e.g. `az keyvault key`,
  `az keyvault secret`, `az keyvault certificate` are top-level under
  `keyvault`, not `keyvault vault key`).
- `agent` already has its own real verbs that are NOT about child resources
  (`create`, `delete`, `start`, `stop`, `list-models`, `wait`) -- mixing
  "manage the agent resource itself" and "manage everything attached to an
  agent" under the same noun conflates two different concerns.

### Alternative B (chosen): Flat top-level nouns, `agent` scoped to core lifecycle only

```
az sre agent create / delete / list / show / start / stop / update / wait / list-models
az sre connector create / delete / list / show / update / list-secret
az sre tool create / delete / list / show
az sre skill create / delete / list / show
az sre identity assign / remove / show
az sre access grant / revoke
...
```

Every command still requires `--agent-name`/`-n` + `--resource-group` to say
*which* agent a connector/tool/skill/etc. belongs to -- so the ARM parent-child
relationship is still fully expressed in the arguments, just not in the noun
path.

**Pros:**
- Matches the majority convention in large `az` extensions once a resource
  has more than a handful of distinct child/extension types (same pattern as
  `az keyvault key/secret/certificate`, `az sql server/db/firewall-rule`).
- Each top-level noun's own `--help` is short and scoped to just that
  resource's own verbs -- much better cold-start discoverability (directly
  verified in this session's live grading exercise: a brand-new user found
  `az sre connector --help` / `az sre tool --help` self-explanatory without
  needing to first discover they live under `agent`).
- Keeps `agent`'s own command group small and focused on actual agent
  lifecycle (9 commands), instead of ballooning to 15 subgroups covering
  unrelated concerns.
- `az sre <noun> --help` at the top level (`az sre --help`) gives one flat
  list of ~15 nouns with one-line summaries each -- a single scan tells you
  everything the CLI can touch, which is what `docs/cli-reference.md`'s
  top-level table now shows.

**Cons:**
- Loses the one-to-one mapping to the ARM resource hierarchy at a glance --
  someone reading just the command name can't immediately tell "this is a
  sub-resource of agent" vs "this is a free-standing top-level resource."
  Mitigated by: every subcommand's required `--agent-name`/`-n` argument
  makes the relationship explicit at the argument level, and every group's
  one-line `--help` summary says "...for an SRE Agent" explicitly (see the
  group table in cli-reference.md, e.g. `connector`: "Connect an SRE Agent to
  an external data source...").
- Slightly more top-level nouns to scan in `az sre --help` (15, vs. ~5 if
  only truly independent resources were top-level) -- judged an acceptable
  tradeoff against the discoverability win above.

**Decision: Alternative B.** Implemented as-is in `custom.py` today (verified
by direct inspection 2026-10-29): 15 top-level `@register_command_group("sre
...")` groups, with `agent` itself registering only the 9 core-lifecycle
commands (`create/delete/list/show/start/stop/update/wait/list-models`) and
nothing else. This was a working assumption adopted early, but had never been
written down with the alternative explicitly compared -- this document closes
that gap.

## Decision 2: How to group the 15 runbook-extension types

**Question:** the underlying service models 15 different "runbook extension"
types (`tools`, `skills`, `commonPrompts`, `hooks`, `pluginMarketplaces`,
`pluginInstallations`, `repositories`, `incidentFilters`, `incidentHandlers`,
`githubAuths`, `azureDevOpsAuths`, `scheduledTasks`, `subagents`, plus two
more) through one generic underlying REST shape
(`.../agents/{name}/{extensionType}[/{name}]`, base64-encoded YAML payload).
Should the CLI expose one generic noun (`az sre extension create
--type tool ...`) or a dedicated noun per type?

### Alternative A: One generic `extension` noun

```
az sre extension create --type tool --name mytool --value <json>
az sre extension create --type skill --name myskill --value <json>
az sre extension create --type hook --name myhook --value <json>
```

**Pros:**
- Minimal code: one set of CRUD commands handles all 15 types via a
  `--type` flag.
- New extension types the service adds later need zero new CLI code.

**Cons:**
- Every type has its own required/optional fields inside `--value`'s JSON
  blob (e.g. a hook needs a trigger event; a scheduled-task needs a cron
  expression) -- a generic noun pushes all of that type-specific validation
  and help text onto the user, with `--help` unable to say anything more
  specific than "JSON document, shape depends on --type."
  This was live-confirmed to be a real discoverability problem during this
  session's cold-start grading exercise.
- `--type` values are raw internal names (`commonPrompts`, not
  "instructions"), so users would need to already know the internal data
  model to use the CLI at all -- directly conflicts with Paul's feedback
  point #4 (use understandable names, not raw internal ones).

### Alternative B (chosen): Dedicated top-level noun per type, with type-specific help/args

```
az sre tool create --agent-name ... --name mytool --value <json>
az sre skill create --agent-name ... --name myskill --file-path SKILL.md
az sre hook create --agent-name ... --name myhook --event <event> --value <json>
az sre instructions create --agent-name ... --value <json>   # was commonPrompts
az sre plugin marketplace create ...
az sre plugin install create ...
az sre repo connect --agent-name ... --repo-url <url>
```

**Pros:**
- Each noun gets its own focused `--help`, its own examples, and (where it
  helps) convenience args that hide the raw JSON shape entirely (e.g.
  `skill create --file-path SKILL.md`, `repo connect --repo-url` auto-detects
  the provider, `tool create`'s `--value` has type-specific guidance).
- Names are user-facing and understandable (`instructions` instead of
  `commonPrompts`, `repo connect` instead of `extension create --type
  repositories`) -- directly addresses Paul's naming feedback (#4).
- Matches the structure Paul specifically asked for in feedback point #7:
  "separate instructions / skills / tools / subagents / automations" as
  distinct concepts, not one generic bucket.

**Cons:**
- More code: 12 of the 15 types each have their own dedicated
  create/show/list/delete command set (`subagents`/`scheduledTasks` are
  permanently out of CLI scope as a platform boundary; see PLAN.md).
- A brand-new extension type added by the service later needs new CLI code
  before it's usable (no auto-coverage via a generic noun). Accepted as the
  right tradeoff: discoverability for the ~15 types that exist today
  outweighs zero-code support for hypothetical future types that don't yet.

**Decision: Alternative B.** Implemented today: the generic `extension` noun
was removed entirely (confirmed in `docs/cli-reference.md`'s "Important
caveats" section: *"there is no generic `extension` escape hatch anymore"*).

## Open sub-question still not fully resolved

`workflow` groups `scheduled-task`/`http-trigger`/`incident-filter` as
subcommands, but the service/portal calls this concept "automation," not
"workflow" (see Paul's feedback point #8, tracked separately in
`paul_shape_feedback` id=8). This is a naming question within an already
flat/dedicated-noun shape, not a re-litigation of Decisions 1 or 2 above --
left open pending a decision on renaming `workflow` -> `automation`.

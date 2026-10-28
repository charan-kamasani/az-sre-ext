# Source code guide

## Intro

`az sre` is one `Microsoft.App/agents` ARM resource family wrapped by the
usual two-layer Azure CLI extension shape: generated AAZ recipes for plain
CRUD, plus a thin hand-written overlay (`custom.py`) for everything a
Swagger spec cannot express — enum normalization, a hand-maintained
preview api-version with no public spec, GET-merge-PUT read-modify-write
helpers, and base64/JSON codec logic for the agent's runbook extension
payloads. This mirrors `azext-aigateway`'s structure deliberately (see
[PLAN.md](../PLAN.md) for why).

## Repository map

```
src/sre/
  azext_sre/
    __init__.py       # SreCommandsLoader: registers the generated AAZ
                       # package, then layers custom.py recipes on top
    commands.py        # load_command_table: renames every generated
                       # "app ..." entry to "sre ...", auto-discovers
                       # every AAZCommand subclass in custom.py
    _help.py           # generated, intentionally empty (knack `helps`
                       # dict is unused here -- see docs/cli-reference.md)
    _params.py          # generated argument wiring
    custom.py           # ALL hand-written behavior -- the only file you
                       # should normally be editing
    aaz/latest/app/agent/...  # generated recipes, DO NOT hand-edit
    tests/latest/
      test_sre.py       # generated scaffold test (left as-is)
      test_custom.py    # the real test suite -- every hand-written
                       # behavior in custom.py
  dist/                # built wheel artifacts (gitignored except CI)
scripts/
  generate_cli_reference.py  # regenerates docs/cli-reference.md
.github/workflows/
  ci.yml               # unit tests -> cli-reference drift check -> wheel build
.github/workflows-future/
  release.yml          # parked full release pipeline, not yet wired up
.githooks/
  pre-commit           # regenerates + stages docs/cli-reference.md
docs/                  # this guide and its siblings
PLAN.md                # architecture decisions, evidence, roadmap
```

## Why the "app" → "sre" rename exists

The SRE Agent Swagger's RP folder is literally `app`
(`Microsoft.App/agents`), so every generated recipe under
`aaz/latest/app/agent/...` is registered by `load_aaz_command_table` as
`app agent ...`. There is no equivalent of `azext-aigateway`'s mismatch
(that extension needed to remap only one leaf, `model-provider`) — here the
*entire* top-level group needs renaming. `__init__.py` remaps a leading
`"sre"` in the lazy-load args to `"app"` purely so `load_aaz_command_table`
finds the right generated module to import; `commands.load_command_table`
then renames every resulting `"app ..."` table/group key back to `"sre
..."` before layering `custom.py`'s overrides on top (which always win,
since they're registered last).

## How a command flows

1. `az sre connector create ...` is typed.
2. The Azure CLI core calls `SreCommandsLoader.load_command_table(args)`.
3. `__init__.py` remaps the leading `sre` to `app` for the *lazy-load args
   only*, then calls `load_aaz_command_table`, which imports and registers
   only the generated modules relevant to this path (e.g.
   `aaz/latest/app/agent/connector/_create.py`).
4. `commands.load_command_table` renames every `app ...` key just
   registered back to `sre ...`, then scans `vars(custom)` for every
   `AAZCommand`/`AAZCommandGroup` subclass defined *in custom.py itself*
   (`value.__module__ == custom.__name__`) and registers each under its own
   `AZ_NAME`, overwriting the generated entry if one exists.
5. For `connector create`, `custom.ConnectorCreate` (a thin subclass of the
   generated `_GeneratedConnectorCreate`) wins. It mixes in
   `_DataConnectorTypeArgMixin`, which merges real enum/help metadata into
   the generated `--data-connector-type` argument's `_help` dict (never
   overwrites it — see the regression class below for why that distinction
   matters) and calls `_normalize_data_connector_type` on the parsed value
   before the generated `super()` request logic runs.
6. The request is sent using the pinned `API_VERSION` (or
   `NETWORK_API_VERSION` for `network update`, which is fully hand-written —
   see [the networking guide](networking.md)).

## Why `custom.py` exists (and what's in it)

Everything in `custom.py` falls into one of these categories:

- **Pure renaming wrappers** (`Create`, `Update`, `Show`, `List`, `Delete`,
  `Start`, `Stop`, and the `Connector*` classes) — thin subclasses of
  generated commands whose only job is to exist in `custom.py` so
  `commands.py`'s auto-discovery picks them up under the `sre` name. They
  add zero behavior beyond small, deliberate overlays like
  `_ModelProviderArgMixin`/`_DataConnectorTypeArgMixin`.
- **Real-world-validated argument metadata** the generated Swagger left as
  bare, unhelpful strings — e.g. `--model-provider` and
  `--data-connector-type` enums, grounded in the real `az rest`-probed
  values (see [PLAN.md](../PLAN.md) and
  [docs/operations.md](operations.md)), not just the Swagger's declared
  enum.
- **Client-side normalization with a real `CLIError`** —
  `_normalize_model_provider`/`_normalize_data_connector_type` validate the
  caller's string against the confirmed enum and raise `CLIError` (not a
  bare `ValueError`, which AAZ's `pre_operations()` hook does **not**
  convert to a clean one-line error — it surfaces as an unhandled
  traceback instead).
- **Fully hand-written commands with no generated counterpart**:
  `ConnectionShow`, `UsageList`, `AccessGrant`/`AccessRevoke` (a thin
  wrapper over `az role assignment create` that builds the agent's full
  resource-ID scope), `ManagedResourceGrant`/`Revoke`/`List` (the mirror
  image — grants the agent's own managed identity access to an external
  scope instead), `NetworkUpdate` (GET-merge-PUT against a preview
  api-version with no public Swagger yet), and the entire `Extension*`
  family (runbook extension CRUD against the agent's data-plane proxy
  endpoints, including the base64/JSON
  `_encode_extension_value`/`_decode_extension_envelope` codec and the
  per-extension-type `EXTENSION_VALUE_VALIDATORS`) along with its dedicated
  front-door nouns (`Tool*`, `Skill*`, `Hook*`, `Instructions*`,
  `Knowledge*`, `Repo*`/`RepoConnect`, `Plugin*`).
- **Connector secret-handling**: `_connector_consent_status`/
  `_annotate_connector_consent_status` add a derived `consentStatus` field
  to connector output without ever touching the underlying secret value,
  and `ConnectorShow`/`ConnectorList` wrap the generated calls to apply it.

## What's regenerated from Swagger and what is not

### Regenerated (do not hand-edit)

Everything under `azext_sre/aaz/latest/app/agent/...` — agent, connector,
and (if/when a public Swagger adds them) extension CRUD. Regenerate with
`aaz-dev` against the pinned `API_VERSION` (`2026-01-01`) if the Swagger
changes; see [development.md](development.md).

### Not regenerated (hand-maintained in `custom.py`)

- `network update` — the real deployed api-version
  (`2026-11-01-preview`) has no public Swagger; the shape was read directly
  from the internal control-plane source with repo access, not from any
  spec. Re-verify against that source if the service's shape ever changes.
- `extension *` (and its dedicated front-door nouns `tool`, `skill`, `hook`,
  `instructions`, `knowledge`, `repo connect`, `plugin marketplace`/`plugin
  install`) — the data-plane extension CRUD proxy endpoints have no ARM
  Swagger at all; payload shapes for each of the 15 extension types are
  confirmed one at a time by live verification against a real agent (12 of
  15 live-verified so far; see [operations.md](operations.md) for the full
  confirmed/unconfirmed table).
- `access grant`/`access revoke` — not a new ARM operation, a convenience
  wrapper over an existing generic command. `managed-resource
  grant`/`revoke`/`list` is the same pattern in the other direction (grants
  the agent's own identity access to an external scope).
- `--model-provider`/`--data-connector-type` enum values — the Swagger
  declares these as bare strings; the real enum came from live `az rest`
  probing, not the spec.

## Making common changes safely

- **Adding a new confirmed extension-type shape**: add a
  `_validate_<type>_shape()` function, register it in
  `EXTENSION_VALUE_VALIDATORS`, update the `--value` help text, add a
  `*ShapeValidationTests` class to `test_custom.py`, then live-verify
  end-to-end (create → GET round-trip → delete) before calling it
  confirmed. Do not trust a 200 response alone — the data plane silently
  sanitizes/drops unrecognized fields instead of rejecting them (this is
  exactly how the original `commonPrompts` shape assumption was wrong).
- **Adding a new hand-written argument mixin**: always add a regression
  test that builds the real arg schema and calls `to_cmd_arg()` (see
  `ArgSchemaHelpRegressionTests`), not just a test that checks help-text
  presence. `AAZBaseArg._help` must always stay a dict
  (`arg._help["short-summary"] = ...`, never `arg._help = "..."`) — a plain
  overwrite silently breaks `-h` later, and the breakage can be dormant if
  the arg instance a mixin thinks it's touching isn't actually reachable at
  schema-build time for every sibling command using the same mixin.
- **After any `custom.py` change**: rebuild the wheel
  (`python -m build --wheel` in `src/sre`) and reinstall it
  (`az extension remove --name sre` then `az extension add --source
  dist/sre-*.whl -y`) before live-testing. The installed extension is a
  wheel snapshot, not a live symlink to source — testing without
  rebuilding silently tests stale code. See
  [docs/testing.md](testing.md#live-verification-workflow).

## Security boundaries

- `connector list-secret` is the only command that can return connector
  secret material. Every other connector command recursively redacts
  secrets from output.
- The generated `--debug` flag will print raw request/response bodies
  including any secret fields present on the wire — use it only against
  disposable test resources, never against anything with real customer
  data.

# Source code guide

## Intro

`az sre` is one `Microsoft.App/agents` ARM resource family wrapped by the
usual two-layer Azure CLI extension shape: generated AAZ recipes for plain
CRUD, plus a thin hand-written overlay (`custom.py`) for everything a
Swagger spec cannot express — enum normalization, a hand-maintained
preview api-version with no public spec, GET-merge-PUT read-modify-write
helpers, and base64/JSON codec logic for the agent's runbook extension
payloads. See
[PLAN.md](../PLAN.md) for why.

## Repository map

```
src/sre/
  azext_sre/
    __init__.py       # SreCommandsLoader: registers the generated AAZ
                       # package, then layers custom.py recipes on top
    commands.py        # load_command_table: auto-discovers every
                       # AAZCommand subclass in custom.py
    _help.py           # group examples applied after load (see comments)
    _params.py          # generated argument wiring
    custom.py           # ALL hand-written behavior -- the only file you
                       # should normally be editing
    aaz/latest/sre/...  # generated recipes, DO NOT hand-edit
    tests/latest/
      test_sre.py       # generated scaffold test (left as-is)
      test_custom.py    # the real test suite -- every hand-written
                       # behavior in custom.py
  dist/                # built wheel artifacts (gitignored except CI)
scripts/
  generate_sre_extension.py  # regenerates azext_sre/aaz from specification/
  generate_cli_reference.py  # regenerates docs/cli-reference.md
specification/         # pinned SRE Agent Swagger (generator input)
.github/workflows/
  ci.yml               # unit tests (Python 3.10-3.13) -> reference drift check -> wheel build + clean-CLI verify
.github/workflows-future/
  release.yml          # parked full release pipeline, not yet wired up
.githooks/
  pre-commit           # regenerates + stages docs/cli-reference.md
docs/                  # this guide and its siblings
PLAN.md                # architecture decisions, evidence, roadmap
```

## Generated command names

The SRE Agent Swagger's RP folder is `app` (`Microsoft.App/agents`), so
aaz-dev would name the generated commands `app agent ...` by default.
`scripts/generate_sre_extension.py` shapes the aaz-dev workspace before code
generation instead: it renames `app` to `sre`, moves the connector and
identity subgroups to the top-level `sre connector`/`sre identity` nouns,
renames `supported-agent-model list` to `sre agent list-models`, and leaves
out the superseded `listConnectorsWithSecrets` action. The generated code
under `aaz/latest/sre/...` therefore already carries the final public names,
and nothing is renamed or removed when the extension loads.

## How a command flows

1. `az sre connector create ...` is typed.
2. The Azure CLI core calls `SreCommandsLoader.load_command_table(args)`.
3. `__init__.py` calls `load_aaz_command_table`, which imports and
   registers only the generated modules relevant to this path (e.g.
   `aaz/latest/sre/connector/_create.py`).
4. `commands.load_command_table` scans `vars(custom)` for every
   `AAZCommand`/`AAZCommandGroup` subclass defined *in custom.py itself*
   (`value.__module__ == custom.__name__`) and registers each under its own
   `AZ_NAME`, overwriting the generated entry of the same name.
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

- **Thin overrides of generated commands** (`Create`, `Update`, `Show`, `List`, `Delete`,
  `Start`, `Stop`, and the `Connector*`/`Identity*` classes) — subclasses
  registered under the same `sre` name as the generated command they extend.
  They add small, deliberate overlays like
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
  scope instead), `NetworkUpdate` (a networking-only PATCH against a preview
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

Everything under `azext_sre/aaz/latest/sre/...` — agent, connector,
identity and `agent list-models`. Regenerate with
`scripts/generate_sre_extension.py` from the pinned Swagger under
`specification/` (api-version `2026-01-01`); see
[CONTRIBUTING.md](../CONTRIBUTING.md#regenerating-the-generated-code).

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
  secrets from output. `list-secret` turns off HTTP request/response
  tracing for its own call, so `--debug` does not write the secrets to
  logs. Store its output securely and never commit it.
- The generated `--debug` flag still prints raw request/response bodies
  for every other command, including any secret fields on the wire (for
  example the token sent by `repo connect`). Use it only against
  disposable test resources, never against anything with real customer
  data, and redact logs before sharing them or attaching them to a
  support request.

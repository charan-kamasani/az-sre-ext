# Development guide

## Architecture

`az sre` follows the standard generated-AAZ-plus-hand-written-overlay pattern:
AAZ-generated recipes under `azext_sre/aaz/latest/`
cover plain ARM CRUD for `Microsoft.App/agents` and its `connectors` child
resource; `azext_sre/custom.py` is the only file with hand-written
behavior. See [docs/source-code.md](source-code.md) for the full map and
request-flow walkthrough.

## References

- SRE Agent ARM resource: `Microsoft.App/agents`, pinned
  `API_VERSION = "2026-01-01"` (must match whatever `aaz/latest` was
  generated against — see `custom.py`'s top-of-file comment).
- Networking fields (`network update`): the real deployed
  `2026-11-01-preview` api-version, confirmed live via `az provider show
  --namespace Microsoft.App`, no public Swagger yet.
- `PLAN.md` documents every architecture decision with its evidence —
  read it before making a structural change.

## Local validation

```bash
cd src/sre
pip install azure-cli-core azure-cli-testsdk msrest azure-common build setuptools wheel
python -m unittest discover -s azext_sre/tests -v
```

This is the same command CI runs (`.github/workflows/ci.yml`). It is fully
credential-free — no Azure login required.

## Regenerating the CLI reference

```bash
python scripts/generate_cli_reference.py
```

This introspects the loaded `SreCommandsLoader` command table (via a
hand-maintained set of probe paths — see the script's module docstring for
why, and why a new command group needs a new probe path added) and
re-renders `docs/cli-reference.md` deterministically. Check for drift
without writing:

```bash
python scripts/generate_cli_reference.py --check
```

CI runs this check after the unit tests and fails the build if the
reference is stale.

## Commit hook

Install the repository-tracked hook once per checkout:

```bash
git config core.hooksPath .githooks
```

`.githooks/pre-commit` regenerates and stages `docs/cli-reference.md` on
every commit attempt, then re-runs the generator in `--check` mode so a
commit still fails loudly if something unexpected is going on (e.g. the
environment's `azure-cli-core` can't be found).

## Rebuilding and reinstalling the extension locally

The installed extension (`~/.azure/cliextensions/sre` on this machine) is a
built wheel snapshot, not a live symlink to source. After any change to
`custom.py` (or anything else under `azext_sre/`), rebuild and reinstall
before live-testing against a real agent:

```bash
cd src/sre
python -m build --wheel
az extension remove --name sre
az extension add --source dist/sre-1.0.0b1-py3-none-any.whl -y
```

Skipping this step silently tests stale code — see
[docs/testing.md](testing.md#live-verification-workflow) for the full
live-verification workflow this unlocks.

## Regenerating AAZ recipes

If the `Microsoft.App/agents` Swagger changes (a new field, a new
api-version), update `specification/` and rerun
`scripts/generate_sre_extension.py` (see
[CONTRIBUTING.md](../CONTRIBUTING.md#regenerating-the-generated-code)) to
regenerate `azext_sre/aaz/latest/sre/...`. Never hand-edit anything under
`aaz/latest/` — put any behavior the generator can't express in
`custom.py` instead (see [docs/source-code.md](source-code.md#what-is-regenerated-from-swagger-and-what-is-not)
for the full list of what's already hand-maintained and why).

## Artifact and release policy

- CI (`.github/workflows/ci.yml`) runs the unit tests on Python 3.13
  with a pinned Azure CLI, checks the CLI reference, builds a wheel, installs
  it into a clean pinned Azure CLI and into the minimum supported Azure CLI
  (`azext.minCliCoreVersion`) and loads every documented command, then uploads
  the wheel as a build artifact — this is a development convenience, not
  a release.
- A full production-grade release pipeline (swagger-drift
  validation, codegen-drift check, SBOM, signed releases) is parked at
  `.github/workflows-future/release.yml`. It is intentionally not
  auto-discovered by GitHub Actions (only `.github/workflows/` is) until
  this project needs signed release artifacts.
- Do not produce release wheel artifacts on a developer workstation once
  that pipeline is wired up — release wheels must come from a compliant
  pipeline.

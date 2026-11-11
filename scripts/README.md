# CI/CD scaffolding status

`.github/workflows/ci.yml` runs on every push/PR:

- **build-and-test** (Windows/macOS/Linux): unit tests; on Linux also the
  CLI reference check and the wheel build/upload. The toolchain is pinned
  (`azure-cli-core==2.92.0`, `build`, `setuptools`, `wheel`, ...) so an
  upstream release can't break CI unannounced; bump pins deliberately.
- **azdev-lint**: `check_command_loader.py`, `azdev style sre` and
  `azdev linter` at medium severity, using the AI Gateway lint config
  vendored in `.github/lint-config/`. `azdev`, `pylint`, `flake8` and the
  Azure CLI source (tag `azure-cli-2.92.0`) are pinned. Fails if the linter cannot load the
  extension (which would otherwise "pass" with zero commands checked).
- **wheel-smoke** (Linux on Azure CLI 2.75.0 minimum and 2.81.0 pinned;
  Windows and macOS on 2.81.0): `verify_installed_wheel.py` installs the
  exact built wheel into a
  clean CLI and checks versions (filename, `az extension show`, `az version`
  and `az sre version` must agree), `--help` for every documented command, that
  the installed inventory matches `docs/cli-reference.md`, and that unknown
  arguments are rejected. Run it locally with
  `python scripts/verify_installed_wheel.py src/sre/dist/sre-<version>-py3-none-any.whl`.
- **regeneration-drift**: regenerates the aaz code from pinned Azure/aaz
  models and rejects any diff.

`.github/workflows/live-canary.yml` runs weekly (Monday 07:17 UTC) and on
manual dispatch, never on pull requests. It builds the wheel, installs it into
Azure CLI 2.81.0, signs in with OIDC and runs `scripts/live_canary.py` against
real Azure: agent create/show/list/update/stop/start/delete, instructions and
knowledge round trips, RBAC grant/revoke with independent `az role assignment`
checks, negative cases, and a scan of all captured output (including `--debug`)
for access tokens. Every run uses a uniquely named resource group that is
always deleted; `live-canary.json` (steps and pass/fail only, no raw output) is
uploaded as evidence. Setup: a `live-canary` environment with
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` (optional
`AZURE_LOCATION`) for a federated identity with Contributor and User Access
Administrator on the subscription. Run locally after `az login` with
`python scripts/live_canary.py --subscription <id>` (add `--skip-rbac` without
role-assignment rights).

`.github/workflows-future/release.yml` holds a full production-grade
release pipeline (swagger validation, `aaz-dev` codegen-drift check, SBOM,
signed releases). It is intentionally parked here — not auto-discovered by
GitHub Actions (only `.github/workflows/` is) — until this project actually
needs signed release artifacts. See [PLAN.md](../PLAN.md) for the full
status/roadmap.

## What's still manual
- Client-side validation logic not expressible in the Swagger (model-provider
  enum normalization, the planned `--data-connector-type` enum) is
  hand-written in `custom.py` regardless of CI maturity.

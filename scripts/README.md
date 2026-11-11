# CI/CD scaffolding status

`.github/workflows/ci.yml` runs on every push/PR:

- **build-and-test** (Windows/macOS/Linux): unit tests; on Linux also the
  CLI reference check and the wheel build/upload. The toolchain is pinned
  (`azure-cli-core==2.92.0`, `build`, `setuptools`, `wheel`, ...) so an
  upstream release can't break CI unannounced; bump pins deliberately.
- **azdev-lint**: `check_command_loader.py`, `azdev style sre` and
  `azdev linter` at medium severity, using the ADC Python lint config
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
knowledge round trips (values read back and compared), RBAC grant/revoke with
`--assignee-me` and independent `az role assignment` checks, negative cases,
and a scan of all captured output (including `--debug`) for access tokens.
`live-canary.json` (steps and pass/fail only, no raw output) is uploaded as
evidence; it reports `passed: true` only if every scenario ran to the end.

Each run creates a uniquely named resource group, tagged
`purpose=sre-live-canary`, `sre-canary-run=<nonce>` and
`sre-canary-created=<UTC time>`. The script refuses to start (exit code 2) if
the group already exists, and deletes only a group it created and tagged with
its own nonce. Every `az` call has a timeout (15 minutes for long-running
operations, 3 otherwise). Deletion is best effort: the workflow signs in again
and deletes the run's group even if the canary fails, and warns if it can't.
A sweep step then deletes any `purpose=sre-live-canary` group whose
`sre-canary-created` tag is more than 6 hours old, so a group left behind by a
failed cleanup is removed by the next run at the latest. Groups from local runs
in the same subscription (including `--keep`) are swept too.

Setup:

1. Create a `live-canary` environment and limit its deployment branches to
   `master` (optionally add required reviewers). The OIDC subject doesn't
   include the branch, so without this rule anyone who can push a branch can
   dispatch a modified workflow and get a token for the identity.
2. Set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID` and `AZURE_SUBSCRIPTION_ID`
   (optional `AZURE_LOCATION`) as variables on that environment.
3. Add a federated credential to the identity with issuer
   `https://token.actions.githubusercontent.com`, audience
   `api://AzureADTokenExchange` and subject
   `repo:charan-kamasani/az-sre-ext:environment:live-canary`.
4. Use a dedicated subscription if possible. Grant the identity Contributor and
   Role Based Access Control Administrator, with a condition that limits it to
   assigning and deleting the four SRE Agent roles (SRE Agent Administrator,
   SRE Agent Standard User, SRE Agent Author, SRE Agent Reader). Don't use User
   Access Administrator or Owner: either is enough to grant Owner. No Microsoft
   Graph permission is needed.

Run locally after `az login` with
`python scripts/live_canary.py --subscription <id>` (add `--skip-rbac` without
rights to assign the SRE Agent roles).

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

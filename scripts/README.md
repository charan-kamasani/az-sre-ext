# CI/CD scaffolding status

`.github/workflows/ci.yml` runs on every push/PR:

- **build-and-test** (Windows/macOS/Linux): unit tests; on Linux also the
  CLI reference check and the wheel build/upload.
- **azdev-lint**: `check_command_loader.py`, `azdev style sre` and
  `azdev linter` at medium severity, using the AI Gateway lint config
  vendored in `.github/lint-config/`. Fails if the linter cannot load the
  extension (which would otherwise "pass" with zero commands checked).
- **wheel-smoke** (Windows/macOS/Linux × Azure CLI 2.75.0 minimum and 2.81.0
  pinned): `verify_installed_wheel.py` installs the exact built wheel into a
  clean CLI and checks versions, `--help` for every documented command, that
  the installed inventory matches `docs/cli-reference.md`, and that unknown
  arguments are rejected. Run it locally with
  `python scripts/verify_installed_wheel.py src/sre/dist/sre-<version>-py3-none-any.whl`.
- **regeneration-drift**: regenerates the aaz code from pinned Azure/aaz
  models and rejects any diff.

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

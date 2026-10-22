# CI/CD scaffolding status

`.github/workflows/ci.yml` runs a minimal build/test pipeline on every push/PR:
checkout → install deps → run the full unit test suite
(`azext_sre/azext_sre/tests/`) → build a wheel → upload it as an artifact.
Confirmed green on `charan-kamasani/az-sre-ext`.

`.github/workflows-future/release.yml` holds a full `azext-aigateway`-style
release pipeline (swagger validation, `aaz-dev` codegen-drift check, SBOM,
signed releases). It is intentionally parked here — not auto-discovered by
GitHub Actions (only `.github/workflows/` is) — until this project actually
needs signed release artifacts. See [PLAN.md](../PLAN.md) for the full
status/roadmap.

## What's still manual
- The `app` → `sre` command-group rename is done via thin `custom.py`
  subclasses of each generated command (see `azext_sre/custom.py`), not at
  generation time — generated recipes under `aaz/latest/app/agent/...` still
  use the Swagger's own `app` folder name, which is expected and should not
  be "fixed".
- Client-side validation logic not expressible in the Swagger (model-provider
  enum normalization, the planned `--data-connector-type` enum) is
  hand-written in `custom.py` regardless of CI maturity.

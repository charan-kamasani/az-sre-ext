# CI/CD scaffolding status (generated from `azext-aigateway`'s proven pattern)

The two workflows in `.github/workflows/` (`ci.yml`, `release.yml`) are adapted
directly from the real, working `azext-aigateway` CI/CD setup — same structure,
same pinned `Azure/aaz` commit (`eea0104952d4d28e30c8df1679f7b02801e95046`,
the exact commit this extension was generated against this session).

**They reference four helper scripts that do NOT exist yet in this repo** —
aigateway has them, we need to write our own equivalents before these
workflows will actually run green. This is the next concrete work item, not
done yet:

| Script | Purpose | Effort |
|---|---|---|
| `scripts/validate_swagger.py` | Lints the `sreagent.json` spec (schema sanity, no broken `$ref`s) before generating anything | Small — can mostly copy aigateway's version, swap the spec path |
| `scripts/generate_sre_extension.py` | Wraps the two `aaz-dev` commands we ran by hand this session (`command-model generate-from-swagger` + `cli generate-by-swagger-tag`) into one repeatable script CI calls on every PR to catch spec drift | Small — straight codification of the commands we already proved work |
| `scripts/verify_installed_wheel.sh` | Installs the built wheel into a clean `az` and runs a smoke command (e.g. `az sre agent --help`) to prove it actually loads | Small |
| `scripts/validate_release_metadata.py` | Confirms the git tag (`vX.Y.Zb1`) matches the wheel's version metadata before a release is allowed to publish | Small |

None of these are hard — they're all straightforward ports of aigateway's
real, working versions — but they are real work, not auto-generated, and
should be the next task after the `commands.py` wiring.

## What's still manual (not in CI yet)
- The `app` → `sre` command-group rename (currently generated commands live
  under `az app agent ...` because the RP folder is `Microsoft.App`) — needs a
  deliberate decision on whether to rename at generation time or at
  `commands.py` wiring time.
- Client-side validation logic (model-provider quota multipliers, EU Data
  Boundary exclusions) — not in the spec, must be hand-written regardless of
  CI maturity.

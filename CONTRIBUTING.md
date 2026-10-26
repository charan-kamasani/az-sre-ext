# Contributing

This repository is a personal/private project tracking `az sre`, a CLI
extension for the `Microsoft.App/agents` (SRE Agent) control plane.

1. Create focused changes that follow the generated-AAZ-plus-hand-written-
   overlay model (see [docs/source-code.md](docs/source-code.md)): generated
   recipes under `azext_sre/aaz/latest/` are never hand-edited; anything a
   Swagger spec cannot express lives in `azext_sre/custom.py`.
2. Do not commit secrets, credentials, tokens, customer data, or local
   environment files.
3. Before claiming a command works, live-verify it against a real Azure
   agent, not just unit tests — see
   [docs/testing.md](docs/testing.md#live-verification-workflow) for the
   required rebuild/reinstall steps and why skipping them tests stale code.
4. Keep `PLAN.md`'s "Implementation progress" log current as work lands —
   it is the evidence trail for every architecture decision.
5. Update `docs/cli-reference.md` and the other `docs/` guides when the
   command surface or a confirmed payload shape changes.

Install the repository-tracked commit hook once per checkout:

```bash
git config core.hooksPath .githooks
```

The hook regenerates and stages `docs/cli-reference.md` on every commit
attempt. CI runs the same deterministic generator with `--check` and fails
the build if the reference drifts.

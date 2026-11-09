# Testing strategy

## Coverage layers

1. **Unit tests** (`src/sre/azext_sre/tests/latest/test_custom.py`) — fully
   credential-free, cover every hand-written behavior in `custom.py`: RBAC
   role-name mapping, the networking GET-merge-PUT logic, extension
   create/show/list/delete resource-ID and payload shape, the base64/JSON
   extension-value codec, model-provider and data-connector-type
   normalization (including that invalid values raise `CLIError`, not a
   bare `ValueError`), extension-type enum completeness, command
   registration, arg-schema help regressions (`to_cmd_arg()` must not
   crash — see [docs/source-code.md](source-code.md)), and CLI-level
   argument enforcement.
2. **`-h` sweep** — run `-h` on every registered command and check for an
   unhandled traceback (`unexpected error`/`Traceback`) in the output. This
   is the fastest way to catch the exact bug class unit tests can miss: an
   `AAZBaseArg._help` dict silently overwritten with a plain string stays
   invisible until `-h` is actually invoked for that specific command.
3. **Live verification** against a real `Microsoft.App/agents` resource —
   the only way to confirm a payload shape, a server-side validation
   message, or a long-running-operation state transition is actually
   correct. Source-mining the control-plane repo alone has been proven
   unreliable at least once (the original `commonPrompts` shape looked
   confirmed from a DebugApp `.tsx` prop type, but was wrong on the wire).

The reference-generator checks execute copied shell examples offline, with
an `az` stand-in that records arguments instead of calling Azure. Run them
from the repository root with Bash available:

```bash
python -m unittest discover -s scripts/tests -v
python scripts/generate_cli_reference.py --check
```

## Live-verification workflow

**Rebuild and reinstall before every live test.** The installed extension
is a wheel snapshot, not a live symlink to source:

```bash
cd src/sre
python -m build --wheel
az extension remove --name sre
az extension add --source dist/sre-1.0.0b1-py3-none-any.whl -y
```

**For read-only / idempotent checks**, use your long-lived test agent
directly (`show`, `list`, `connection show`, `usage list`, connector/
tool/skill/instructions `show`/`list`).

**For anything destructive or state-changing** (`create`, `delete`,
`start`, `stop`, `identity assign`/`remove`, `network update`, a new
connector or extension type you haven't confirmed yet), create a disposable
throwaway agent, exercise the command, then tear the throwaway agent down
completely:

```bash
RG="<approved-test-resource-group>"
AGENT="sre-lifecycle-test"

az sre agent create --name "$AGENT" -g "$RG" -l eastus2 \
  --default-model "{provider:anthropic,name:automatic}" \
  --system-assigned --no-wait

az sre agent wait --name "$AGENT" -g "$RG" --created --timeout 600

# ... exercise the command under test here ...

az sre agent delete --name "$AGENT" -g "$RG" -y
```

At least one identity (`--system-assigned` or `--user-assigned`) is
required at create time — the server rejects creation without one.

**When confirming an extension payload shape**, a 200 response alone is
not proof — the data plane silently sanitizes/drops unrecognized fields
instead of rejecting them. Always read back what you just created and
compare the relevant user-supplied fields, allowing for documented server
defaults and redacted secrets. Use the noun-specific commands; the old
`az sre extension` group is no longer available:

```bash
az sre instructions create -g "$RG" --agent-name "$AGENT" \
  --name test-prompt --value '{"prompt": "test prompt"}'

az sre instructions show -g "$RG" --agent-name "$AGENT" --name test-prompt
```

For raw-request probing when the CLI's own client-side validator is in the
way, use `az rest` with a file-based JSON body (PowerShell mangles inline
quoting unreliably for this):

```bash
az rest --method put \
  --url "https://management.azure.com/<resource-id>/commonPrompts/default?api-version=2026-01-01" \
  --headers "Content-Type=application/json" \
  --body "@body.json"
```

**Clean up every disposable resource afterward.** `globalSettings` is a
true ARM singleton — it does not support `DELETE` (`405 MethodNotAllowed:
"Settings cannot be deleted. Use PUT with empty properties to reset."`);
reset it to `{}` via `PUT` instead.

## Known environment restrictions (not CLI bugs)

- EntraOAuth MCP connectors are server-side disabled in at least one test
  subscription (`"MCP Entra OAuth is disabled"`). The consent-status
  branch for that case remains unit-tested but not live-verified; treat it
  as a known gap, not a defect.

## Confirmed vs. unconfirmed extension-type payload shapes

See [docs/operations.md](operations.md#runbook-extension-payload-shapes)
for the current confirmed/unconfirmed table and the live-probing technique
that confirmed `commonPrompts` and `globalSettings`.

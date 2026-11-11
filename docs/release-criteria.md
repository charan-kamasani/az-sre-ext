# Release criteria for `az sre`

This document decides whether `az sre` can ship as an **early preview** Azure CLI
extension.

It has two parts:

- **[Part 1: Release rules](#part-1-release-rules)** say what must be true before a
  release ships. The sign-off owners agree to these once.
- **[Part 2: This release](#part-2-this-release)** records what has been tested for the
  release being prepared now. It is updated as testing progresses.

The bar matches an early preview. `az sre` is a CLI extension, not a live service, so a
fix ships as a new version. The goal is confidence that the extension installs, the
main customer journeys work on the supported tenants, and failures are clear and safe.
It is not exhaustive testing of every edge case.

## Status at a glance

**Decision: nearly ready.** Gates 1, 2, 3 and 6 pass. Two pieces of testing and the
license file remain, then the owners sign off.

| # | Gate | Status | Owner | Remaining |
|---|---|---|---|---|
| 1 | [Candidate artifact](#gate-1-candidate-artifact) | ✅ Passed | Charan Kamasani | |
| 2 | [Automated validation](#gate-2-automated-validation) | ✅ Passed | Charan Kamasani | |
| 3 | [Package smoke](#gate-3-package-smoke) | ✅ Passed | Charan Kamasani | |
| 4 | [E2E: SRE Agent labs](#gate-4-e2e-sre-agent-labs) | 🟡 In progress | Patrick Verbrugge | Run the labs on Linux |
| 5 | [Security E2E](#gate-5-security-e2e) | 🟡 In progress | Charan Kamasani | Connectors and secrets, and the remaining identities |
| 6 | [Quickstart samples](#gate-6-quickstart-samples) | ✅ Passed | Charan Kamasani | |
| 7 | [Defect bar](#gate-7-defect-bar) | 🟡 In progress | Patrick Verbrugge | Add the MIT LICENSE file |
| 8 | [Release owner sign-off](#gate-8-release-owner-sign-off) | ⚪ Waiting on gates 4, 5 and 7 | Release owners | |

Key: ✅ passed, 🟡 in progress, ⚪ not started, ❌ failed.

---

# Part 1: Release rules

## The eight gates

A release is **GO** only when every gate passes and the sign-off table is complete.

| # | Gate | What it proves | Minimum evidence |
|---|---|---|---|
| 1 | Candidate artifact | The release wheel builds and installs | Wheel file name, version, SHA-256, commit SHA, clean install |
| 2 | Automated validation | The unit and regression suite passes | CI run on Windows, macOS and Linux |
| 3 | Package smoke | Every documented command loads from the wheel | Command smoke result, azdev style and linter |
| 4 | E2E: SRE Agent labs | Real customer journeys work end to end using only the CLI | Each lab completed on each OS |
| 5 | Security E2E | Identity, RBAC, connectors and secrets behave safely | Principal, role and scope; unauthorized results; output scan; cleanup |
| 6 | Quickstart samples | A new user can follow the published quickstarts | Each quickstart run from a clean install |
| 7 | Defect bar | No ship-blocking bugs remain | Every open bug has an owner and a decision |
| 8 | Release owner sign-off | Owners reviewed the results | Completed sign-off table |

## Gate details

### Gate 1: Candidate artifact

- [x] Build the release wheel with the release workflow (#35).
- [x] Record the file name, version, SHA-256 and commit SHA in
      [Release under review](#release-under-review).
- [x] Install it into a clean Azure CLI environment with no load or registration errors.
- [x] `az sre version` returns the expected release version.

**Pass:** the wheel installs and loads cleanly. Any packaging failure is NO-GO.

### Gate 2: Automated validation

- [x] CI passes on Windows, macOS and Linux: lint, unit tests, regeneration drift check
      and wheel verification (#78).

**Pass:** all required CI checks are green.

### Gate 3: Package smoke

- [x] Every documented command responds to `--help`.
- [x] The installed command list matches `docs/cli-reference.md`.
- [x] No missing packaged modules or files.

**Pass:** every documented command loads. Any command-registration failure is NO-GO.

### Gate 4: E2E: SRE Agent labs

The public SRE Agent labs are the end-to-end tests. They follow real customer journeys
(create an agent, connect data sources, investigate an incident, clean up) rather than
testing commands one by one, and they surface the edge cases customers will hit.

- [ ] Every public SRE Agent lab completes using only `az sre` commands, on Windows,
      macOS and Linux.
- [ ] Each lab is run by more than one person, so different setups and habits are
      covered.
- [ ] Errors along the way are clear and point to the fix.
- [ ] Test resources are deleted at the end of each lab.

**Pass:** every lab completes on every OS, and no lab leaves resources behind.

### Gate 5: Security E2E

Identity and RBAC:

- [ ] Assign an identity to a test agent and verify it exists.
- [ ] Grant a supported role at the intended test scope.
- [ ] Verify the assignment independently with `az role assignment list`.
- [ ] Revoke it and verify only that assignment was removed.
- [ ] Remove the identity and clean up.

Connectors and secrets:

- [ ] Create a test connector; verify it with `show` and `list`.
- [ ] Run `connector list-secret` as an authorized identity, then as an unauthorized one.
- [ ] Review normal, error, `--verbose` and `--debug` output for exposed credentials.
- [ ] Delete the connector and verify cleanup.

Each test identity (see [Test coverage](#test-coverage)) must get its expected result:

| Identity | Expected result |
|---|---|
| Administrator on the test agent | Every command in the scenario succeeds |
| No role on the test agent | Every change and `list-secret` fails with a clear authorization error and no state change |
| Reader-only | Reads succeed; every create, update, delete, grant and revoke fails with a clear authorization error and no state change |
| Guest (B2B) user | Supported commands work, or fail with a clear error; `--assignee` and sign-in lookups resolve the right principal |
| Service principal or managed identity | Commands run without prompts or Graph user lookups; `--grant-access-to-me` fails clearly |

**Pass:** only the intended access changes, unauthorized operations fail safely, and
no credential appears unexpectedly.

### Gate 6: Quickstart samples

- [x] The short quickstart in the README (create an agent, add a connector, connect
      incidents, create a response plan) works from a clean install.
- [x] The full quickstart, which uses every command group, works from a clean install.

**Pass:** both quickstarts run start to finish as written.

### Gate 7: Defect bar

- [ ] Zero P0 defects.
- [ ] Zero unresolved security, authorization, credential-exposure or
      destructive-operation P1 defects.
- [ ] Zero unresolved release-packaging or licensing P1 defects (for example, a missing
      LICENSE file).
- [ ] Every other open bug has an owner and a documented decision.

### Gate 8: Release owner sign-off

- [ ] Every owner in the [sign-off table](#sign-off) has reviewed the results in Part 2
      for the exact candidate and recorded a decision.

## Test coverage

Gates 4 to 6 cover the combinations below. Results are recorded in
[Testing done](#testing-done).

| Item | Required |
|---|---|
| Operating systems | Windows, Linux, macOS |
| Tenants | Corp and BAMI (non-Microsoft). AME and PME: out of scope (see [Decisions](#decisions)). Sovereign clouds: no, unless SRE Agent is available there |
| Signed-in identities | Administrator, no role, Reader-only, guest (B2B) user, service principal or managed identity |
| Agent channels | Stable; Preview where the command supports it |
| Azure CLI | Minimum supported version (`azext.minCliCoreVersion` in `src/sre/azext_sre/azext_metadata.json`, currently 2.75.0) and latest |

## GO / NO-GO

**GO** only if:

- [ ] Every gate passes.
- [ ] No unexpected credential exposure.
- [ ] No leaked test resources or permissions.

**Automatic NO-GO** if any of these happens:

- The release wheel cannot install or load cleanly.
- The core agent create, manage or delete journey fails.
- An identity or RBAC change affects the wrong principal, role, resource or scope.
- An unauthorized operation succeeds.
- A credential is exposed.
- A destructive command affects an unintended resource.
- A failed operation leaves security-sensitive unintended state.

## Sign-off

Signing off means you agree these rules are sufficient and the results in Part 2 meet
them.

| Role | Name | Decision | Date |
|---|---|---|---|
| CLI owner | Charan Kamasani | | |
| SRE Agent engineering | Dalibor | | |
| SRE Agent PM | Deepthi | | |
| Developer tools | Paul Yuknewicz | | |
| Developer tools PM | Matt | | |

---

# Part 2: This release

## Release under review

| Field | Value |
|---|---|
| Version | 1.0.0b1 (early preview) |
| Preview build for testers | [`preview-20261111`](https://github.com/charan-kamasani/az-sre-ext/releases/tag/preview-20261111) |
| Wheel file name | `sre-1.0.0b1-py3-none-any.whl` |
| Wheel SHA-256 | `3513dd89ebdc51c194d0891b4f430a7b592290ef97cc27b5a665ddb99df1dcac` |
| Commit SHA | `8ee3b94` (preview build). The final release is tagged `v1.0.0b1` |
| License | MIT, matching most Azure CLI extensions |

The final wheel is built by the release workflow from the `v1.0.0b1` tag. CI repeats
gates 1 to 3 on it automatically. If the CLI code changes after the preview build, the
affected labs are re-run.

## Decisions

| Question | Options | Decision |
|---|---|---|
| Is AME testing required for this release? | Yes / No | No. Out of scope |
| Is PME testing required for this release? | Yes / No | No. Out of scope |
| Is an internal customer testing period required (named users and a feedback channel, see #27)? | Yes / No | |

AME and PME are out of scope for `az sre`. Changes in \*ME tenants must go through EV2
or ApprovalService, and running the Azure CLI by hand counts as a manual touch, which
isn't allowed there (confirmed by Hamid Henry Safi). `az sre` is for external
customers and for 1P teams in Corp. 1P teams deploying to AME or PME should use EV2;
`srectl extension generate-ev2` already generates the Bicep and ARM templates for that.

## Testing done

| Test | Windows | Linux | macOS | Account / tenant | Result |
|---|---|---|---|---|---|
| Unit tests, azdev style and linter, command smoke (CI) | ✅ | ✅ | ✅ | — | Pass |
| Live, most commands | ✅ | ✅ | ✅ | Corp | Pass |
| Live, most commands | ✅ | ✅ | Not tested | BAMI | Pass |
| Full command script (84 commands) | — | — | ✅ | Corp | Pass; 2 bugs found and tracked |
| All 9 public SRE Agent labs (including Zava AKS/Postgres) | ✅ | 🟡 Patrick | ✅ | Corp | In progress |
| README quickstart and full quickstart, run cold | ✅ | — | ✅ | Corp | Pass |
| Agent access as administrator, reader and writer | ✅ | — | — | Corp | Pass |
| Connectors, secrets and the remaining identities (Gate 5) | 🟡 Charan | — | — | Corp | In progress |
| Copilot runs scenarios using only `--help` | ✅ | — | — | Corp | Pass |
| Real IcM incident → response plan → agent investigates | ✅ | — | ✅ | Corp (SRE e2e agent, IcM team 142788) | Pass |
| Proxima checks run locally (CodeQL, component governance, pytest, DeepReview) | ✅ | — | — | — | Pass |
| Sign-in with a non-Microsoft account | Planned | — | — | AzCode2610 (account from Brandon Waterloo) | Not started |

**Still to do:** labs on Linux (Patrick), Gate 5 security testing (Charan), the MIT
LICENSE file (Patrick), and BAMI on macOS.
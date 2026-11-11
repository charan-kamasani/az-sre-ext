# Release criteria for `az sre`

This document decides whether an `az sre` release can ship to customers.

It has two parts:

- **[Part 1: Release rules](#part-1-release-rules)** say what must be true before any
  release ships. The sign-off owners agree to these once.
- **[Part 2: This release](#part-2-this-release)** records the results for the release
  being prepared now. It is updated as testing progresses.

Every gate runs against the **exact wheel being released**, installed from that file.
The E2E gates run against live Azure.

## Status at a glance

**Decision: not ready to ship yet.** Testing on the release wheel has not started.

Nothing outside the team is stopping us. Every gate runs against the exact wheel being
released, so the gates start once that wheel is built. Next steps:

1. Merge the CI hardening PR (#78), then the install and release scripts PR (#35).
2. Tag the release commit and build the release wheel (gate 1).
3. Run gates 2 to 6 on that wheel.

AME and PME testing is optional until the sign-off owners decide it is required
(see [Decisions needed](#decisions-needed)). If they require it, it needs a SAW.

Every gate below is required to ship.

| # | Gate | Status | Starts after |
|---|---|---|---|
| 1 | [Candidate artifact](#gate-1-candidate-artifact) | ⚪ Not started | #78 and #35 merged, release tagged |
| 2 | [Automated validation](#gate-2-automated-validation) | ⚪ Not started | Gate 1 |
| 3 | [Package smoke](#gate-3-package-smoke) | ⚪ Not started | Gate 1 |
| 4 | [Core E2E](#gate-4-core-e2e) | ⚪ Not started | Gate 1 |
| 5 | [Security E2E](#gate-5-security-e2e) | ⚪ Not started | Gate 1 |
| 6 | [Feature-specific E2E](#gate-6-feature-specific-e2e) | ⚪ Not started | Gate 1 |
| 7 | [Defect bar](#gate-7-defect-bar) | ⚪ Not started | Gates 1 to 6 |
| 8 | [Release owner sign-off](#gate-8-release-owner-sign-off) | ⚪ Not started | Gates 1 to 7 |

Key: ✅ passed, 🟡 in progress or open, ⚪ not started, ❌ failed.

---

# Part 1: Release rules

## The eight gates

A release is **GO** only when every blocking gate passes and the sign-off table is
complete.

| # | Gate | What it proves | Minimum evidence |
|---|---|---|---|
| 1 | Candidate artifact | The exact release wheel builds and installs | Wheel file name, version, SHA-256, commit SHA, clean install log |
| 2 | Automated validation | The unit and regression suite passes | CI run on the release commit |
| 3 | Package smoke | Every documented command loads from the wheel | Command smoke result |
| 4 | Core E2E | The agent lifecycle works against the live service, and failures are safe | Commands, exit codes, resource IDs, before and after state, cleanup |
| 5 | Security E2E | Identity, RBAC, connectors and secrets behave safely | Principal, role and scope; unauthorized results; output scan; cleanup |
| 6 | Feature-specific E2E | Network configuration works | Before and after state, invalid-input error |
| 7 | Defect bar | No ship-blocking bugs remain | Every open bug has an owner and a decision |
| 8 | Release owner sign-off | Owners reviewed the results for the exact candidate | Completed sign-off table |

## Gate details

### Gate 1: Candidate artifact

- [ ] Build the release wheel from the tagged release commit.
- [ ] Record the file name, version, SHA-256 and commit SHA in
      [Release under review](#release-under-review).
- [ ] Install it into a clean Azure CLI environment with no load or registration errors.
- [ ] `az sre version` returns the expected release version.

**Pass:** the wheel installs and loads cleanly. Any packaging failure is NO-GO.

### Gate 2: Automated validation

- [ ] CI passes on the release commit: lint, unit tests, regeneration drift check and
      wheel verification.

**Pass:** all required CI checks are green on that exact commit.

### Gate 3: Package smoke

- [ ] Every documented command responds to `--help`.
- [ ] The installed command list matches `docs/cli-reference.md`.
- [ ] No missing packaged modules or files.

**Pass:** every documented command loads. Any command-registration failure is NO-GO.

### Gate 4: Core E2E

Agent lifecycle, from the installed release wheel:

- [ ] Create a real test agent and wait for provisioning.
- [ ] `show` returns the agent with the correct state, and `list` contains it.
- [ ] Update a supported property and verify the change persisted.
- [ ] Stop and start the agent, verifying state after each.
- [ ] Delete the agent and verify it is gone.

Destructive operations and failures, using representative high-impact commands:

- [ ] Delete, remove and revoke affect only the intended target.
- [ ] An operation on a nonexistent resource fails with a clear error.
- [ ] One representative service or network failure is handled where practical.
- [ ] Expected failures leave no partial state.
- [ ] The test environment is clean after the suite.

**Pass:** the full lifecycle succeeds, failures are clear and safe, and no test
resource is left behind.

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

### Gate 6: Feature-specific E2E

Blocking, because `az sre network show` and `az sre network update` ship in this release.

- [ ] Apply one valid network configuration to a test agent.
- [ ] Retrieve it and verify the configuration persisted.
- [ ] Attempt one invalid configuration and confirm a clear error.
- [ ] Verify the failure did not change the last valid configuration.
- [ ] Clean up.

**Pass:** valid configuration works; invalid configuration fails without breaking the
agent.

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

Gates 3 to 6 run on every combination below. Results are recorded in the
[test results matrix](#test-results).

| Item | Required |
|---|---|
| Operating systems | Windows, Linux, macOS |
| Tenants | Corp and BAMI (non-Microsoft). AME and PME: [decision needed](#decisions-needed). Sovereign clouds: no, unless SRE Agent is available there |
| Signed-in identities | Administrator, no role, Reader-only, guest (B2B) user, service principal or managed identity |
| Agent channels | Stable; Preview where the command supports it |
| Azure CLI | Minimum supported version (`azext.minCliCoreVersion` in `src/sre/azext_sre/azext_metadata.json`, currently 2.75.0) and latest |

AME and PME testing needs a SAW and production-tenant accounts.

## GO / NO-GO

**GO** only if:

- [ ] The exact release wheel was tested, and it is the artifact being released.
- [ ] Every applicable blocking gate passes.
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
- Gate 6 (network configuration) has not passed.
- The tested artifact differs from the released artifact.

## Sign-off

Signing off means you agree these rules are sufficient and the results in Part 2 meet
them.

| Role | Name | Decision | Date |
|---|---|---|---|
| CLI owner | Charan Kamasani | | |
| SRE Agent engineering | Dalibor | | |
| SRE Agent PM | Deepthi | | |
| Developer tools | Paul Yuknewicz | | |

---

# Part 2: This release

## Release under review

| Field | Value |
|---|---|
| Version | |
| Commit SHA | |
| Wheel file name | |
| Wheel SHA-256 | |
| Network commands ship in this release? | Yes (`az sre network show`, `az sre network update`) |
| Evidence folder | |

## Decisions needed

| Question | Options | Decision |
|---|---|---|
| Is AME testing required for this release? | Yes / No | |
| Is PME testing required for this release? | Yes / No | |
| Is an internal customer testing period required (named users and a feedback channel, see #27)? | Yes / No | |

## Test results

Fill in from the exact release wheel: ✅ pass, ❌ fail with issue link, — not
applicable. Package smoke depends only on the OS, so it is recorded once per OS.
Skip the AME and PME rows if they are not required.

| OS | Tenant | Signed in as | Package smoke | Core E2E | Security E2E | Feature-specific E2E |
|---|---|---|---|---|---|---|
| Windows | Corp | User | | | | |
| Linux | Corp | User | | | | |
| macOS | Corp | User | | | | |
| Windows | BAMI | User | — | | | |
| Linux | BAMI | User | — | | | |
| macOS | BAMI | User | — | | | |
| Windows (SAW) | AME | User | — | | | |
| Windows (SAW) | PME | User | — | | | |
| Linux | Corp | Service principal or managed identity | — | | | |

## Testing done so far

Done before the release candidate, from a development wheel or from source. This shows
progress but does **not** count toward the gates, which must be re-run on the exact
release wheel.

| Test | Windows | Linux | macOS | Account / tenant | Installed from | Result |
|---|---|---|---|---|---|---|
| azdev style + azdev linter | ✅ | ✅ (CI) | — | — | Source | Pass |
| Live, most commands | ✅ | ✅ | ✅ | Corp | Wheel | Pass |
| Live, most commands | ✅ | ✅ | Not tested | BAMI | Wheel (to confirm with Patrick) | Pending confirmation |
| All 9 public SRE Agent labs (including Zava AKS/Postgres) | ✅ | Not tested | ✅ | Corp | Wheel | Pass |
| Quickstart run cold | ✅ | — | ✅ | Corp | Wheel | Pass |
| Copilot runs scenarios using only `--help` | ✅ | — | — | Corp | Wheel | Pass |
| Full end-to-end script (84 commands) | — | — | ✅ | Corp | Wheel | 2 bugs found, tracked separately |
| Real IcM incident → response plan → agent investigates | ✅ | — | ✅ | Corp (SRE e2e agent, IcM team 142788) | Wheel | Pass |
| Proxima checks run locally (CodeQL, component governance, pytest, DeepReview) | ✅ | — | — | — | Source | Pass |

**Gaps still to close:** labs on Linux, BAMI on macOS, AME, PME, and the Reader-only,
guest and service principal identities.

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

**Decision: NOT READY.** No gate has been run against a release wheel yet.

| # | Gate | Blocking? | Status |
|---|---|---|---|
| 1 | [Candidate artifact](#gate-1-candidate-artifact) | Yes | Not started |
| 2 | [Automated validation](#gate-2-automated-validation) | Yes | Not started |
| 3 | [Package smoke](#gate-3-package-smoke) | Yes | Not started |
| 4 | [Core E2E](#gate-4-core-e2e) | Yes | Not started |
| 5 | [Security E2E](#gate-5-security-e2e) | Yes | Not started |
| 6 | [Feature-specific E2E](#gate-6-feature-specific-e2e) | Yes | Not started |
| 7 | [Defect bar](#gate-7-defect-bar) | Yes | Not met: #54 is open |
| 8 | [Release owner sign-off](#gate-8-release-owner-sign-off) | Yes | Not started |

Open decisions for the sign-off owners are listed in
[Decisions needed](#decisions-needed).

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
| 7 | Defect bar | No ship-blocking bugs remain | Known issues table with owners and decisions |
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
- [ ] Every other known issue has an owner and a documented decision in
      [Known issues](#known-issues).

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
| SRE Agent engineering | Dalibor (full name to confirm) | | |
| SRE Agent PM | Deepthi (full name to confirm) | | |
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

## Known issues

| Issue | Severity | Blocks GO? | Owner | Decision |
|---|---|---|---|---|
| [#54](https://github.com/charan-kamasani/az-sre-ext/issues/54) Add a LICENSE file and restore package metadata | P1 (release packaging) | Yes | Charan Kamasani | |
| [#32](https://github.com/charan-kamasani/az-sre-ext/issues/32) Align ARM api-versions (generated 2026-01-01 vs hand-written 2026-11-01-preview) | P2 | No | Charan Kamasani | |
| [#21](https://github.com/charan-kamasani/az-sre-ext/issues/21) Code Access: web-login (OAuth) flow gaps for ADO/GitHub and GitLab egress allowlist | P2 | No | Charan Kamasani | |
| [#53](https://github.com/charan-kamasani/az-sre-ext/issues/53) Accessibility review of device flow, help and errors | P2 | No | Charan Kamasani | |
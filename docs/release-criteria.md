# Release criteria for `az sre`

This document defines what must be true before an `az sre` release ships to customers.
A release is **GO** only when every required gate in the summary passes and the sign-off
table is complete.

Every gate runs against the **exact wheel being released**, installed from that file.
The E2E gates run against live Azure.

## Release sign-off summary

| Gate | Minimum evidence | Required | Detailed checks | Status |
|---|---|---|---|---|
| Candidate artifact | Exact release wheel builds and installs | ✅ | [Gate 1](#1-release-artifact-smoke) | |
| Automated validation | Existing unit/regression suite passes | ✅ | CI on the release commit | |
| Package smoke | Documented CLI surface loads from packaged artifact | ✅ | [Gate 1](#1-release-artifact-smoke) | |
| Core E2E | Agent create → show/update → delete against service | ✅ | [Gate 2](#2-core-agent-lifecycle), [Gate 6](#6-destructive-operations-and-failure-behavior) | |
| Security E2E | Identity/RBAC + auth/secret-sensitive path validated | ✅ | [Gate 3](#3-identity-and-rbac), [Gate 4](#4-connector-authentication-and-secret-safety) | |
| Feature-specific E2E | Network/connector/etc. validated if shipping | ✅ | [Gate 4](#4-connector-authentication-and-secret-safety), [Gate 5](#5-network-configuration-blocking-only-if-network-commands-ship) | |
| Defect bar | No known ship-blocking P0/P1 defects | ✅ | [GO / NO-GO](#go--no-go), [Known issues](#known-issues-and-decisions) | |
| Release owner sign-off | Results reviewed against exact candidate | ✅ | [Sign-off](#sign-off) | |

The sections below describe how each gate is checked and what evidence to attach.

## Sign-off

| Role | Name | Decision | Date |
|---|---|---|---|
| CLI owner | Charan Kamasani | | |
| SRE Agent engineering | Dalibor | | |
| SRE Agent PM | Deepthi | | |
| Developer tools | Paul Yuknewicz | | |

Signing off means you agree these criteria are sufficient for this release.

## Release under review

| Field | Value |
|---|---|
| Version | |
| Commit SHA | |
| Wheel file name | |
| Wheel SHA-256 | |
| Network commands ship in this release? | Yes / No |
| Evidence folder | |

## Blocking gates

### 1. Release artifact smoke

- [ ] Install the exact release wheel into a clean Azure CLI environment.
- [ ] The extension loads with no import or registration errors.
- [ ] `az sre version` returns the expected release version.
- [ ] All documented commands load and respond to `--help`, and the installed command
      list matches `docs/cli-reference.md`.
- [ ] No missing packaged modules or files.

**Evidence:** wheel file name and version, commit SHA, clean install log, command smoke
result.
**Pass:** every documented command loads. Any packaging or command-registration failure
is NO-GO.

### 2. Core agent lifecycle

From the installed release wheel:

- [ ] Create a real test agent and wait for provisioning.
- [ ] `show` returns the agent with the correct state.
- [ ] `list` contains it.
- [ ] Update a supported property and verify the change persisted.
- [ ] Stop and start the agent, verifying state after each.
- [ ] Delete the agent and verify it is gone.

**Evidence:** commands run, exit results, resource ID, verified Azure state, cleanup
result.
**Pass:** the full lifecycle succeeds and no test resource is left behind.

### 3. Identity and RBAC

- [ ] Assign an identity to a test agent and verify it exists.
- [ ] Grant a supported role at the intended test scope.
- [ ] Verify the assignment independently with `az role assignment list`.
- [ ] Revoke it and verify only that assignment was removed.
- [ ] Remove the identity and clean up.
- [ ] Run one insufficient-permission case and confirm it fails without changing state.

**Evidence:** principal, role and scope used; before and after state; authorization
failure result; cleanup result.
**Pass:** only the intended access changes; the unauthorized operation fails safely.

### 4. Connector, authentication and secret safety

- [ ] Create a supported test connector; verify with `show` and `list`.
- [ ] Run `connector list-secret` as an authorized identity.
- [ ] Run `connector list-secret` as an unauthorized identity.
- [ ] Review normal, error, `--verbose` and `--debug` output from the scenario for
      exposed credentials.
- [ ] Delete the connector and verify cleanup.

**Evidence:** connector lifecycle result, unauthorized result, output scan result,
cleanup result.
**Pass:** the functional path works, the unauthorized path fails safely, and no
credential appears unexpectedly.

### 5. Network configuration (blocking only if network commands ship)

- [ ] Apply one valid network configuration to a test agent.
- [ ] Retrieve it and verify the configuration persisted.
- [ ] Attempt one invalid configuration and confirm a clear error.
- [ ] Verify the failure did not change the last valid configuration.
- [ ] Clean up.

**Evidence:** before state, applied configuration, verified state, invalid-input error,
after state.
**Pass:** valid configuration works; invalid configuration fails without breaking the
agent.

### 6. Destructive operations and failure behavior

Use representative high-impact commands, not every command.

- [ ] Delete, remove and revoke affect only the intended target.
- [ ] An operation on a nonexistent resource fails with a clear error.
- [ ] An unauthorized change fails without changing service state.
- [ ] One representative service or network failure is handled where practical.
- [ ] Expected failures leave no partial state.
- [ ] The test environment is clean after the suite.

**Evidence:** command, expected error, actual error and exit code, state before and
after, cleanup result.
**Pass:** failures are clear and safe, with no unintended state changes.

## Test environment

| Item | Value |
|---|---|
| Operating systems | Windows, macOS, Linux |
| Tenants | Corp, BAMI (non-Microsoft); AME and PME per the table below |
| Agent channels | Stable; Preview where the command supports it |
| Identities | Administrator on the test agent; no role on the test agent; Reader-only; guest (B2B) user; service principal or managed identity (non-interactive) |
| Azure CLI | Minimum supported version and latest |

### Test matrix

Run the E2E gates from the exact release wheel and record the result in each cell
(✅ pass, ❌ fail with issue link, — not applicable). AME and PME need a SAW and
production-tenant accounts.

| Gate | Windows | Linux | macOS | Corp | BAMI | AME | PME | Non-interactive (SP/MI) |
|---|---|---|---|---|---|---|---|---|
| Package smoke | | | | n/a | n/a | n/a | n/a | n/a |
| Core E2E | | | | | | | | |
| Security E2E | | | | | | | | |
| Feature-specific E2E | | | | | | | | |

### Pre-release testing done so far

Testing done before the release candidate, from a development wheel or from
source. It does not replace the gates above, which must be re-run on the exact
release wheel.

| Test | Windows | Linux | macOS | Account / tenant | Installed from | Result |
|---|---|---|---|---|---|---|
| azdev style + azdev linter | ✅ | ✅ (CI) | — | n/a | Source | Pass |
| Live, most commands | ✅ | ✅ | ✅ | Corp | Wheel | Pass |
| Live, most commands | ✅ | ✅ | Not tested | BAMI | To confirm with Patrick (BAMI) | Pass |
| All 9 public SRE Agent labs (including Zava AKS/Postgres) | ✅ | Not tested | ✅ | Corp | Wheel | Pass |
| Quickstart run cold | ✅ | — | ✅ | Corp | Wheel | Pass |
| Copilot runs scenarios using only `--help` | ✅ | — | — | Corp | Wheel | Pass |
| Full end-to-end script (84 commands) | — | — | ✅ | Corp | Wheel | 2 bugs found, tracked separately |
| Real IcM incident → response plan → agent investigates | ✅ | — | ✅ | Corp (SRE e2e agent, IcM team 142788) | Wheel | Pass |
| Proxima checks run locally (CodeQL, component governance, pytest, DeepReview) | ✅ | — | — | n/a | Source | Pass |

Gaps to close: labs on Linux, BAMI on macOS, AME, PME, and the identities below.

Security E2E must also cover these identities, recording the result for each:

| Identity | Expected result |
|---|---|
| Reader-only | Reads succeed; every create, update, delete, grant and revoke fails with a clear authorization error and no state change |
| Guest (B2B) user | Supported commands work, or fail with a clear error; `--assignee` and sign-in lookups resolve the right principal |
| Service principal or managed identity | Commands run without prompts or Graph user lookups; `--grant-access-to-me` fails clearly |

| Tenant | Required for this release? |
|---|---|
| Corp | Yes |
| BAMI (non-Microsoft) | Yes |
| AME | Decision needed by sign-off owners |
| PME | Decision needed by sign-off owners |
| Sovereign clouds | No, unless SRE Agent is available there |

| Other validation | Required for this release? |
|---|---|
| Internal customer testing (dogfood period with named users and a feedback channel, see #27) | Decision needed by sign-off owners |

## GO / NO-GO

**GO only if all of these are true:**

- [ ] The exact release wheel was tested.
- [ ] The command smoke passes for every documented command.
- [ ] Every applicable blocking gate passes.
- [ ] No unexpected credential exposure.
- [ ] No leaked test resources or permissions.
- [ ] Zero P0 defects.
- [ ] Zero unresolved security, authorization, credential-exposure or
      destructive-operation P1 defects.
- [ ] Every other accepted issue has an owner and a documented decision.

**Automatic NO-GO** if any of these happens:

- The release wheel cannot install or load cleanly.
- The core agent create, manage or delete journey fails.
- An identity or RBAC change affects the wrong principal, role, resource or scope.
- An unauthorized operation succeeds.
- A credential is exposed.
- A destructive command affects an unintended resource.
- A failed operation leaves security-sensitive unintended state.
- Network commands ship but gate 5 has not passed.
- The tested artifact differs from the released artifact.

## Known issues and decisions

| Issue | Severity | Owner | Decision |
|---|---|---|---|
| [#54](https://github.com/charan-kamasani/az-sre-ext/issues/54) Add a LICENSE file and restore package metadata | P1 (release packaging) | Charan Kamasani | |
| [#32](https://github.com/charan-kamasani/az-sre-ext/issues/32) Align ARM api-versions (generated 2026-01-01 vs hand-written 2026-11-01-preview) | P2 | Charan Kamasani | |
| [#21](https://github.com/charan-kamasani/az-sre-ext/issues/21) Code Access: web-login (OAuth) flow gaps for ADO/GitHub and GitLab egress allowlist | P2 | Charan Kamasani | |
| [#53](https://github.com/charan-kamasani/az-sre-ext/issues/53) Accessibility review of device flow, help and errors | P2 | Charan Kamasani | |

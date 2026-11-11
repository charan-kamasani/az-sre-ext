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
| Tenants | Microsoft corporate; one non-Microsoft tenant (BAMI) |
| Agent channels | Stable; Preview where the command supports it |
| Identities | One test identity with Administrator on the test agent; one identity with no role on the test agent |
| Azure CLI | Minimum supported version and latest |

AME and sovereign clouds are out of scope for this release unless a 1P customer
scenario requires them.

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
| | | | |

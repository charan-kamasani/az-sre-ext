# Releasing az sre

A release is a lightweight Git tag named `v<major>.<minor>.<patch>b<n>` (for example
`v1.0.0b2`) on the current tip of `master`. Pushing the tag runs
`.github/workflows/release.yml`. The flow follows the ADC Azure CLI extension release
pattern so the CLI can move to the ADC repository later without changing how it is released.

## Release contract

A release publishes exactly three assets:

- `sre-<version>-py3-none-any.whl`
- `SHA256SUMS`
- `sre-<version>.spdx.json` (SBOM)

The workflow refuses to publish unless all of these hold:

- The tag is lightweight and points at the current `origin/master` commit.
- The tag, `VERSION` in `src/sre/setup.py`, the wheel filename and the wheel metadata
  agree (`scripts/validate_release_metadata.py`).
- Unit tests pass and `docs/cli-reference.md` is current.
- The wheel installs into a clean, pinned Azure CLI, `az extension show` and `az sre version`
  report the release version, every command and group in `docs/cli-reference.md` answers
  `--help`, and the installed command inventory matches that reference exactly
  (`scripts/verify_installed_wheel.py`).
- `scripts/install.sh` installs the built wheel.
- Build-provenance attestations for all assets verify against this workflow.
- No release with the tag exists yet.

Publishing is draft-first: the workflow creates a draft, checks the target commit and asset
count, then publishes. A failed run deletes its draft.

## Cut a release

1. Set `VERSION` in `src/sre/setup.py` and add an entry to `src/sre/HISTORY.rst`.
2. Merge the change to `master` and wait for CI.
3. Tag the exact current `master` commit and push the tag.

   ```bash
   git fetch origin master
   git tag v1.0.0b2 origin/master
   git push origin v1.0.0b2
   ```

4. Watch the `Release` workflow. Both jobs must pass.

## Verify the release

Check the release page lists the three assets, then install from a clean shell:

```bash
gh api -H 'Accept: application/vnd.github.raw+json' repos/charan-kamasani/az-sre-ext/contents/scripts/install.sh | sh -s -- --release-tag v1.0.0b2 --require-attestation
az sre --help
```

Record the workflow run URL and the release URL in the release tracking issue.

## Install options

| Option (`install.sh` / `install.ps1`) | Environment variable | Purpose |
|---|---|---|
| `--release-tag` / `-ReleaseTag` | `SRE_INSTALL_RELEASE_TAG` | Install this tag. |
| `--latest-release` / `-LatestRelease` | | Install the newest release. Default. |
| `--repo` / `-Repo` | `SRE_INSTALL_REPO` | Source repository. Defaults to `charan-kamasani/az-sre-ext`. |
| `--require-attestation` / `-RequireAttestation` | `SRE_INSTALL_REQUIRE_ATTESTATION` | Fail unless attestation verification ran. It always runs for GitHub downloads; this guards against `--base-url`. |
| `--base-url` / `-BaseUrl` | `SRE_INSTALL_BASE_URL` | Download over HTTP from a directory instead of GitHub. Needs a release tag, doesn't need `gh`, skips attestation. For testing. |

Without `--base-url`, both scripts need GitHub CLI 2.68.0 or later (for
`gh attestation verify --source-ref`), signed in (`gh auth login`) with an account that can
see the repository, because the repository is private.

When no tag is given, the scripts install the newest published release whose tag matches
`v<major>.<minor>.<patch>b<n>`; releases with other tags are ignored.

The installer never falls back to another version. If the release lookup, the checksum or
the attestation check fails, it stops.

## Rollback

Never replace assets or move a published tag. If a release is bad, delete the release
entry (the tag stays) or turn it back into a draft, so the installers' latest lookup skips
it, then publish a fixed version with a new tag.

## Moving to ADC

The CLI is planned to move to the ADC repository once it is stable. The layout of
`scripts/` and the release workflow deliberately matches other ADC Azure CLI extensions so
the move is a copy, not a redesign.

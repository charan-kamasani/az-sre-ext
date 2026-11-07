# Releasing az sre

A release is a lightweight Git tag named `v<major>.<minor>.<patch>b<n>` (for example
`v1.0.0b2`) on the current tip of `master`. Pushing the tag runs
`.github/workflows/release.yml`. The flow mirrors the AI Gateway extension so the CLI can
move to the ADC repository later without changing how it is released.

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
- The wheel installs into a clean, pinned Azure CLI and every `az sre` command in
  `docs/cli-reference.md` answers `--help` (`scripts/verify_installed_wheel.sh`).
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
curl -fsSL https://raw.githubusercontent.com/charan-kamasani/az-sre-ext/master/scripts/install.sh | sh -s -- --release-tag v1.0.0b2 --require-attestation
az sre --help
```

Record the workflow run URL and the release URL in the release tracking issue.

## Install options

| Option (`install.sh` / `install.ps1`) | Environment variable | Purpose |
|---|---|---|
| `--release-tag` / `-ReleaseTag` | `SRE_INSTALL_RELEASE_TAG` | Install this tag. |
| `--latest-release` / `-LatestRelease` | | Install the newest release. Default. |
| `--repo` / `-Repo` | `SRE_INSTALL_REPO` | Source repository. Defaults to `charan-kamasani/az-sre-ext`. |
| `--require-attestation` / `-RequireAttestation` | `SRE_INSTALL_REQUIRE_ATTESTATION` | Fail unless attestation verification ran. Needs an authenticated `gh`. |
| `--base-url` / `-BaseUrl` | `SRE_INSTALL_BASE_URL` | Download from a directory instead of GitHub. Skips attestation. For testing. |

The installer never falls back to another version. If the release lookup, the checksum or
the attestation check fails, it stops.

## Rollback

Never replace assets or move a published tag. If a release is bad, mark it as a
pre-release or delete the release entry, then publish a fixed version with a new tag.

## Moving to ADC

The CLI is planned to move to the ADC repository once it is stable. The layout of
`scripts/` and the release workflow deliberately matches AI Gateway's so the move is a
copy, not a redesign.

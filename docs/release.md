# Releasing az sre

A release is a Git tag. Pushing a tag runs `.github/workflows/release.yml`, which tests the
code, builds the wheel, writes `SHA256SUMS`, checks the install script against the built
wheel, and publishes a GitHub release with both files. Tags containing `a` or `b` followed
by a number (for example `v1.0.0b2`) are marked as pre-releases.

## Cut a release

1. Set `VERSION` in `src/sre/setup.py` and add an entry to `src/sre/HISTORY.rst`.
2. Merge the change to `master`.
3. Tag and push. The tag must equal `v` plus the `setup.py` version.

   ```bash
   git tag v1.0.0b2
   git push origin v1.0.0b2
   ```

4. Check the release page for the wheel and `SHA256SUMS`.

## Install a release

The scripts in `scripts/` download the wheel and `SHA256SUMS` from the release, compare the
checksum and run `az extension add`. See [Install](../README.md#install).

| Variable | Purpose |
|---|---|
| `SRE_INSTALL_VERSION` | Release tag to install. Defaults to the newest release. |
| `SRE_INSTALL_REPO` | GitHub repository. Defaults to `charan-kamasani/az-sre-ext`. |
| `SRE_INSTALL_BASE_URL` | Download location override, used to test a locally built wheel. |

# Releasing

The version is set in `packaging/package.yaml`; tags are derived from it, never typed by hand.

1. Bump `version` in `packaging/package.yaml` and run `make manifests-sync`.
2. **Release candidate:** Actions → *Tag RC* → Run workflow on `develop`. It tags the head of `develop` as `vX.Y.Z-rcN` and builds the packages, published as a prerelease. Tick *Tag even if CI has not passed* to override the CI check.
3. **Release:** Actions → *Tag release* → Run workflow on `develop` (the workflow does not exist on `main`, and it fails on any other branch). It squashes the release candidate (the `rc` input, or the latest one) onto `main` as one commit, tags it `vX.Y.Z` and publishes the release candidate's files as the release. Nothing is rebuilt, and the release candidate's packages must have been built successfully.

Only *Tag release* writes to `main`. The same steps run locally with `make tag-rc` and `make release RC=vX.Y.Z-rcN` (a dry run without `PUSH=1`).

*Tag release* pushes with the `RELEASE_TOKEN` secret (a fine-grained PAT or GitHub App token with Contents and Workflows write on this repository), because the release commit carries `.github/workflows` and `GITHUB_TOKEN` cannot push those.

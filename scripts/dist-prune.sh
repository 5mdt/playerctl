#!/usr/bin/env bash
# Run by `meson dist`: keep only what is needed to build, test and document
# playerctl in the release tarball. An allowlist, so new development files
# (CI, containers, tooling) never leak into the tarball by accident.

set -euo pipefail

root=${MESON_DIST_ROOT:?must be run by meson dist}

keep=(
    CONTRIBUTORS.md
    LICENSE.md
    README.md
    data
    doc
    examples
    meson.build
    meson_options.txt
    playerctl
    test
)

is_kept() {
    local entry
    for entry in "${keep[@]}"; do
        [[ $1 == "${entry}" ]] && return 0
    done
    return 1
}

shopt -s dotglob nullglob
for path in "${root}"/*; do
    is_kept "${path##*/}" || rm -rf "${path}"
done

# Only the C unit tests are built from the tarball (-Dtests); the Python
# suite needs the test image and is not part of a source release.
for path in "${root}"/test/*; do
    [[ ${path##*/} == c ]] || rm -rf "${path}"
done

rm -f "${root}/doc/USER_STORIES.md"

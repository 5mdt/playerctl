#!/usr/bin/env bash
# Fail if the release tarball contains anything outside the allowlist that
# scripts/dist-prune.sh enforces, so development files cannot leak into it.

set -euo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 TARBALL" >&2; exit 2; }
tarball=$1
[[ -f ${tarball} ]] || { echo "No ${tarball}, run make dist first" >&2; exit 1; }
prefix=$(basename "${tarball}" .tar.xz)

allowed="^${prefix}/(CONTRIBUTORS\.md|LICENSE\.md|README\.md|meson\.build|meson_options\.txt|(data|doc|examples|playerctl|test/c)(/.*)?)$"
dirs="^${prefix}/(test/?)?$"

unexpected=$(tar -tf "${tarball}" | grep -Ev "${allowed}|${dirs}" || true)
if [[ -n ${unexpected} ]]; then
    echo "Unexpected files in ${tarball}:" >&2
    echo "${unexpected}" >&2
    exit 1
fi
if tar -tf "${tarball}" | grep -q 'doc/USER_STORIES\.md$'; then
    echo "doc/USER_STORIES.md must not be in the tarball" >&2
    exit 1
fi

echo "${tarball}: $(tar -tf "${tarball}" | grep -vc '/$') files, $(du -h "${tarball}" | cut -f1)"

#!/usr/bin/env bash
# Collect the release files in OUTDIR: the source tarball, every package built
# by `make packages` (prefixed with its distro, since .deb names do not say
# which release they were built on), the PKGBUILD with the real checksum, and
# SHA256SUMS. If GPG_PRIVATE_KEY (ASCII-armored) is set, SHA256SUMS is signed.

set -euo pipefail

[[ $# -eq 3 ]] || { echo "usage: $0 DISTDIR PKGROOT OUTDIR" >&2; exit 2; }
distdir=$1
pkgroot=$2
outdir=$3
root=$(realpath "$(dirname "$0")/..")

rm -rf "${outdir}"
mkdir -p "${outdir}"

tarball=$(find "${distdir}" -maxdepth 1 -name 'playerctl-*.tar.xz' | head -n 1)
[[ -n ${tarball} ]] || { echo "no tarball in ${distdir}" >&2; exit 1; }
cp "${tarball}" "${outdir}/"

for dir in "${pkgroot}"/*/; do
    # directory names are <distro>-<arch>
    label=$(basename "${dir}")
    distro=${label%-*}
    for file in "${dir}"*; do
        [[ -f ${file} ]] && cp "${file}" "${outdir}/${distro}_$(basename "${file}")"
    done
done

sum=$(sha256sum "${tarball}" | cut -d' ' -f1)
manifests=$(mktemp -d)
# only the PKGBUILD is used, so the date from git does not matter
SOURCE_DATE_EPOCH=0 "${root}/scripts/render-packaging.py" --out "${manifests}" --sha256 "${sum}"
cp "${manifests}/arch/PKGBUILD" "${outdir}/PKGBUILD"
rm -rf "${manifests}"

(cd "${outdir}" && sha256sum -- * > SHA256SUMS)

if [[ -n ${GPG_PRIVATE_KEY:-} ]]; then
    GNUPGHOME=$(mktemp -d)
    export GNUPGHOME
    trap 'rm -rf "${GNUPGHOME}"' EXIT
    echo "${GPG_PRIVATE_KEY}" | gpg --batch --import
    gpg --batch --yes --armor --detach-sign "${outdir}/SHA256SUMS"
fi

ls -l "${outdir}"

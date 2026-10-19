#!/usr/bin/env bash
# Collect the release files in OUTDIR: the source tarball, every package built
# by `make packages` (prefixed with playerctl-<distro>-<version>-<cpu>, since
# .deb names do not say which release they were built on), the PKGBUILD with
# the real checksum, and SHA256SUMS. If GPG_PRIVATE_KEY (ASCII-armored) is set, SHA256SUMS is signed.

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

sum=$(sha256sum "${tarball}" | cut -d' ' -f1)
manifests=$(mktemp -d)
# only the PKGBUILD and the file names are used, so the date from git does not matter
SOURCE_DATE_EPOCH=0 "${root}/scripts/render-packaging.py" --out "${manifests}" --sha256 "${sum}"
cp "${manifests}/arch/PKGBUILD" "${outdir}/PKGBUILD"

# names.txt has a "<distro> <name>-<version>" line for every distro
declare -A slugs
while read -r distro slug; do
    slugs[${distro}]=${slug}
done < "${manifests}/names.txt"
rm -rf "${manifests}"

for dir in "${pkgroot}"/*/; do
    # directory names are <distro>-<cpu>
    label=$(basename "${dir}")
    distro=${label%-*}
    cpu=${label##*-}
    [[ -n ${slugs[${distro}]:-} ]] || { echo "unknown distro ${distro} in ${dir}" >&2; exit 1; }
    for file in "${dir}"*; do
        [[ -f ${file} ]] && cp "${file}" "${outdir}/playerctl-${slugs[${distro}]}-${cpu}_$(basename "${file}")"
    done
done

(cd "${outdir}" && sha256sum -- * > SHA256SUMS)

if [[ -n ${GPG_PRIVATE_KEY:-} ]]; then
    GNUPGHOME=$(mktemp -d)
    export GNUPGHOME
    trap 'rm -rf "${GNUPGHOME}"' EXIT
    echo "${GPG_PRIVATE_KEY}" | gpg --batch --import
    gpg --batch --yes --armor --detach-sign "${outdir}/SHA256SUMS"
fi

ls -l "${outdir}"

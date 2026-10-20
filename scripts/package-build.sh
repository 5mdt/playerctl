#!/usr/bin/env bash
# Build a distro package from the meson dist tarball with the manifests
# rendered by `make manifests`. Runs as root inside the target distro's
# container, see `make package`.

set -euo pipefail

usage() {
    echo "usage: $0 {rpm|deb|arch} TARBALL OUTDIR MANIFESTDIR" >&2
    exit 2
}

[[ $# -eq 4 ]] || usage
type=$1
tarball=$(realpath "$2")
outdir=$3
manifests=$(realpath "$4")
version=$(basename "${tarball}" .tar.xz)
version=${version#playerctl-}

mkdir -p "${outdir}"
outdir=$(realpath "${outdir}")
work=$(mktemp -d)
trap 'rm -rf "${work}"' EXIT

build_rpm() {
    local spec=${manifests}/rpm/playerctl.spec install
    if command -v dnf > /dev/null; then
        install=(dnf install -y)
    else
        install=(zypper --non-interactive install)
    fi
    "${install[@]}" rpm-build
    local -a deps
    mapfile -t deps < <(rpmspec -q --buildrequires "${spec}")
    "${install[@]}" "${deps[@]}"

    mkdir -p "${work}"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}
    cp "${tarball}" "${work}/SOURCES/playerctl-${version}.tar.xz"
    rpmbuild -bb --define "_topdir ${work}" "${spec}"
    find "${work}/RPMS" -name '*.rpm' ! -name '*-debuginfo-*' ! -name '*-debugsource-*' \
        -exec cp {} "${outdir}" \;
}

build_deb() {
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y --no-install-recommends build-essential devscripts equivs fakeroot

    cp "${tarball}" "${work}/playerctl_${version}.orig.tar.xz"
    tar -C "${work}" -xf "${tarball}"
    local tree=${work}/playerctl-${version}
    cp -r "${manifests}/debian" "${tree}/debian"

    cd "${tree}"
    mk-build-deps --install --remove \
        --tool 'apt-get -y --no-install-recommends' debian/control
    dpkg-buildpackage -us -uc -b
    find "${work}" -maxdepth 1 -name '*.deb' ! -name '*-dbgsym_*' -exec cp {} "${outdir}" \;
}

build_arch() {
    # Landlock, which pacman sandboxes downloads with, is not allowed in
    # containers on CI runners
    pacman -Syu --disable-sandbox --noconfirm --needed base-devel
    id builder > /dev/null 2>&1 || useradd -m builder

    cp "${manifests}/arch/PKGBUILD" "${work}/PKGBUILD"
    cp "${tarball}" "${work}/playerctl-${version}.tar.xz"
    chown -R builder "${work}"

    local -a deps
    mapfile -t deps < <(bash -c 'source "$1"; printf "%s\n" "${depends[@]}" "${makedepends[@]}"' _ "${work}/PKGBUILD")
    pacman -S --disable-sandbox --noconfirm --needed "${deps[@]}"

    su builder -c "cd '${work}' && makepkg --force --noconfirm"
    find "${work}" -maxdepth 1 -name '*.pkg.tar.*' ! -name '*-debug-*' -exec cp {} "${outdir}" \;
}

case ${type} in
    rpm) build_rpm ;;
    deb) build_deb ;;
    arch) build_arch ;;
    *) usage ;;
esac

# Docker runs as real root: hand the results back to the invoking user
if [[ -n ${HOST_UID:-} ]]; then
    chown -R "${HOST_UID}:${HOST_GID:-${HOST_UID}}" "${outdir}"
fi

echo "Built packages:"
ls -l "${outdir}"

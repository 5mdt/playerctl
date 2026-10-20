#!/usr/bin/env bash
# Lint the packages in PKGDIR with the distro's own linter (rpmlint, lintian
# or namcap), inside the distro's container. See `make package-lint`.

set -uo pipefail

[[ $# -eq 1 ]] || { echo "usage: $0 PKGDIR" >&2; exit 2; }
pkgdir=$(realpath "$1")

# shellcheck disable=SC1091
. /etc/os-release
export DEBIAN_FRONTEND=noninteractive

case " ${ID} ${ID_LIKE:-} " in
    *" fedora "*)
        dnf install -y rpmlint || exit 1
        rpmlint "${pkgdir}"/*.rpm
        ;;
    *" suse "* | *" opensuse "*)
        zypper --non-interactive install rpmlint || exit 1
        rpmlint "${pkgdir}"/*.rpm
        ;;
    *" debian "* | *" ubuntu "*)
        apt-get update && apt-get install -y --no-install-recommends lintian || exit 1
        lintian --fail-on error "${pkgdir}"/*.deb
        ;;
    *" arch "*)
        # Landlock is not allowed in containers on CI runners
        pacman -Syu --disable-sandbox --noconfirm namcap || exit 1
        out=$(namcap "${pkgdir}"/*.pkg.tar.*)
        echo "${out}"
        ! grep -q ' E: ' <<< "${out}"
        ;;
    *)
        echo "Unsupported distro: ${ID}" >&2
        exit 2
        ;;
esac

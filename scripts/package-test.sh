#!/usr/bin/env bash
# Install the packages built by scripts/package-build.sh in a fresh container
# of the same distro and check that they work. Starting from a clean image,
# not the build container, means missing runtime dependencies are not masked
# by build dependencies. First installs the distro's own playerctl so the
# upgrade path is covered too. See `make package-test`.

# The check functions are only called indirectly, through check
# shellcheck disable=SC2329
set -uo pipefail

[[ $# -eq 2 ]] || { echo "usage: $0 PKGDIR VERSION" >&2; exit 2; }
pkgdir=$(realpath "$1")
version=$2

# shellcheck disable=SC1091
. /etc/os-release
case " ${ID} ${ID_LIKE:-} " in
    *" fedora "*) pm=dnf ;;
    *" suse "* | *" opensuse "*) pm=zypper ;;
    *" debian "* | *" ubuntu "*) pm=apt ;;
    *" arch "*) pm=pacman ;;
    *)
        echo "Unsupported distro: ${ID}" >&2
        exit 2
        ;;
esac

export DEBIAN_FRONTEND=noninteractive

# install NAME...: from the distro repositories
install() {
    case ${pm} in
        dnf) dnf install -y "$@" ;;
        zypper) zypper --non-interactive install "$@" ;;
        apt) apt-get install -y --no-install-recommends "$@" ;;
        # Landlock, which pacman sandboxes downloads with, is not allowed in
        # containers on CI runners
        pacman) pacman -S --disable-sandbox --noconfirm --needed "$@" ;;
    esac
}

# install_local FILE...: package files, upgrading what is installed
install_local() {
    case ${pm} in
        dnf) dnf install -y --nogpgcheck "$@" ;;
        zypper) zypper --non-interactive --no-gpg-checks install --allow-unsigned-rpm --allow-vendor-change "$@" ;;
        apt) apt-get install -y --no-install-recommends --allow-downgrades "$@" ;;
        pacman) pacman -U --noconfirm --ask 4 "$@" ;;
    esac
}

case ${pm} in
    dnf) tools=(dbus-daemon glib2 pkgconf-pkg-config) ;;
    zypper) tools=(dbus-1-daemon findutils glib2-tools pkgconf-pkg-config) ;;
    apt) tools=(dbus-daemon dbus-bin libglib2.0-bin pkgconf) ;;
    pacman) tools=(dbus glib2 pkgconf) ;;
esac

case ${pm} in
    apt) apt-get update ;;
    pacman) pacman -Syu --disable-sandbox --noconfirm ;;
    zypper) zypper --non-interactive refresh ;;
esac

echo "== installing test tools"
install "${tools[@]}" || exit 1

echo "== installing the distro playerctl (upgrade baseline)"
if install playerctl; then
    echo "distro playerctl: $(playerctl --version)"
else
    echo "no distro playerctl available, skipping the upgrade check"
fi

echo "== installing ${pkgdir}"
case ${pm} in
    dnf | zypper) mapfile -t files < <(find "${pkgdir}" -name '*.rpm') ;;
    apt) mapfile -t files < <(find "${pkgdir}" -name '*.deb') ;;
    pacman) mapfile -t files < <(find "${pkgdir}" -name '*.pkg.tar.*') ;;
esac
[[ ${#files[@]} -gt 0 ]] || { echo "no packages in ${pkgdir}" >&2; exit 1; }
install_local "${files[@]}" || exit 1

failed=0
# check DESCRIPTION COMMAND...
check() {
    local what=$1
    shift
    if "$@" > /dev/null 2>&1; then
        echo "ok   ${what}"
    else
        echo "FAIL ${what}"
        failed=1
    fi
}

has_glob() { compgen -G "$1" > /dev/null; }
no_missing_libs() { ! ldd "$(command -v "$1")" | grep -q 'not found'; }
# Container images often exclude docs, so ask the package manager, not the disk
packaged_man_page() {
    case ${pm} in
        dnf | zypper) rpm -ql playerctl ;;
        apt) dpkg -L playerctl ;;
        pacman) pacman -Qlq playerctl-5mdt ;;
    esac | grep -q 'man1/playerctl\.1'
}
typelib_present() { [[ -n $(find /usr/lib* -name Playerctl-2.0.typelib) ]]; }
version_is() { [[ $("$@") == "v${version}" ]]; }
pc_version_is() { [[ $(pkg-config --modversion playerctl) == "${version}" ]]; }
daemon_owns_name() {
    dbus-run-session -- bash -c '
        playerctld daemon
        for _ in 1 2 3 4 5; do
            sleep 1
            gdbus call --session --dest org.freedesktop.DBus \
                --object-path /org/freedesktop/DBus \
                --method org.freedesktop.DBus.NameHasOwner \
                org.mpris.MediaPlayer2.playerctld | grep -q true && exit 0
        done
        exit 1'
}

echo "== checks (expecting ${version})"
check "playerctl --version is v${version}" version_is playerctl --version
check "playerctld runs" playerctld --help
check "playerctl links all libraries" no_missing_libs playerctl
check "playerctld links all libraries" no_missing_libs playerctld
check "playerctld owns its bus name" daemon_owns_name
check "D-Bus service file" test -f /usr/share/dbus-1/services/org.mpris.MediaPlayer2.playerctld.service
check "man page is packaged" packaged_man_page
check "bash completion" has_glob '/usr/share/bash-completion/completions/playerctl*'
check "zsh completion" test -f /usr/share/zsh/site-functions/_playerctl
check "pkg-config reports ${version}" pc_version_is
check "introspection typelib" typelib_present
check "headers" test -f /usr/include/playerctl/playerctl.h

exit "${failed}"

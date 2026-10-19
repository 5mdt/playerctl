# Installing

## Packages from this fork

Every [release](https://github.com/5mdt/playerctl/releases) has packages for x86_64 and aarch64, built and install-tested in containers of each distribution. They use the same package names as the distributions, so they upgrade the `playerctl` that is already installed.

Release file names start with the distribution they were built for. Download the files for your distribution release and CPU (`x86_64` or `aarch64` in `.rpm` and Arch names, `amd64` or `arm64` in `.deb` names) and install all of them in one command, from the directory you downloaded them to:

<!-- BEGIN distro-table -->

| Distribution        | Install command                                   |
|---------------------|---------------------------------------------------|
| Fedora 43           | `sudo dnf install ./fedora-43_*.rpm`              |
| Fedora 44           | `sudo dnf install ./fedora-44_*.rpm`              |
| openSUSE Tumbleweed | `sudo zypper install ./opensuse-tumbleweed_*.rpm` |
| openSUSE Leap 16.0  | `sudo zypper install ./opensuse-leap_*.rpm`       |
| Debian 12           | `sudo apt install ./debian-12_*.deb`              |
| Debian 13           | `sudo apt install ./debian-13_*.deb`              |
| Ubuntu 22.04        | `sudo apt install ./ubuntu-22.04_*.deb`           |
| Ubuntu 24.04        | `sudo apt install ./ubuntu-24.04_*.deb`           |
| Ubuntu 26.04        | `sudo apt install ./ubuntu-26.04_*.deb`           |
| Arch Linux          | `sudo pacman -U ./arch_*.pkg.tar.zst`             |

<!-- END distro-table -->

Each set holds the `playerctl` command, the shared library, and the development files (`-devel` or `-dev`) with the introspection data. Arch has a single package, `playerctl-5mdt`, which replaces `playerctl`; the release also has the `PKGBUILD` to build it yourself. The release also has `SHA256SUMS` (with `SHA256SUMS.asc`, a signature, when the maintainer's key was available) and the source tarball.

## Other distributions

Other distributions may package Playerctl themselves, but those packages are usually older than this fork. Build from source, see below.

## Guix

`playerctl` is available as a [Guix](https://guix.gnu.org) package which can be installed on any Linux distribution after [installing Guix](https://guix.gnu.org/manual/en/html_node/Installation.html). It is built from the original project, not this fork:

```
guix install playerctl
```

## Compile from source

Using the cli and library requires [GLib](https://developer.gnome.org/glib/) (which is a dependency of almost all of these players as well, so you probably already have it). You can use the library in almost any programming language with the associated [introspection binding library](https://wiki.gnome.org/Projects/GObjectIntrospection/Users).

Additionally, you also need the following build dependencies:

[gobject-introspection](https://wiki.gnome.org/Projects/GObjectIntrospection) for building introspection data (configurable with the `introspection` meson option)

[gtk-doc](https://gitlab.gnome.org/GNOME/gtk-doc) for building documentation (configurable with the `gtk-doc` meson option)

Fedora users also need to install `redhat-rpm-config`

To generate and build the project to contribute to development and install playerctl to `/`:

```
meson setup build
sudo meson install -C build
```

Note that you need `meson` installed. In case your distro only has an older version of meson in its repository you can install the newest version via pip:

```
pip3 install meson
```

Also keep in mind that gtk-doc and gobject-introspection are enabled by default, you can disable them with `-Dintrospection=false` and `-Dgtk-doc=false`.

If you don't want to install playerctl to `/` you can install it elsewhere by exporting `DESTDIR` before running `meson install`, e.g.:

```
export PREFIX="/usr/local"
meson setup --prefix="${PREFIX}" --libdir="${PREFIX}/lib" build
export DESTDIR="$(pwd)/install"
meson install -C build
```

You can use it later on by exporting the following variables:

```
export LD_LIBRARY_PATH="$DESTDIR/${PREFIX}/lib/:$LD_LIBRARY_PATH"
export GI_TYPELIB_PATH="$DESTDIR/${PREFIX}/lib/:$GI_TYPELIB_PATH"
export PATH="$DESTDIR/${PREFIX}/bin:$PATH"
```

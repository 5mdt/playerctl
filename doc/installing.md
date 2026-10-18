# Installing

First, check and see if Playerctl is available from your package manager (if it is not, get someone to host a package for you) and also check the [releases](https://github.com/5mdt/playerctl/releases) page on github.

## Fedora

`playerctl` is available for Fedora 28 or later:

```
sudo dnf install playerctl
```

## Mageia, openSUSE

`playerctl` is available for Mageia and openSUSE via [this COPR repository](https://copr.fedorainfracloud.org/coprs/jflory7/playerctl/). First, install the repository file for your distribution from COPR. Then, install `playerctl` with your package manager of choice.

## Guix

`playerctl` is available as a [Guix](https://guix.gnu.org) package which can be installed on any Linux distribution after [installing Guix](https://guix.gnu.org/manual/en/html_node/Installation.html):

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
meson mesonbuild
sudo ninja -C mesonbuild install
```

Note that you need `meson` installed. In case your distro only has an older version of meson in its repository you can install the newest version via pip:

```
pip3 install meson
```

Also keep in mind that gtk-doc and gobject-introspection are enabled by default, you can disable them with `-Dintrospection=false` and `-Dgtk-doc=false`.

If you don't want to install playerctl to `/` you can install it elsewhere by exporting `DESTDIR` before invoking ninja, e.g.:

```
export PREFIX="/usr/local"
meson --prefix="${PREFIX}" --libdir="${PREFIX}/lib" mesonbuild
export DESTDIR="$(pwd)/install"
ninja -C mesonbuild install
```

You can use it later on by exporting the following variables:

```
export LD_LIBRARY_PATH="$DESTDIR/${PREFIX}/lib/:$LD_LIBRARY_PATH"
export GI_TYPELIB_PATH="$DESTDIR/${PREFIX}/lib/:$GI_TYPELIB_PATH"
export PATH="$DESTDIR/${PREFIX}/bin:$PATH"
```

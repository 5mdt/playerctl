# Builds on Fedora and openSUSE from the meson dist tarball. Subpackage names
# follow each distribution, so these packages upgrade the distro playerctl.
%if 0%{?suse_version}
%global libpkg libplayerctl2
%global typelibpkg typelib-1_0-Playerctl-2_0
%else
%global libpkg playerctl-libs
%endif

Name:           playerctl
Version:        2.5.0
Release:        1%{?dist}
Summary:        Command-line utility and library for controlling media players
License:        LGPL-3.0-or-later
URL:            https://github.com/5mdt/playerctl
Source0:        %{name}-%{version}.tar.xz

BuildRequires:  gcc
BuildRequires:  meson
BuildRequires:  pkgconfig(bash-completion)
BuildRequires:  pkgconfig(gio-unix-2.0)
BuildRequires:  pkgconfig(gobject-2.0)
BuildRequires:  pkgconfig(gobject-introspection-1.0)

%description
Playerctl is a command-line utility and library for controlling media players
that implement the MPRIS D-Bus Interface Specification. It makes it easy to
bind player actions, such as play and pause, to media keys, and to get
metadata about the playing track for status bars and other tools. The
playerctld daemon acts on the currently active media player.

%package -n %{libpkg}
Summary:        Playerctl shared library
%if !0%{?suse_version}
Requires:       %{name}%{?_isa} = %{version}-%{release}
%endif

%description -n %{libpkg}
The Playerctl shared library, used by the playerctl command and by programs
that control MPRIS media players.

%if 0%{?suse_version}
%package -n %{typelibpkg}
Summary:        Introspection data for Playerctl

%description -n %{typelibpkg}
Introspection data for the Playerctl library, used to call it from languages
such as Python and JavaScript.
%endif

%package devel
Summary:        Development files for Playerctl
Requires:       %{libpkg}%{?_isa} = %{version}-%{release}
%if 0%{?suse_version}
Requires:       %{typelibpkg} = %{version}-%{release}
%endif

%description devel
Headers, the pkgconfig file and the introspection source for developing
against the Playerctl library.

%prep
%autosetup

%build
%meson -Dgtk-doc=false -Dbash-completions=true -Dzsh-completions=true -Dtests=false
%meson_build

%install
%meson_install

%ldconfig_scriptlets -n %{libpkg}

%files
%license LICENSE.md
%doc README.md doc/CHANGELOG.md
%{_bindir}/playerctl
%{_bindir}/playerctld
%{_mandir}/man1/playerctl.1*
%{_datadir}/dbus-1/services/org.mpris.MediaPlayer2.playerctld.service
%{_datadir}/bash-completion/completions/playerctl*
%{_datadir}/zsh/site-functions/_playerctl

%files -n %{libpkg}
%license LICENSE.md
%{_libdir}/libplayerctl.so.2*
%if !0%{?suse_version}
%{_libdir}/girepository-1.0/Playerctl-2.0.typelib
%endif

%if 0%{?suse_version}
%files -n %{typelibpkg}
%{_libdir}/girepository-1.0/Playerctl-2.0.typelib
%endif

%files devel
%{_includedir}/playerctl/
%{_libdir}/libplayerctl.so
%{_libdir}/pkgconfig/playerctl.pc
%{_datadir}/gir-1.0/Playerctl-2.0.gir

%changelog
* Mon Oct 19 2026 Vladimir Budylnikov <github@nett00n.org> - 2.5.0-1
- Release 2.5.0 from the 5mdt fork

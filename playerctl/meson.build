playerctl_version_header = configure_file(
  input: 'playerctl-version.h.in',
  output: 'playerctl-version.h',
  configuration: version_conf,
)

# Include the just generated playerctl_version header
configuration_inc = include_directories('..')

playerctl_generated = gnome.gdbus_codegen(
  'playerctl-generated',
  join_paths(meson.project_source_root(), 'data', 'mpris-dbus-interface.xml'),
)

headers = [
  'playerctl.h',
  'playerctl-player.h',
  'playerctl-player-manager.h',
  'playerctl-player-name.h',
  playerctl_version_header,
]

playerctl_sources = [
  'playerctl-player-name.c',
  'playerctl-formatter.c',
  'playerctl-formatter-parser.c',
  'playerctl-formatter-helpers.c',
  'playerctl-player.c',
  'playerctl-player-commands.c',
  'playerctl-common.c',
  'playerctl-player-manager.c',
  playerctl_generated,
]

# Allow including playerctl.h during compilation
c_args = [
  '-DPLAYERCTL_COMPILATION',
  '-DG_LOG_DOMAIN="playerctl"',
]

enums = gnome.mkenums_simple(
  'playerctl-enum-types',
  sources: headers,
  install_header: true,
  install_dir: join_paths(get_option('includedir'), 'playerctl')
)

deps = [
  gobject_dep,
  gio_dep,
]

symbols_file = join_paths(meson.project_source_root(), 'data', 'playerctl.syms')
symbols_flag = '-Wl,--version-script,@0@'.format(symbols_file)

# default_library is shared by default see
# https://mesonbuild.com/Builtin-options.html this enabled the project
# to be either statically or dynamically linked as a subproject
playerctl_lib = library(
  'playerctl',
  playerctl_sources, enums,
  dependencies: deps,
  include_directories: configuration_inc,
  version: playerctl_version,
  install: true,
  link_args : symbols_flag,
  link_depends: symbols_file,
  c_args: c_args,
)

# Required for linking against the shared lib we just built
playerctl_shared_link = declare_dependency(
  link_with: playerctl_lib,
  dependencies: deps,
  include_directories: include_directories('..'),
)

playerctl_executable = executable(
  'playerctl',
  'playerctl-cli.c',
  'playerctl-cli-util.c',
  enums,
  dependencies: playerctl_shared_link,
  include_directories: configuration_inc,
  install: true,
)

# The introspection data playerctld announces is generated from the interface
# XML files in data/, so the code and the specifications cannot drift apart.
# MPRIS: playerctld does not forward methods that pass file descriptors, so
# GetArtworkFd is left out. Its own interface is also announced under the
# deprecated name of earlier versions.
gen_introspection = files('gen-introspection-header.py')
python = find_program('python3')
daemon_introspection = [
  custom_target(
    'playerctl-daemon-introspection',
    input: files('../data/mpris-dbus-interface.xml'),
    output: 'playerctl-daemon-introspection.h',
    command: [
      python, gen_introspection, '@INPUT@', '@OUTPUT@',
      '--variable', 'mpris_introspection_xml',
      '--exclude', 'org.mpris.MediaPlayer2.Player.GetArtworkFd',
    ],
    depend_files: gen_introspection,
  ),
  custom_target(
    'playerctl-daemon-playerctld-introspection',
    input: files('../data/org._5mdt.playerctld.xml'),
    output: 'playerctl-daemon-playerctld-introspection.h',
    command: [
      python, gen_introspection, '@INPUT@', '@OUTPUT@',
      '--variable', 'playerctld_introspection_xml',
      '--deprecated-alias',
      'org._5mdt.playerctld=com.github.altdesktop.playerctld',
    ],
    depend_files: gen_introspection,
  ),
]

playerctld_executable = executable(
  'playerctld',
  'playerctl-daemon.c',
  'playerctl-daemon-player.c',
  'playerctl-daemon-context.c',
  'playerctl-daemon-bus.c',
  enums, daemon_introspection,
  dependencies: deps,
  include_directories: configuration_inc,
  install: true,
  c_args: c_args,
)

install_headers(
  headers,
  install_dir: join_paths(get_option('includedir'), 'playerctl'),
)

if get_option('introspection')
  # The below isn't strictly required, since meson checks for gobject-introspection anyway when
  # we call gnome.generate_gir. However, doing it this way we have a little nicer error reporting
  # in case the user enabled instropection but doesn't have gobject-introspection installed.
  introspection_dep = dependency('gobject-introspection-1.0', required: false)
  if not introspection_dep.found()
      error('You need to have gobject-introspection installed to generate Gir data. Disable it with `-Dintrospection=false` if you don\'t want to build it')
  endif

  gnome.generate_gir(
    playerctl_lib,
    sources: [
      enums,
      'playerctl-player-name.c',
      'playerctl-player-name.h',
      'playerctl-player-manager.c',
      'playerctl-player-manager.h',
      'playerctl-player.c',
      'playerctl-player-commands.c',
      'playerctl-player.h',
    ],
    extra_args : [ '-DPLAYERCTL_COMPILATION' ],
    nsversion: playerctl_major_version + '.0',
    namespace: 'Playerctl',
    includes: ['GObject-2.0'],
    install: true,
  )
endif

pkgconfig.generate(
  libraries: playerctl_lib,
  subdirs: 'playerctl',
  version: meson.project_version(),
  name: 'Playerctl',
  filebase: 'playerctl',
  description: 'A C library for MPRIS players',
  requires: ['gobject-2.0'],
  requires_private: 'gio-2.0',
)

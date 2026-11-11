# GLib g_test unit tests for internals that the CLI cannot reach (static
# formatter functions, pctl_* helpers hidden by the lib's version script).
# The implementation files are compiled straight into each test instead of
# linking libplayerctl. Nothing here is installed.
src = meson.project_source_root() / 'playerctl'

common_sources = [
  src / 'playerctl-common.c',
  src / 'playerctl-player-name.c',
]

c_test_includes = include_directories('../..')

# enums[1] is the generated enum-types header: listed so it exists before compiling.
formatter_sources = [
  src / 'playerctl-formatter.c',
  src / 'playerctl-formatter-parser.c',
  src / 'playerctl-formatter-helpers.c',
]

# Extra dependencies per test (default: none beyond deps).
daemon_sources = [
  src / 'playerctl-daemon-player.c',
  src / 'playerctl-daemon-context.c',
  src / 'playerctl-daemon-bus.c',
]

player_lib_sources = [playerctl_generated, enums[0]]
foreach f : [
  'playerctl-formatter.c',
  'playerctl-formatter-parser.c',
  'playerctl-formatter-helpers.c',
  'playerctl-player.c',
  'playerctl-player-commands.c',
  'playerctl-player-manager.c',
] + ['playerctl-common.c', 'playerctl-player-name.c']
  player_lib_sources += src / f
endforeach

# name: [implementation sources, extra dependencies]
c_tests = {
  'test_formatter': [common_sources + formatter_sources, []],
  'test_formatter_adversarial': [common_sources + formatter_sources, []],
  'test_common': [common_sources, []],
  'test_player_name': [[src / 'playerctl-player-name.c'], []],
  # player_compare_func needs the PlayerctlPlayer type from the shared library.
  'test_cli_util': [
    common_sources + [src / 'playerctl-cli-util.c'],
    [playerctl_shared_link],
  ],
  'test_daemon_player': [common_sources + [src / 'playerctl-daemon-player.c'], []],
  'test_daemon_context': [common_sources + daemon_sources, []],
  # Whole library compiled in: reaches static and hidden player internals.
  'test_player_internal': [player_lib_sources, []],
}

foreach name, spec : c_tests
  exe = executable(
    name,
    [name + '.c', spec[0], enums[1], playerctl_version_header, daemon_introspection],
    dependencies: deps + spec[1],
    include_directories: [c_test_includes, include_directories('../../playerctl')],
    c_args: c_args,
    install: false,
  )
  test(name, exe, args: ['--tap'], protocol: 'tap', suite: 'c', timeout: 60)
endforeach

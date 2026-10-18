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
c_tests = {
  'test_formatter': common_sources,
  'test_common': common_sources,
  'test_player_name': [src / 'playerctl-player-name.c'],
}

foreach name, impl : c_tests
  exe = executable(
    name,
    [name + '.c', impl, enums[1], playerctl_version_header],
    dependencies: deps,
    include_directories: c_test_includes,
    c_args: c_args,
    install: false,
  )
  test(name, exe, suite: 'c', timeout: 60)
endforeach

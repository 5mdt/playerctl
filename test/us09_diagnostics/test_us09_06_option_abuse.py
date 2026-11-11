"""US-9.6: As a scripter, I want any abuse of the option syntax (repeated or
conflicting flags, missing values, `--`, combined short flags, `-f` with
control commands, oversized formats, `-v`/`-h` combinations) to end in a
documented exit code (0 or 1) and a clean message: never a signal, a hang or
a GLib CRITICAL/WARNING."""

import pytest

from ..helpers.cli_fuzz import (
    CONTROL_COMMANDS,
    assert_sane,
    prepared,
    q,
    run,
    snapshot,
)

OPTIONS_WITH_VALUE = [
    '-p',
    '--player',
    '-i',
    '--ignore-player',
    '-f',
    '--format',
]

ABUSE = [
    '-p a -p b status',
    '-a -p a status',
    '-a -i a status',
    '-i a -i b status',
    '-p a -i a status',
    '--player= status',
    '--player=a --player=b status',
    "-p '' status",
    "-p '' -p ' , ' status",
    "-p ',,,' status",
    '-p a,b,c -a status',
    '-a -a -a status',
    '-s -s status',
    '-sa status',
    '-as status',
    '-sl',
    '-ls',
    '-as -p a status',
    'status --',
    '-- status',
    '-- -- status',
    'status status',
    'status extra args here',
    'play extra',
    '-p a status -p b',
    'status -s',
    '--list-all=1',
    '--no-messages=1 status',
    '--all-players=false status',
    '-s -p nosuch status',
    '-a -p nosuch play',
]


@pytest.mark.parametrize('cmd', ABUSE)
async def test_option_abuse_keeps_exit_contract(cmd, playerctl, mpris_factory):
    await prepared(mpris_factory, 'a', 'b', 'c')

    result = await run(playerctl, cmd)

    assert_sane(result, cmd)


@pytest.mark.parametrize('option', OPTIONS_WITH_VALUE)
async def test_missing_value_is_reported(option, playerctl, mpris_factory):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, option)

    assert result.returncode == 1
    assert not result.stdout
    assert f'Missing argument for {option}' in result.stderr
    assert_sane(result)


@pytest.mark.parametrize('option', ['-p', '--player', '-i', '-f'])
async def test_missing_value_after_other_options(
    option, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, f'-s status {option}')

    assert result.returncode == 1
    assert 'Missing argument' in result.stderr


@pytest.mark.parametrize(
    'option',
    [
        '--bogus',
        '--bogus=1',
        '-x',
        '-z',
        '-=',
        '--=',
        '--p',
        '--pl',
        '--player-name',
        '--PLAYER',
        '-P',
        '---',
        '---player',
        '-ñ',
        '--é',
        '-p-',
    ],
)
async def test_unknown_options_fail_cleanly(option, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'a')
    before = snapshot(mpris)

    result = await run(playerctl, f'{option} a play')

    assert_sane(result, option)
    assert result.returncode == 1 or option in ('-p-', '--=')
    assert snapshot(mpris) == before


@pytest.mark.parametrize('option', ['-p', '--player=x', '-aF', '-', '--'])
async def test_degenerate_option_without_command(
    option, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, option)

    assert_sane(result, option)


@pytest.mark.parametrize(
    'command',
    CONTROL_COMMANDS
    + ('position 1', 'volume 1', 'open x', 'loop None', 'shuffle On'),
)
@pytest.mark.parametrize('option', ['-f', '--format'])
async def test_format_rejected_by_commands_that_print_nothing(
    command, option, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'a')
    before = snapshot(mpris)

    result = await run(playerctl, f"-p a {option} '{{{{status}}}}' {command}")

    assert result.returncode == 1
    assert 'format strings are not supported on command' in result.stderr
    assert not result.stdout
    assert snapshot(mpris) == before


@pytest.mark.parametrize(
    'command',
    CONTROL_COMMANDS
    + ('position 1', 'volume 1', 'open x', 'loop None', 'shuffle On'),
)
async def test_follow_rejected_by_commands_that_print_nothing(
    command, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'a')
    before = snapshot(mpris)

    result = await run(playerctl, f'-p a -F {command}')

    assert result.returncode == 1
    assert 'follow is not supported on command' in result.stderr
    assert not result.stdout
    assert snapshot(mpris) == before


@pytest.mark.parametrize('length', [1026, 1027])
async def test_format_at_the_limit_is_accepted(
    length, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, f"-p a -f {q('x' * length)} status")

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'x' * length


@pytest.mark.parametrize('length', [1028, 1029, 4096, 100_000])
async def test_format_over_the_limit_is_rejected(
    length, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, f"-p a -f {q('x' * length)} status")

    assert result.returncode == 1
    assert 'maximum format string length is 1027' in result.stderr
    assert not result.stdout
    assert_sane(result)


@pytest.mark.parametrize('length', [1027, 1028, 5000])
async def test_oversized_format_with_other_commands(
    length, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'a')

    for command in (
        'metadata',
        'status',
        'loop',
        'shuffle',
        'volume',
        'position',
    ):
        result = await run(
            playerctl,
            f"-p a -f {q('{{' + 'x' * (length - 4) + '}}')} {command}",
        )
        assert_sane(result, command)


@pytest.mark.parametrize(
    'fmt',
    [
        '{{',
        '}}',
        '{{}}',
        '{{ }}',
        '{{ status',
        'status }}',
        '{{ status }',
        '{ { status } }',
        '{{{{ status }}}}',
        '{{ "unterminated }}',
        "{{ 'x }}",
        '{{ 1/0 }}',
        '{{ nosuch(1) }}',
        '{{ lc() }}',
        '{{ unknownvar }}',
        '%',
        '%s%n%x',
        '\\x00',
        '{{ -- }}',
        '{{ ((((((1)))))) }}',
        '',
        ' ',
        '\n',
    ],
)
@pytest.mark.parametrize('command', ['status', 'metadata'])
async def test_hostile_format_strings(fmt, command, playerctl, mpris_factory):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, f'-p a -f {q(fmt)} {command}')

    assert_sane(result, fmt)
    if result.returncode == 1:
        assert result.stderr
        assert not result.stdout


@pytest.mark.parametrize(
    'cmd',
    [
        '-v',
        '--version',
        '-v -h',
        '-h -v',
        '--version --help',
        '-v status',
        '-h status',
        '-v extra',
        '-l -v',
        '-v -l',
        '-v -p a',
        '-s -v',
        '-a -v',
        '-v --bogus',
        '-h --bogus',
        '-v -f x',
    ],
)
async def test_version_and_help_combinations(cmd, playerctl, mpris_factory):
    await prepared(mpris_factory, 'a')

    result = await run(playerctl, cmd)

    assert_sane(result, cmd)
    if '--bogus' not in cmd:
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith(('v2.', 'Usage:'))
        assert not result.stderr


@pytest.mark.parametrize(
    'cmd',
    [
        '-l extra',
        "-l ''",
        '-l -- --',
        '-l -f x',
        '-l -F',
        '-l -a -a',
        '-l -p',
        '-l -s -s',
        '-l --bogus',
    ],
)
async def test_list_all_with_bad_arguments(cmd, playerctl, mpris_factory):
    await prepared(mpris_factory, 'a', 'b')

    result = await run(playerctl, cmd)

    assert_sane(result, cmd)
    if result.returncode == 0:
        assert result.stdout.splitlines() == ['a', 'b']


async def test_double_dash_ends_options(playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'a')

    result = await run(playerctl, '-p a -- play')
    option_after = await run(playerctl, '-p a -- -p')

    assert result.returncode == 0, result.stderr
    assert mpris.play_called
    assert option_after.returncode == 1
    assert 'Command not recognized: -p' in option_after.stderr


@pytest.mark.parametrize(
    'command',
    [
        '-',
        '--',
        '---',
        '-p',
        'pla',
        'PLAY',
        'Play',
        'play ',
        ' play',
        'play\t',
        'é',
        '$(id)',
        '%s',
    ],
)
async def test_unrecognised_commands(command, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'a')
    before = snapshot(mpris)

    result = await run(playerctl, f'-p a -- {q(command)}')

    assert_sane(result, command)
    assert result.returncode == 1
    assert snapshot(mpris) == before

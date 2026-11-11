"""US-9.7: As a scripter, I want every command, given any hostile argument,
to exit with 0 or 1, print valid UTF-8, log no GLib CRITICAL/WARNING and
never leave the player in a state the command did not intend."""

import pytest

from ..helpers.cli_fuzz import (
    ALL_COMMANDS,
    CONTROL_COMMANDS,
    HOSTILE_NUMBERS,
    assert_sane,
    prepared,
    q,
    run,
    run_raw,
    snapshot,
)

HOSTILE_PATHS = {
    'relative': 'relative/path.mp3',
    'dotdot': '../../etc/passwd',
    'space-uri': 'file:///x y',
    'bad-escape': 'file:///x%zz',
    'bad-scheme': '://',
    'colon': 'a:b',
    'long-path': '/' + 'a' * 100_000,
    'many-segments': '/a' * 40_000,
    'deep-dots': '/..' * 30_000,
    'root': '/',
    'double-root': '//',
    'tilde': '~',
    'dev-null': '/dev/null',
    'nonexistent': '/nonexistent/../x',
    'long-uri': 'http://' + 'h' * 100_000,
    'unicode-path': '/é/漢字/🎵.mp3',
}

# Values for which a command that takes none must still ignore the argument.
BARE_SAFE = [v for v in HOSTILE_NUMBERS.values() if not v.startswith('-')]


@pytest.mark.parametrize('name', sorted(HOSTILE_NUMBERS))
@pytest.mark.parametrize('command', ALL_COMMANDS)
async def test_command_with_hostile_argument(
    command, name, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'victim')
    before = snapshot(mpris)

    result = await run(
        playerctl, f'-p victim {command} -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert_sane(result, f'{command} {name}')
    if result.returncode == 1:
        assert result.stderr, 'failure without a message'
        assert snapshot(mpris) == before


@pytest.mark.parametrize('command', ALL_COMMANDS)
@pytest.mark.parametrize(
    'value', BARE_SAFE[:12], ids=lambda v: v[:12] or 'empty'
)
async def test_command_with_hostile_argument_without_double_dash(
    command, value, playerctl, mpris_factory
):
    await prepared(mpris_factory, 'victim')

    result = await run(playerctl, f'-p victim {command} {q(value)}')

    assert_sane(result, f'{command} {value[:20]}')


@pytest.mark.parametrize('command', CONTROL_COMMANDS)
@pytest.mark.parametrize(
    'name', ['empty', 'huge', 'nan', 'dashdash', 'shell-subst', 'unicode']
)
async def test_control_commands_ignore_arguments(
    command, name, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'victim')

    result = await run(
        playerctl, f'-p victim {command} -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert result.returncode == 0, result.stderr
    assert not result.stdout
    called = {
        'play': mpris.play_called,
        'pause': mpris.pause_called,
        'play-pause': mpris.play_pause_called,
        'stop': mpris.stop_called,
        'next': mpris.next_called,
        'previous': mpris.previous_called,
    }
    assert called.pop(command)
    assert not any(called.values())


@pytest.mark.parametrize('name', sorted(HOSTILE_PATHS))
async def test_open_hostile_uri(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'victim')

    result = await run(playerctl, f'-p victim open {q(HOSTILE_PATHS[name])}')

    assert_sane(result, name)
    assert not result.stdout
    if result.returncode == 0:
        assert mpris.open_uri_called_with is not None
        mpris.open_uri_called_with.encode()
    else:
        assert mpris.open_uri_called_with is None


@pytest.mark.parametrize(
    'uri',
    ['http://x/y', 'file:///x y', 'file:///x%zz', 'a:b', 'relative', '%', ' '],
)
async def test_open_passes_non_files_through_verbatim(
    uri, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'victim')

    result = await run(playerctl, f'-p victim open {q(uri)}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == uri


@pytest.mark.parametrize('path', ['/dev/null', '/', '/tmp'])
async def test_open_converts_existing_paths_to_file_uris(
    path, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'victim')

    result = await run(playerctl, f'-p victim open {path}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == f'file://{path}'


@pytest.mark.parametrize('command', ALL_COMMANDS)
@pytest.mark.parametrize('raw', [b'\xff', b'a\xffb', b'\xf4\x90\x80\x80'])
async def test_invalid_utf8_argument(command, raw, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'victim')
    before = snapshot(mpris)

    rc, out, err = await run_raw(playerctl, '-p', 'victim', command, raw)

    out.decode()
    err.decode()
    assert rc in (0, 1)
    assert b'CRITICAL' not in err and b'WARNING' not in err
    if rc == 1:
        assert snapshot(mpris) == before


@pytest.mark.parametrize('command', ALL_COMMANDS)
async def test_no_player_exits_cleanly(command, playerctl):
    result = await run(playerctl, f'{command} -- x')

    assert_sane(result, command)
    assert result.returncode == 1
    assert 'No players found' in result.stderr


@pytest.mark.parametrize('command', ALL_COMMANDS)
async def test_all_players_hostile_argument_is_consistent(
    command, playerctl, mpris_factory
):
    players = await prepared(mpris_factory, 'one', 'two')
    before = [snapshot(p) for p in players]

    result = await run(playerctl, f'-a {command} -- {q("5+-" + chr(0x1F3B5))}')

    assert_sane(result, command)
    if result.returncode == 1:
        assert [snapshot(p) for p in players] == before

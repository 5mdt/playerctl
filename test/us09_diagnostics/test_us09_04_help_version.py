"""US-9.4: As a user, I want `--help`/`--version` (and help when no command is
given)."""

import re

import pytest


async def test_help(playerctl):
    result = await playerctl.run('--help')

    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert not result.stderr


@pytest.mark.parametrize('flag', ['--version', '-v'])
async def test_version(flag, playerctl):
    result = await playerctl.run(flag)

    assert result.returncode == 0, result.stderr
    # `v` followed by the version number, nothing else
    assert re.fullmatch(r'v\d+\.\d+\.\d+\S*', result.stdout), result.stdout
    assert not result.stderr


@pytest.mark.parametrize('flag', ['--help', '-h'])
async def test_help_lists_options_and_commands(flag, playerctl):
    result = await playerctl.run(flag)

    assert result.returncode == 0, result.stderr
    for text in ('--player', '--all-players', '--follow', '--format'):
        assert text in result.stdout
    for command in ('play-pause', 'position', 'metadata', 'shuffle'):
        assert command in result.stdout


async def test_no_command_prints_help(playerctl):
    result = await playerctl.run('')

    assert result.returncode == 1
    assert 'Usage:' in result.stdout
    assert '--no-messages' in result.stdout
    assert not result.stderr


async def test_unknown_command(playerctl):
    result = await playerctl.run('frobnicate')

    assert result.returncode == 1
    assert not result.stdout
    assert 'Command not recognized: frobnicate' in result.stderr


@pytest.mark.parametrize('flag', ['-f', '--format'])
async def test_short_and_long_format_flag(flag, playerctl, mpris_factory):
    await mpris_factory('flags')

    result = await playerctl.run(f"{flag} '{{{{status}}}}!' status")

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing!'


@pytest.mark.parametrize('flag', ['-F', '--follow'])
async def test_short_and_long_follow_flag(flag, playerctl, mpris_factory):
    [mpris] = await mpris_factory('flags')

    proc = await playerctl.start(f'{flag} status')

    assert await proc.queue.get() == 'Playing'
    await mpris.emit_properties(playback_status='Paused')
    assert await proc.queue.get() == 'Paused'

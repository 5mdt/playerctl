"""US-1.5: As a scripter, I want a D-Bus error from the player to be reported
as "Could not execute command: ..." with exit code 1."""

import pytest

from ..helpers.mpris import was_called

COMMANDS = [
    'play',
    'pause',
    'play-pause',
    'stop',
    'next',
    'previous',
    'open https://example.com/a.mp3',
    'position 5',
    'position 5+',
    'position 5-',
    'volume 0.5',
    'loop Track',
    'shuffle on',
]


@pytest.mark.parametrize('command', COMMANDS)
async def test_player_error_reported(command, playerctl, mpris_factory):
    [mpris] = await mpris_factory('failing')
    await mpris.set_artist_title('artist', 'title')
    mpris.error = 'the player is broken'

    result = await playerctl.run(f'-p failing {command}')

    assert result.returncode == 1
    assert not result.stdout
    assert 'Could not execute command' in result.stderr
    assert 'the player is broken' in result.stderr


@pytest.mark.parametrize('command', ['play', 'next', 'stop'])
async def test_error_not_hidden_by_no_messages(
    command, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('failing')
    mpris.error = 'the player is broken'

    result = await playerctl.run(f'-s -p failing {command}')

    assert result.returncode == 1
    assert 'the player is broken' in result.stderr
    assert not was_called(mpris, command)

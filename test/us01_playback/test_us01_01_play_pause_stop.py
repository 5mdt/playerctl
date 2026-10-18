"""US-1.1: As a user, I want `play`, `pause`, `play-pause` and `stop` so I can
control playback from a hotkey."""

import pytest

from ..helpers.mpris import was_called


@pytest.mark.parametrize('command', ['play', 'pause', 'play-pause', 'stop'])
async def test_command_reaches_player(command, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')

    result = await playerctl.run(f'-p commands {command}')

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, command), f'{command} was not called'

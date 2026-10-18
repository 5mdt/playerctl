"""US-1.2: As a user, I want `next` and `previous` to change track."""

import pytest

from ..helpers.mpris import was_called


@pytest.mark.parametrize('command', ['next', 'previous'])
async def test_command_reaches_player(command, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')

    result = await playerctl.run(f'-p commands {command}')

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, command), f'{command} was not called'

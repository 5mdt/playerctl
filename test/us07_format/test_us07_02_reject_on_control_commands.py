"""US-7.2: As a user, I want `-f` rejected on commands that change state."""

import pytest

CONTROL_COMMANDS = [
    'play',
    'pause',
    'play-pause',
    'stop',
    'next',
    'previous',
    'open file:///x.ogg',
    'position 10',
    'position 5+',
    'volume 0.5',
    'volume 0.1+',
    'loop Track',
    'shuffle On',
]


@pytest.mark.parametrize('command', CONTROL_COMMANDS)
async def test_format_rejected_on_control_commands(
    command, playerctl, format_player
):
    cmd = await playerctl.run(f"--format '{{{{title}}}}' {command}")
    assert cmd.returncode == 1, cmd.stderr
    assert 'format strings are not supported on command' in cmd.stderr
    assert cmd.stdout == ''

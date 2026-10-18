"""US-8.7: As a user, I want `-F` rejected on control commands."""

import asyncio

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
async def test_follow_rejected_on_control_commands(
    command, playerctl, mpris_factory
):
    await mpris_factory('test1')
    proc = await playerctl.start(f'--follow {command}')
    try:
        await asyncio.wait_for(proc.proc.wait(), 2)
    except asyncio.TimeoutError:
        pytest.fail(f'`--follow {command}` was accepted and kept running')
    stderr = (await proc.proc.stderr.read()).decode()
    assert proc.proc.returncode == 1, stderr
    assert 'follow is not supported on command' in stderr
    assert proc.queue.empty()

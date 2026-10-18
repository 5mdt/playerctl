"""US-1.6: As a scripter, I want a command to fail cleanly with exit code 1
when the player vanishes mid-command, and to wait for a slow player."""

import asyncio

import pytest

from ..helpers.mpris import PLAYER_INTERFACE, gated, was_called

# command -> D-Bus member the player is made to sit on
COMMANDS = {
    'play': ('Play', None),
    'pause': ('Pause', None),
    'play-pause': ('PlayPause', None),
    'stop': ('Stop', None),
    'next': ('Next', None),
    'previous': ('Previous', None),
    'open https://example.com/a.mp3': ('OpenUri', None),
    'position 5': ('SetPosition', None),
    'position 5+': ('Seek', None),
    'volume 0.5': ('Set', 'Volume'),
    'loop Track': ('Set', 'LoopStatus'),
    'shuffle on': ('Set', 'Shuffle'),
}


def _hold(member, prop):
    def configure(gate):
        if prop is None:
            gate.hold(member)
        else:
            gate.hold(
                member, 'org.freedesktop.DBus.Properties', PLAYER_INTERFACE
            )

    return configure


@pytest.mark.parametrize(
    ('command', 'member', 'prop'),
    [(c, *m) for c, m in COMMANDS.items()],
    ids=COMMANDS.keys(),
)
async def test_player_vanishing_during_command(
    command, member, prop, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('van', prepare=gated(_hold(member, prop)))
    await mpris.set_artist_title('artist', 'title')
    task = asyncio.ensure_future(playerctl.run(f'-p van {command}'))

    await mpris.gate.wait_held()
    await mpris.disconnect()
    result = await asyncio.wait_for(task, 4)

    assert result.returncode == 1, result.stderr
    assert not result.stdout
    assert 'Could not execute command' in result.stderr


@pytest.mark.parametrize('command', ['play', 'next', 'stop'])
async def test_slow_player_still_gets_the_command(
    command, playerctl, mpris_factory
):
    member = COMMANDS[command][0]
    [mpris] = await mpris_factory('slow', prepare=gated(_hold(member, None)))
    task = asyncio.ensure_future(playerctl.run(f'-p slow {command}'))

    await mpris.gate.wait_held()
    await asyncio.sleep(0.3)
    assert not task.done()
    mpris.gate.release()
    result = await asyncio.wait_for(task, 4)

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, command)


async def test_player_vanishing_while_connecting(playerctl, mpris_factory):
    [mpris] = await mpris_factory(
        'van', prepare=gated(lambda g: g.hold_get_all(PLAYER_INTERFACE))
    )
    task = asyncio.ensure_future(playerctl.run('-p van status'))

    await mpris.gate.wait_held()
    await mpris.disconnect()
    result = await asyncio.wait_for(task, 4)

    # whatever the outcome, it is a clean failure and not a hang or a crash
    assert result.returncode == 1, result.stderr
    assert not result.stdout
    assert result.stderr

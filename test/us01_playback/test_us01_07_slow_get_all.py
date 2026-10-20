"""US-1.7: As a scripter, I want a simple command such as play-pause to reach
a player at once even when the player is slow to answer Properties.GetAll
(issue #10, spotifyd takes seconds, or 25s, to reply)."""

import asyncio

import pytest
from dbus_next import Variant

from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    gated,
    was_called,
)

ONE_SHOT = ['play', 'pause', 'play-pause', 'stop', 'next', 'previous']

# command -> the Can* property (mock attribute) that gates it
GATES = [
    ('play', 'can_play'),
    ('pause', 'can_pause'),
    ('play-pause', 'can_play'),
    ('stop', 'can_play'),
    ('next', 'can_go_next'),
    ('previous', 'can_go_previous'),
]

# a player that never answers GetAll: today that is the 25s GDBus timeout
HUNG = gated(lambda gate: gate.hold_get_all(PLAYER_INTERFACE))


def _wrong_type(gate):
    gate.hold_get_all(PLAYER_INTERFACE)

    def rewrite(reply):
        reply.body[0] = Variant('s', 'yes')
        return reply

    gate.rewrite('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE, rewrite)


def _get_fails(gate):
    gate.hold_get_all(PLAYER_INTERFACE)
    gate.fail('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE)


@pytest.mark.parametrize('command', ONE_SHOT)
async def test_command_does_not_wait_for_get_all(
    command, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('slow', prepare=HUNG)

    result = await asyncio.wait_for(playerctl.run(f'-p slow {command}'), 2)

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, command)


async def test_open_does_not_wait_for_get_all(playerctl, mpris_factory):
    [mpris] = await mpris_factory('slow', prepare=HUNG)

    result = await asyncio.wait_for(
        playerctl.run('-p slow open https://example.com/a.mp3'), 2
    )

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == 'https://example.com/a.mp3'


@pytest.mark.parametrize(('command', 'gate'), GATES)
async def test_cannot_is_still_respected(
    command, gate, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('slow', prepare=HUNG)
    await mpris.emit_properties(**{gate: False})

    result = await asyncio.wait_for(playerctl.run(f'-p slow {command}'), 2)

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert not was_called(mpris, command)


@pytest.mark.parametrize(
    'prepare',
    [gated(_get_fails), gated(_wrong_type)],
    ids=['get_fails', 'get_wrong_type'],
)
async def test_unreadable_capability_skips_the_player(
    prepare, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('slow', prepare=prepare)

    result = await asyncio.wait_for(playerctl.run('-p slow play'), 2)

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert not was_called(mpris, 'play')


async def test_falls_back_to_a_capable_player(playerctl, mpris_factory):
    [slow] = await mpris_factory('slow', prepare=HUNG)
    [fast] = await mpris_factory('fast')
    await slow.emit_properties(can_go_next=False)

    result = await asyncio.wait_for(playerctl.run('-p slow,fast next'), 2)

    assert result.returncode == 0, result.stderr
    assert fast.next_called
    assert not slow.next_called


async def test_status_waits_for_slow_get_all(playerctl, mpris_factory):
    [mpris] = await mpris_factory('slow', prepare=HUNG)
    task = asyncio.ensure_future(playerctl.run('-p slow status'))

    await mpris.gate.wait_held()
    await asyncio.sleep(0.3)
    assert not task.done()
    mpris.gate.release()
    result = await asyncio.wait_for(task, 4)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'Playing'


async def test_fast_player_is_unaffected(playerctl, mpris_factory):
    [mpris] = await mpris_factory('fast')

    result = await asyncio.wait_for(playerctl.run('-p fast play-pause'), 2)

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, 'play-pause')

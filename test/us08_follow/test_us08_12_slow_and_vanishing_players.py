"""US-8.12: As a bar author, I want follow mode to cope with players that
answer slowly or vanish while they are being connected or queried."""

import asyncio

from ..helpers.follow import expect_no_line, follow_cmd, lines_until, next_line
from ..helpers.mpris import PLAYER_INTERFACE, gated


def _hold_player_properties(gate):
    gate.hold_get_all(PLAYER_INTERFACE)


async def test_slow_new_player_is_shown_once_it_answers(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist1 - title'

    # test2 does not answer its property request for a while
    [mpris2] = await mpris_factory(
        'test2', prepare=gated(_hold_player_properties)
    )
    await mpris2.gate.wait_held()
    await expect_no_line(proc, wait=0.3)
    assert proc.running()

    mpris2.gate.release()
    await mpris2.set_artist_title('artist2', 'title')
    await lines_until(proc, 'test2: artist2 - title')


async def test_new_player_vanishing_while_connecting(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist1 - title'

    [mpris2] = await mpris_factory(
        'test2', prepare=gated(_hold_player_properties)
    )
    await mpris2.gate.wait_held()
    await mpris2.disconnect()

    # the other player is still there and follow mode carries on
    await asyncio.sleep(0.5)
    assert proc.running(), await proc.proc.stderr.read()
    await mpris1.set_artist_title('artist1', 'other')
    await lines_until(proc, 'test1: artist1 - other')


async def test_player_vanishing_while_connecting_at_start(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory(
        'test1', prepare=gated(_hold_player_properties)
    )
    proc = await playerctl.start(follow_cmd())
    await mpris1.gate.wait_held()
    await mpris1.disconnect()

    # nothing left to follow, but follow mode still waits for players
    await asyncio.sleep(0.5)
    assert proc.running(), await proc.proc.stderr.read()
    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title')
    await lines_until(proc, 'test2: artist2 - title')

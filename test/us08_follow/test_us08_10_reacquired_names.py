"""US-8.10: As a bar author, I want follow mode to cope with a player name
that is released and re-acquired quickly, replaced by another owner, or served
on both buses."""

from dbus_next import NameFlag

from ..helpers.follow import expect_no_line, follow_cmd, lines_until, next_line


async def test_name_released_and_taken_again_at_once(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist - title'

    # no wait for follow mode to notice the first owner leaving
    await mpris1.disconnect()
    [mpris1b] = await mpris_factory('test1')
    await mpris1b.set_artist_title('artist', 'back')

    await lines_until(proc, 'test1: artist - back')
    await mpris1b.set_artist_title('artist', 'again')
    assert await next_line(proc) == 'test1: artist - again'
    assert proc.running()


async def test_name_taken_over_by_a_new_owner(playerctl, mpris_factory):
    [mpris1] = await mpris_factory(
        'test1', name_flags=NameFlag.ALLOW_REPLACEMENT
    )
    await mpris1.set_artist_title('old', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: old - title'

    # the bus hands the name over without it ever being unowned
    [mpris1b] = await mpris_factory(
        'test1', name_flags=NameFlag.REPLACE_EXISTING
    )
    await mpris1b.set_artist_title('new', 'title')

    await lines_until(proc, 'test1: new - title')
    await mpris1b.set_artist_title('newer', 'title')
    assert await next_line(proc) == 'test1: newer - title'
    assert proc.running()


async def test_same_name_on_session_and_system_bus(playerctl, mpris_factory):
    [session] = await mpris_factory('test1')
    await session.set_artist_title('session', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: session - title'

    # a player with the same name on the system bus is a different player
    [system] = await mpris_factory('test1', system=True)
    await system.set_artist_title('system', 'title')
    await lines_until(proc, 'test1: system - title')

    await session.set_artist_title('session2', 'title')
    assert await next_line(proc) == 'test1: session2 - title'


async def test_already_managed_name_does_not_add_a_second_player(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist - title'

    # a second connection queues for the name that follow mode already manages
    [queued] = await mpris_factory('test1', queued=True)
    await queued.set_artist_title('other', 'title')
    await expect_no_line(proc)

    await mpris1.set_artist_title('artist', 'title2')
    assert await next_line(proc) == 'test1: artist - title2'


async def test_system_bus_twin_vanishing_keeps_session_player(
    playerctl, mpris_factory
):
    [session] = await mpris_factory('test1')
    await session.set_artist_title('session', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: session - title'
    [system] = await mpris_factory('test1', system=True)
    await system.set_artist_title('system', 'title')
    await lines_until(proc, 'test1: system - title')
    await session.set_artist_title('session2', 'title')
    assert await next_line(proc) == 'test1: session2 - title'

    # the system player leaves: the session player is the one left to follow
    # (FAILS: the manager removes the session player by name, ignoring the bus)
    await system.disconnect()
    await expect_no_line(proc)  # nothing changed for the session player
    await session.set_artist_title('session3', 'title')
    assert await next_line(proc) == 'test1: session3 - title'

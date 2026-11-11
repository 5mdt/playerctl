"""US-10.26: As a user, I want playerctld to keep serving every client when
the active player is slow, blocked or dies in the middle of a forwarded call:
the caller gets an answer or an error, and nobody else is held up."""

import asyncio

import pytest
from dbus_next import MessageType

from ..helpers.daemon import (
    player_names,
    wait_for_player_names,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    OPTIONAL_NOISE,
    PLAYER_INTERFACE,
    PREFIX,
    PlayerCollector,
    assert_healthy,
    close_bus,
    new_bus,
    raw_call,
    shift_names,
)
from ..helpers.mpris import PROPERTIES_INTERFACE, gated

ERROR = MessageType.ERROR
RETURN = MessageType.METHOD_RETURN


async def gated_player(mpris_factory, daemon_bus, name, configure):
    [mpris] = await mpris_factory(name, prepare=gated(configure))
    await mpris.set_artist_title('artist', name)
    deadline = asyncio.get_running_loop().time() + 2
    while PREFIX + name not in await player_names(daemon_bus):
        assert asyncio.get_running_loop().time() < deadline
        await asyncio.sleep(0.02)
    return mpris


async def test_blocked_active_player_does_not_block_other_clients(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    mpris = await gated_player(
        mpris_factory, daemon_bus, 'slow', lambda g: g.hold('Play')
    )
    other = await new_bus(bus_address)
    stuck = asyncio.ensure_future(
        raw_call(other, PLAYER_INTERFACE, 'Play', timeout=4)
    )
    await mpris.gate.wait_held(1)

    # the daemon answers everyone else while the first call hangs
    assert await player_names(daemon_bus) == [PREFIX + 'slow']
    reply = await raw_call(daemon_bus, PLAYER_INTERFACE, 'Pause')
    assert reply.message_type == RETURN
    assert not stuck.done()

    mpris.gate.release()
    assert (await stuck).message_type == RETURN
    assert mpris.play_called
    assert_healthy(playerctld)
    await close_bus(other)


async def test_many_blocked_calls_are_all_answered_after_the_release(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    mpris = await gated_player(
        mpris_factory, daemon_bus, 'slow', lambda g: g.hold('Next')
    )
    buses = [await new_bus(bus_address) for _ in range(15)]
    calls = [
        asyncio.ensure_future(raw_call(b, PLAYER_INTERFACE, 'Next', timeout=4))
        for b in buses
    ]
    await mpris.gate.wait_held(15)

    assert not any(c.done() for c in calls)
    mpris.gate.release()
    replies = await asyncio.gather(*calls)

    assert [r.message_type for r in replies] == [RETURN] * 15
    assert_healthy(playerctld)
    for bus in buses:
        await close_bus(bus)


async def test_shift_while_a_call_is_blocked_still_forwards_new_calls_to_the_new_player(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'calm')
    slow = await gated_player(
        mpris_factory, daemon_bus, 'slow', lambda g: g.hold('Play')
    )
    await wait_for_player_names(daemon_bus, [PREFIX + 'slow', PREFIX + 'calm'])
    other = await new_bus(bus_address)
    stuck = asyncio.ensure_future(
        raw_call(other, PLAYER_INTERFACE, 'Play', timeout=4)
    )
    await slow.gate.wait_held(1)

    reply = await shift_names(daemon_bus)
    assert reply.body == [PREFIX + 'calm']
    reply = await raw_call(daemon_bus, PLAYER_INTERFACE, 'Pause')

    assert reply.message_type == RETURN
    assert calm.pause_called and not slow.pause_called
    slow.gate.release()
    assert (await stuck).message_type == RETURN
    assert slow.play_called and not calm.play_called
    assert_healthy(playerctld)
    await close_bus(other)


async def test_player_dying_during_a_forwarded_call_gives_the_caller_an_error(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    mpris = await gated_player(
        mpris_factory, daemon_bus, 'doomed', lambda g: g.hold('Play')
    )
    other = await new_bus(bus_address)
    call = asyncio.ensure_future(
        raw_call(other, PLAYER_INTERFACE, 'Play', timeout=3)
    )
    await mpris.gate.wait_held(1)

    await mpris.disconnect()
    reply = await call

    assert reply.message_type == ERROR
    assert reply.error_name.startswith('org.freedesktop.DBus.Error.')
    await wait_for_player_names(daemon_bus, [])
    assert_healthy(playerctld)
    await close_bus(other)


async def test_calls_after_the_active_player_died_get_noactiveplayer(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('doomed')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'doomed'])
    await mpris.disconnect()
    await wait_for_player_names(daemon_bus, [])

    for member in ('Play', 'Pause', 'Next'):
        reply = await raw_call(daemon_bus, PLAYER_INTERFACE, member)
        assert reply.message_type == ERROR
        assert reply.error_name.endswith('NoActivePlayer')
    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, 'GetAll', 's', [PLAYER_INTERFACE]
    )
    assert reply.message_type == ERROR
    assert_healthy(playerctld)


async def test_forwarded_error_text_is_kept(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('grumpy')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'grumpy'])
    mpris.error = 'I refuse'

    reply = await raw_call(daemon_bus, PLAYER_INTERFACE, 'Play')

    assert reply.message_type == ERROR
    assert reply.error_name == 'org.example.Error'
    assert reply.body == ['I refuse']


async def test_unanswering_player_during_start_up_scan_only_delays_the_start(
    bus_address, mpris_factory
):
    from ..helpers.daemon import start_playerctld

    # a player that never answers GetAll before the daemon starts: the
    # sync scan waits for its 25 s call timeout, so give it an error instead
    # (a player answering with an error is dropped at once)
    [bad] = await mpris_factory(
        'bad', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist', 'title')

    proc = await start_playerctld(bus_address)
    bus = await new_bus(bus_address)
    await wait_for_players(bus, [PREFIX + 'good'])

    assert proc.returncode is None, proc.log
    await close_bus(bus)


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D7: player_update_position_sync() makes a blocking D-Bus call '
    '(25 s timeout) from the daemon main loop when a player becomes active; '
    'one player that does not answer Get(Position) stalls playerctld for '
    'every client',
)
async def test_shift_to_a_player_that_never_answers_does_not_stall_the_daemon(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    hang = await gated_player(
        mpris_factory,
        daemon_bus,
        'hang',
        lambda g: g.hold('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE),
    )
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'calm')
    await wait_for_player_names(daemon_bus, [PREFIX + 'calm', PREFIX + 'hang'])
    other = await new_bus(bus_address)
    shift = asyncio.ensure_future(shift_names(other))
    await hang.gate.wait_held(1)

    # while the daemon waits for `hang`, an unrelated client asks for the names
    names = await raw_call(
        daemon_bus,
        PROPERTIES_INTERFACE,
        'Get',
        'ss',
        ['org._5mdt.playerctld', 'PlayerNames'],
        timeout=1.5,
    )

    assert names.message_type == RETURN
    shift.cancel()


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D7: the active player quitting makes the next one active '
    'through a blocking Get(Position) on the main loop; a hung next player '
    'stalls the daemon',
)
async def test_active_player_quitting_in_front_of_a_hung_one_does_not_stall(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    hang = await gated_player(
        mpris_factory,
        daemon_bus,
        'hang',
        lambda g: g.hold('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE),
    )
    [front] = await mpris_factory('front')
    await front.set_artist_title('artist', 'front')
    await wait_for_player_names(
        daemon_bus, [PREFIX + 'front', PREFIX + 'hang']
    )

    await front.disconnect()
    await hang.gate.wait_held(1)
    names = await raw_call(
        daemon_bus,
        PROPERTIES_INTERFACE,
        'Get',
        'ss',
        ['org._5mdt.playerctld', 'PlayerNames'],
        timeout=1.5,
    )

    assert names.message_type == RETURN


async def test_blocked_player_that_is_released_in_time_is_activated_normally(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    slow = await gated_player(
        mpris_factory,
        daemon_bus,
        'slow',
        lambda g: g.hold('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE),
    )
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'calm')
    await wait_for_player_names(daemon_bus, [PREFIX + 'calm', PREFIX + 'slow'])
    collector = await PlayerCollector.start(bus_address)
    other = await new_bus(bus_address)
    shift = asyncio.ensure_future(shift_names(other))
    await slow.gate.wait_held(1)

    slow.gate.release()
    reply = await shift

    assert reply.body == [PREFIX + 'slow']
    await collector.wait_quiet()
    assert collector.pairing_errors() == []
    assert await player_names(daemon_bus) == [PREFIX + 'slow', PREFIX + 'calm']
    assert_healthy(playerctld, allow=OPTIONAL_NOISE)
    await close_bus(other)
    await collector.close()

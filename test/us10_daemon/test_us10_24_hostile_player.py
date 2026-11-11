"""US-10.24: As a user, I want one misbehaving player (flooding signals,
sending malformed ones, vanishing in the middle of things) to never take
playerctld down or corrupt what it knows about the other players."""

import asyncio

import pytest
from dbus_next import MessageType, Variant

from ..helpers.sanitizer import skip_rss_check_under_asan
from ..helpers.daemon import (
    player_names,
    settle,
    wait_for_player_names,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    PLAYER_INTERFACE,
    PREFIX,
    PlayerCollector,
    RawPlayer,
    assert_healthy,
    problems,
    raw_call,
    vm_rss_kb,
)
from ..helpers.mpris import PROPERTIES_INTERFACE, gated

PROPERTIES = PROPERTIES_INTERFACE


async def alive(playerctld, daemon_bus, expected):
    await wait_for_players(daemon_bus, expected)
    assert_healthy(playerctld)


BAD_KINDS = {'no-body', 'string-only', 'int-body', 'swapped'}
MALFORMED = {
    'no-body': ('', []),
    'string-only': ('s', [PLAYER_INTERFACE]),
    'missing-invalidated': ('sa{sv}', [PLAYER_INTERFACE, {}]),
    'extra-argument': (
        'sa{sv}asx',
        [PLAYER_INTERFACE, {'Volume': Variant('d', 1.0)}, [], 5],
    ),
    'swapped': ('a{sv}s', [{'Volume': Variant('d', 1.0)}, PLAYER_INTERFACE]),
    'int-body': ('x', [7]),
    'empty-interface': ('sa{sv}as', ['', {}, []]),
    'nested-variant-key': (
        'sa{sv}as',
        [PLAYER_INTERFACE, {'': Variant('s', '')}, ['']],
    ),
}


BUG_D3 = pytest.mark.xfail(
    strict=True,
    reason='BUG-D3: a PropertiesChanged whose body is not (sa{sv}as) makes '
    'player_apply_properties_changed() read missing children: GLib-CRITICAL',
)


@pytest.mark.parametrize(
    'kind',
    [
        pytest.param(k, marks=BUG_D3) if k in BAD_KINDS else k
        for k in sorted(MALFORMED)
    ],
)
async def test_malformed_properties_changed_is_survived_without_criticals(
    bus_address, playerctld, daemon_bus, mpris_factory, kind
):
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist', 'title')
    evil = await RawPlayer.create(bus_address, 'evil')
    await wait_for_players(daemon_bus, [PREFIX + 'good', PREFIX + 'evil'])
    signature, body = MALFORMED[kind]

    await evil.emit(PROPERTIES, 'PropertiesChanged', signature, body)
    # the daemon is still responsive
    await good.set_artist_title('artist2', 'title2')
    await wait_for_player_names(daemon_bus, [PREFIX + 'good', PREFIX + 'evil'])
    await settle()

    assert playerctld.returncode is None, playerctld.log
    assert not [line for line in problems(playerctld) if 'CRITICAL' in line], (
        playerctld.log
    )
    await evil.disconnect()


@pytest.mark.parametrize(
    'signature, body',
    [('s', ['text']), ('', []), ('x', [1]), ('a{sv}', [{}])],
)
async def test_odd_seeked_signals_do_not_crash(
    bus_address, playerctld, daemon_bus, mpris_factory, signature, body
):
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'good'])
    evil = await RawPlayer.create(bus_address, 'evil')
    await wait_for_players(daemon_bus, [PREFIX + 'good', PREFIX + 'evil'])

    await evil.emit(PLAYER_INTERFACE, 'Seeked', signature, body)
    await good.set_artist_title('artist2', 'title2')

    assert await wait_for_player_names(
        daemon_bus, [PREFIX + 'good', PREFIX + 'evil']
    )
    assert playerctld.returncode is None, playerctld.log
    await evil.disconnect()


async def test_signal_flood_from_an_inactive_player(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    evil = await RawPlayer.create(bus_address, 'evil')
    await wait_for_players(daemon_bus, [PREFIX + 'evil'])
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'title')
    await wait_for_player_names(daemon_bus, [PREFIX + 'calm', PREFIX + 'evil'])
    collector = await PlayerCollector.start(bus_address)

    await evil.flood(300)
    await collector.wait_quiet()

    # the flood made the evil player active exactly once, not 300 times
    assert await player_names(daemon_bus) == [
        PREFIX + 'evil',
        PREFIX + 'calm',
    ]
    assert collector.end_names().count(PREFIX + 'evil') == 1
    assert collector.pairing_errors() == []
    assert_healthy(playerctld)
    await evil.disconnect()
    await collector.close()


async def test_flood_does_not_starve_other_clients(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    evil = await RawPlayer.create(bus_address, 'evil')
    await wait_for_players(daemon_bus, [PREFIX + 'evil'])

    await evil.flood(500)
    await evil.flood(
        500,
        lambda i: {
            'Metadata': Variant('a{sv}', {'xesam:title': Variant('s', str(i))})
        },
    )

    # a client call still gets through while the daemon digests the flood
    reply = await raw_call(
        daemon_bus,
        PROPERTIES,
        'Get',
        'ss',
        [PLAYER_INTERFACE, 'Volume'],
        timeout=3,
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert_healthy(playerctld)
    await evil.disconnect()


async def test_player_that_registers_floods_and_vanishes_repeatedly(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'calm'])
    collector = await PlayerCollector.start(bus_address)

    for _ in range(25):
        evil = await RawPlayer.create(bus_address, 'evil')
        await evil.flood(20)
        await evil.disconnect()

    await wait_for_players(daemon_bus, [PREFIX + 'calm'])
    await collector.wait_quiet()
    assert collector.pairing_errors() == []
    assert (await player_names(daemon_bus)) == [PREFIX + 'calm']
    assert_healthy(playerctld, allow=_RACE)
    await collector.close()


_RACE = (
    'could not update player position',
    'could not get properties',
    'could not get org.mpris',
)


async def test_player_vanishing_right_after_registering(
    bus_address, playerctld, daemon_bus
):
    for _ in range(30):
        evil = await RawPlayer.create(bus_address, 'blink')
        await evil.disconnect()

    await wait_for_player_names(daemon_bus, [])
    assert playerctld.returncode is None, playerctld.log


async def test_properties_changed_from_a_stranger_is_ignored(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    # a client that does not own a player name cannot make itself active
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist', 'title')
    [other] = await mpris_factory('other')
    await other.set_artist_title('artist', 'title')
    await wait_for_player_names(
        daemon_bus, [PREFIX + 'other', PREFIX + 'good']
    )
    stranger = await RawPlayer.create(
        bus_address, 'org.example.NotAPlayer', full=True
    )

    stranger.player.emit_properties_changed({'Volume': 0.5})
    await stranger.player.ping()
    await good.ping()

    assert await player_names(daemon_bus) == [
        PREFIX + 'other',
        PREFIX + 'good',
    ]
    assert_healthy(playerctld)
    await stranger.disconnect()


async def test_player_second_connection_cannot_speak_for_the_player(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [good] = await mpris_factory('good')
    [other] = await mpris_factory('other')
    await good.set_artist_title('artist', 'title')
    await other.set_artist_title('artist', 'title')
    await wait_for_player_names(
        daemon_bus, [PREFIX + 'other', PREFIX + 'good']
    )
    # `good` has a helper connection that does not own the name
    helper = await RawPlayer.create(
        bus_address, 'org.example.Helper', full=True
    )

    helper.player.emit_properties_changed({'PlaybackStatus': 'Paused'})
    await helper.player.ping()

    assert (await player_names(daemon_bus))[0] == PREFIX + 'other'
    await helper.disconnect()


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D4: a GetAll reply without body makes the daemon read a '
    'missing child (GLib-CRITICAL); player_fetch_properties_sync() and the '
    'async callback do not check the reply type',
)
async def test_get_all_reply_with_an_empty_body_logs_no_critical(
    bus_address, playerctld, daemon_bus
):
    def hollow(gate):
        def strip(reply):
            reply.signature = ''
            reply.body = []
            return reply

        gate.rewrite('GetAll', PROPERTIES, PLAYER_INTERFACE, strip)

    from ..helpers.mpris import setup_mpris

    [mpris] = await setup_mpris(
        'hollow', bus_address=bus_address, prepare=gated(hollow)
    )
    await mpris.ping()
    await asyncio.sleep(0.2)

    assert playerctld.returncode is None, playerctld.log
    assert not [x for x in problems(playerctld) if "CRITICAL" in x], (
        playerctld.log
    )
    assert await player_names(daemon_bus) == []
    await mpris.disconnect()


async def test_get_all_reply_of_the_wrong_type_leaves_the_player_unlisted(
    bus_address, playerctld, daemon_bus
):
    def wrong(gate):
        def strip(reply):
            reply.signature = 's'
            reply.body = ['not a dict']
            return reply

        gate.rewrite('GetAll', PROPERTIES, PLAYER_INTERFACE, strip)

    from ..helpers.mpris import setup_mpris

    [mpris] = await setup_mpris(
        'wrong', bus_address=bus_address, prepare=gated(wrong)
    )
    await mpris.ping()
    await asyncio.sleep(0.2)

    assert playerctld.returncode is None, playerctld.log
    assert await player_names(daemon_bus) == []
    await mpris.disconnect()


async def test_startup_scan_with_a_hostile_get_all_reply(bus_address):
    from ..helpers.daemon import start_playerctld
    from ..helpers.mpris import setup_mpris

    def wrong(gate):
        def strip(reply):
            reply.signature = 's'
            reply.body = ['not a dict']
            return reply

        gate.rewrite('GetAll', PROPERTIES, PLAYER_INTERFACE, strip)

    [mpris] = await setup_mpris(
        'wrong', bus_address=bus_address, prepare=gated(wrong)
    )
    [good] = await setup_mpris('good', bus_address=bus_address)
    await good.set_artist_title('artist', 'title')

    proc = await start_playerctld(bus_address)

    assert proc.returncode is None, proc.log
    await mpris.disconnect()
    await good.disconnect()


async def test_unanswered_get_all_does_not_block_other_players(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory(
        'slow', prepare=gated(lambda g: g.hold_get_all(PLAYER_INTERFACE))
    )
    await slow.gate.wait_held(1)

    [fast] = await mpris_factory('fast')
    await fast.set_artist_title('artist', 'title')

    assert await wait_for_players(daemon_bus, [PREFIX + 'fast'])
    slow.gate.release()
    await wait_for_players(daemon_bus, [PREFIX + 'fast', PREFIX + 'slow'])
    assert_healthy(playerctld)


async def test_memory_stays_flat_after_player_churn(
    bus_address, playerctld, daemon_bus
):
    skip_rss_check_under_asan()

    async def churn(rounds):
        for _ in range(rounds):
            evil = await RawPlayer.create(bus_address, 'churn')
            await evil.flood(10)
            await evil.disconnect()
            await wait_for_player_names(daemon_bus, [])

    await churn(20)  # warm up allocators
    before = vm_rss_kb(playerctld.pid)

    await churn(60)

    grown = vm_rss_kb(playerctld.pid) - before
    assert grown < 2048, f'RSS grew by {grown} kB over 60 churn cycles'
    assert playerctld.returncode is None

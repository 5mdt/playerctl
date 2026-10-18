"""US-10.17: As a scripter, I want playerctld to answer invalid or
unanswerable requests with a D-Bus error instead of hanging or crashing."""

import asyncio

from dbus_next import MessageType, Variant

from ..helpers.daemon import player_names, playerctld_call, settle
from ..helpers.mpris import gated

PLAYER = 'org.mpris.MediaPlayer2.Player'
PROPERTIES = 'org.freedesktop.DBus.Properties'
PLAYERCTLD = 'org._5mdt.playerctld'
PREFIX = 'org.mpris.MediaPlayer2.'


async def test_unknown_method_is_an_error(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(daemon_bus, PLAYER, 'NoSuchMethod')

    assert reply.message_type == MessageType.ERROR
    assert reply.error_name.startswith('org.freedesktop.DBus.Error.')
    assert await player_names(daemon_bus) == [PREFIX + 'player1']


async def test_unknown_interface_is_an_error(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(daemon_bus, 'org.example.Nothing', 'Play')

    assert reply.message_type == MessageType.ERROR
    assert reply.error_name.startswith('org.freedesktop.DBus.Error.')
    assert not mpris.play_called


async def test_unknown_playerctld_method_is_an_error(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(daemon_bus, PLAYERCTLD, 'Rotate')

    assert reply.message_type == MessageType.ERROR
    assert playerctld.returncode is None


async def test_unknown_playerctld_property_is_an_error_not_a_crash(
    playerctld, daemon_bus
):
    reply = await playerctld_call(
        daemon_bus, PROPERTIES, 'Get', 'ss', [PLAYERCTLD, 'NoSuchProperty']
    )

    assert reply.message_type == MessageType.ERROR
    assert playerctld.returncode is None


async def test_playerctld_properties_are_read_only(playerctld, daemon_bus):
    reply = await playerctld_call(
        daemon_bus,
        PROPERTIES,
        'Set',
        'ssv',
        [PLAYERCTLD, 'PlayerNames', Variant('as', ['x'])],
    )

    assert reply.message_type == MessageType.ERROR
    assert playerctld.returncode is None
    assert await player_names(daemon_bus) == []


async def test_property_calls_without_active_player_are_errors(
    playerctld, daemon_bus
):
    for member, signature, body in [
        ('Get', 'ss', [PLAYER, 'Volume']),
        ('GetAll', 's', [PLAYER]),
        ('Set', 'ssv', [PLAYER, 'Volume', Variant('d', 0.5)]),
    ]:
        reply = await playerctld_call(
            daemon_bus, PROPERTIES, member, signature, body
        )
        assert reply.message_type == MessageType.ERROR, member
        assert reply.error_name.endswith('NoActivePlayer'), member


async def test_set_of_a_read_only_property_is_an_error(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(
        daemon_bus,
        PROPERTIES,
        'Set',
        'ssv',
        [PLAYER, 'CanGoNext', Variant('b', False)],
    )

    assert reply.message_type == MessageType.ERROR
    assert mpris.can_go_next is True


async def test_slow_player_does_not_block_the_daemon(
    playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory(
        'slow', prepare=gated(lambda gate: gate.hold('Play'))
    )
    await slow.set_artist_title('artist1', 'title1')
    call = asyncio.ensure_future(playerctld_call(daemon_bus, PLAYER, 'Play'))
    await slow.gate.wait_held()

    # the daemon keeps answering while the player sits on the call
    assert await player_names(daemon_bus) == [PREFIX + 'slow']
    assert not call.done()

    slow.gate.release()
    reply = await asyncio.wait_for(call, 2.0)

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert slow.play_called


async def test_player_vanishing_during_a_call_answers_with_an_error(
    playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory(
        'slow', prepare=gated(lambda gate: gate.hold('Play'))
    )
    await slow.set_artist_title('artist1', 'title1')
    call = asyncio.ensure_future(playerctld_call(daemon_bus, PLAYER, 'Play'))
    await slow.gate.wait_held()

    await slow.disconnect()
    reply = await asyncio.wait_for(call, 2.0)

    assert reply.message_type == MessageType.ERROR
    await settle()
    assert playerctld.returncode is None
    assert await player_names(daemon_bus) == []

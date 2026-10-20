"""US-10.5: As an integrator, I want `ActivePlayerChangeBegin`/`End` signals."""

import asyncio

import pytest

from ..helpers.daemon import (
    SignalListener,
    player_names,
    playerctld_shift,
    start_playerctld,
)
from ..helpers.mpris import PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY

INTERFACES = [PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY]
PLAYER1 = 'org.mpris.MediaPlayer2.player1'
PLAYER2 = 'org.mpris.MediaPlayer2.player2'


@pytest.mark.parametrize('interface', INTERFACES)
async def test_signals_when_another_player_becomes_active(
    interface, bus_address, playerctld, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris2.set_artist_title('artist2', 'title2')

    assert await listener.next(interface, 'ActivePlayerChangeBegin') == [
        PLAYER2
    ]
    assert await listener.next(interface, 'ActivePlayerChangeEnd') == [PLAYER2]
    await listener.close()


async def test_begin_precedes_end(bus_address, playerctld, mpris_factory):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris2.set_artist_title('artist2', 'title2')

    seen = []
    while len(seen) < 2:
        interface, member, body = await listener.queue.get()
        if interface == PLAYERCTLD_INTERFACE and member.startswith(
            'ActivePlayerChange'
        ):
            seen.append((member, body))
    assert seen == [
        ('ActivePlayerChangeBegin', [PLAYER2]),
        ('ActivePlayerChangeEnd', [PLAYER2]),
    ]
    await listener.close()


async def test_signals_on_shift(bus_address, playerctld, mpris_factory):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    listener = await SignalListener.start(bus_address)

    assert await playerctld_shift(bus_address) == 0

    assert await listener.next(
        PLAYERCTLD_INTERFACE, 'ActivePlayerChangeBegin'
    ) == [PLAYER1]
    assert await listener.next(
        PLAYERCTLD_INTERFACE, 'ActivePlayerChangeEnd'
    ) == [PLAYER1]
    await listener.close()


async def test_signals_with_empty_name_when_last_player_leaves(
    bus_address, playerctld, mpris_factory
):
    [mpris1] = await mpris_factory('player1')
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris1.disconnect()

    assert await listener.next(
        PLAYERCTLD_INTERFACE, 'ActivePlayerChangeBegin'
    ) == ['']
    assert await listener.next(
        PLAYERCTLD_INTERFACE, 'ActivePlayerChangeEnd'
    ) == ['']
    await listener.close()


PREFIX = 'org.mpris.MediaPlayer2.'
PROPERTIES = 'org.freedesktop.DBus.Properties'
PLAYER_INTERFACE = 'org.mpris.MediaPlayer2.Player'
ROOT_INTERFACE = 'org.mpris.MediaPlayer2'
TRACKLIST = 'org.mpris.MediaPlayer2.TrackList'
PLAYLISTS = 'org.mpris.MediaPlayer2.Playlists'


async def signals_until_end(listener):
    """Everything emitted up to and including ActivePlayerChangeEnd."""
    seen = []
    while True:
        signal = await asyncio.wait_for(listener.queue.get(), 2.0)
        seen.append(signal)
        if signal[:2] == (PLAYERCTLD_INTERFACE, 'ActivePlayerChangeEnd'):
            return seen


def properties_changed(seen):
    return {
        body[0]: body
        for iface, member, body in seen
        if member == 'PropertiesChanged'
    }


def assert_full_announcement(seen):
    changed = properties_changed(seen)
    assert {PLAYER_INTERFACE, ROOT_INTERFACE, TRACKLIST, PLAYLISTS} <= set(
        changed
    )
    assert (
        changed[PLAYER_INTERFACE][1]['Metadata'].value['xesam:title'].value
        == 'title2'
    )
    assert (
        changed[ROOT_INTERFACE][1]['Identity'].value == 'playerctl test client'
    )
    assert changed[TRACKLIST][1]['Tracks'].value == ['/track/1', '/track/2']
    assert changed[PLAYLISTS][1]['PlaylistCount'].value == 3
    assert (PLAYER_INTERFACE, 'Seeked', [12345]) in seen


async def test_new_active_player_gets_full_properties_and_seeked(
    bus_address, playerctld, mpris_factory
):
    # the player appears while playerctld is already running
    [mpris1] = await mpris_factory('player1')
    [mpris2] = await mpris_factory('player2', tracklist=True, playlists=True)
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    mpris2.position = 12345
    await mpris2.set_artist_title('artist2', 'title2')

    assert_full_announcement(await signals_until_end(listener))
    await listener.close()


async def test_preexisting_player_gets_full_properties_and_seeked(
    bus_address, daemon_bus, mpris_factory
):
    # the player was running before playerctld started
    [plain] = await mpris_factory('plain')
    [mpris2] = await mpris_factory('tracks', tracklist=True, playlists=True)
    await plain.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    mpris2.position = 12345
    await start_playerctld(bus_address)
    if (await player_names(daemon_bus))[0] == PREFIX + 'tracks':
        assert await playerctld_shift(bus_address) == 0
    listener = await SignalListener.start(bus_address)

    assert await playerctld_shift(bus_address) == 0

    assert_full_announcement(await signals_until_end(listener))
    await listener.close()


async def test_optional_interfaces_are_not_announced_when_unsupported(
    bus_address, playerctld, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris2.set_artist_title('artist2', 'title2')
    seen = await signals_until_end(listener)

    changed = properties_changed(seen)
    assert PLAYER_INTERFACE in changed
    assert ROOT_INTERFACE in changed
    assert TRACKLIST not in changed
    assert PLAYLISTS not in changed
    await listener.close()


async def test_invalidation_names_the_right_interfaces_when_last_player_leaves(
    bus_address, playerctld, mpris_factory
):
    [mpris1] = await mpris_factory('player1', tracklist=True, playlists=True)
    await mpris1.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris1.disconnect()
    seen = await signals_until_end(listener)

    invalidated = {
        tuple(body[2]): body[0]
        for _, member, body in seen
        if member == 'PropertiesChanged' and body[2]
    }
    by_property = {}
    for names, interface in invalidated.items():
        for name in names:
            by_property[name] = interface
    assert by_property['Metadata'] == PLAYER_INTERFACE
    assert by_property['Identity'] == ROOT_INTERFACE
    assert by_property['Tracks'] == TRACKLIST
    assert by_property['CanEditTracks'] == TRACKLIST
    assert by_property['PlaylistCount'] == PLAYLISTS
    assert by_property['ActivePlaylist'] == PLAYLISTS
    await listener.close()

"""US-10.10: As a user, I want playerctld to pick up the players that were
already running before it started."""

from dbus_next import Message

from ..helpers.daemon import PLAYERCTLD_NAME, player_names, start_playerctld
from ..helpers.mpris import setup_partial_player

PREFIX = 'org.mpris.MediaPlayer2.'


async def list_managed_names(bus):
    reply = await bus.call(
        Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='ListNames',
        )
    )
    return [
        n
        for n in reply.body[0]
        if n.startswith(PREFIX) and n != PLAYERCTLD_NAME
    ]


async def test_existing_players_are_managed(
    bus_address, playerctl, daemon_bus, mpris_factory
):
    players = await mpris_factory('player1', 'player2', 'player3')
    for i, player in enumerate(players, 1):
        await player.set_artist_title(f'artist{i}', f'title{i}')
    listed = await list_managed_names(daemon_bus)

    await start_playerctld(bus_address)

    # every player is pushed to the head in the order the bus lists them, so
    # the last listed player ends up active
    assert await player_names(daemon_bus) == listed[::-1]
    active = listed[-1].removeprefix(PREFIX)
    result = await playerctl.run('-p playerctld metadata xesam:title')
    assert result.stdout == 'title' + active.removeprefix('player')


async def test_existing_players_can_be_controlled(
    bus_address, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    await start_playerctld(bus_address)

    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert mpris.play_called


async def test_players_without_mandatory_interfaces_are_dropped(
    bus_address, daemon_bus, mpris_factory
):
    await mpris_factory('good')
    buses = [
        await setup_partial_player('nothing', bus_address),
        await setup_partial_player('noroot', bus_address, player=True),
        await setup_partial_player('noplayer', bus_address, root=True),
    ]

    await start_playerctld(bus_address)

    assert await player_names(daemon_bus) == [PREFIX + 'good']
    for bus in buses:
        bus.disconnect()
        await bus.wait_for_disconnect()


async def test_players_without_optional_interfaces_are_kept(
    bus_address, daemon_bus, mpris_factory
):
    await mpris_factory('plain')
    await mpris_factory('tracks', tracklist=True)
    await mpris_factory('lists', playlists=True)
    await mpris_factory('both', tracklist=True, playlists=True)

    await start_playerctld(bus_address)

    assert sorted(await player_names(daemon_bus)) == [
        PREFIX + n for n in ('both', 'lists', 'plain', 'tracks')
    ]

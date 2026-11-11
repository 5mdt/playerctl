"""US-10.29: As a client of playerctld, I want its signals to tell the truth:
PlayerNames changes are announced, only the active player's changes are
forwarded, and a normal player does not make the daemon log warnings."""

import pytest
from dbus_next import Message, MessageType

from ..helpers.daemon import (
    MPRIS_PATH,
    PLAYERCTLD_NAME,
    settle,
    wait_for_player_names,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    PLAYER_INTERFACE,
    PREFIX,
    PlayerCollector,
    assert_healthy,
    new_bus,
    problems,
)
from ..helpers.mpris import PLAYERCTLD_INTERFACE


class Tap:
    '''Collects the PropertiesChanged signals of the daemon.'''

    def __init__(self, bus, owner):
        self.seen = []
        self.owner = owner
        bus.add_message_handler(self._handle)

    def _handle(self, msg):
        if (
            msg.message_type == MessageType.SIGNAL
            and msg.sender == self.owner
            and msg.member == 'PropertiesChanged'
        ):
            self.seen.append((msg.body[0], msg.body[1], msg.body[2]))

    def for_interface(self, interface):
        return [(c, i) for n, c, i in self.seen if n == interface]


async def tap(bus_address):
    bus = await new_bus(bus_address)
    reply = await bus.call(
        Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='GetNameOwner',
            signature='s',
            body=[PLAYERCTLD_NAME],
        )
    )
    owner = reply.body[0]
    await bus.call(
        Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member='AddMatch',
            signature='s',
            body=[f"type='signal',path='{MPRIS_PATH}',sender='{owner}'"],
        )
    )
    return Tap(bus, owner), bus


async def two_players(daemon_bus, mpris_factory):
    [older] = await mpris_factory('older')
    await older.set_artist_title('artist', 'older')
    [newer] = await mpris_factory('newer')
    await newer.set_artist_title('artist', 'newer')
    await wait_for_player_names(
        daemon_bus, [PREFIX + 'newer', PREFIX + 'older']
    )
    return older, newer


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D8: when an inactive player disappears the daemon changes '
    'PlayerNames but emits no PropertiesChanged for it (the property is '
    'announced as emitting changes), so clients caching it go stale',
)
async def test_inactive_player_leaving_is_announced_in_player_names(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    older, newer = await two_players(daemon_bus, mpris_factory)
    watcher, bus = await tap(bus_address)

    await older.disconnect()
    await wait_for_player_names(daemon_bus, [PREFIX + 'newer'])
    await settle()

    changes = watcher.for_interface(PLAYERCTLD_INTERFACE)
    assert changes, 'PlayerNames changed silently'
    assert changes[-1][0]['PlayerNames'].value == [PREFIX + 'newer']


async def test_active_player_leaving_is_announced_in_player_names(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    older, newer = await two_players(daemon_bus, mpris_factory)
    watcher, bus = await tap(bus_address)

    await newer.disconnect()
    await wait_for_player_names(daemon_bus, [PREFIX + 'older'])
    await settle()

    changes = watcher.for_interface(PLAYERCTLD_INTERFACE)
    assert changes[-1][0]['PlayerNames'].value == [PREFIX + 'older']


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D9: player_signal_proxy_callback() forwards every '
    'PropertiesChanged of an inactive player even when nothing changed '
    '(it did not become active), so clients attribute its values to the '
    'active player',
)
async def test_unchanged_properties_of_an_inactive_player_are_not_forwarded(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    older, newer = await two_players(daemon_bus, mpris_factory)
    watcher, bus = await tap(bus_address)

    # the very same value the player already had
    await older.emit_properties(volume=older.volume)
    await settle()

    assert watcher.for_interface(PLAYER_INTERFACE) == []


async def test_changed_properties_of_an_inactive_player_make_it_active(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    older, newer = await two_players(daemon_bus, mpris_factory)
    watcher, bus = await tap(bus_address)

    await older.emit_properties(volume=0.123)

    await wait_for_player_names(
        daemon_bus, [PREFIX + 'older', PREFIX + 'newer']
    )
    await settle()
    forwarded = watcher.for_interface(PLAYER_INTERFACE)
    assert forwarded and forwarded[-1][0]['Volume'].value == 0.123


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D1: a player without the optional TrackList/Playlists '
    'interfaces makes the daemon log a WARNING for each, every time it '
    'appears; missing optional interfaces are normal',
)
async def test_ordinary_player_makes_the_daemon_log_no_warning(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('plain')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'plain'])
    await settle()

    assert problems(playerctld, allow=()) == []


async def test_player_with_tracklist_and_playlists_makes_the_daemon_log_no_warning(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('rich', tracklist=True, playlists=True)
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'rich'])
    await settle()

    assert_healthy(playerctld, allow=())


async def test_names_in_player_names_and_signals_never_include_the_daemon_itself(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    collector = await PlayerCollector.start(bus_address)
    await two_players(daemon_bus, mpris_factory)
    await collector.wait_quiet()

    assert all(
        PLAYERCTLD_NAME not in v for k, v in collector.events if k == 'Names'
    )
    assert all(v != PLAYERCTLD_NAME for v in collector.end_names())
    await collector.close()

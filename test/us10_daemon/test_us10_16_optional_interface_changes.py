"""US-10.16: As a user, I want property changes on a player's TrackList and
Playlists interfaces to be tracked by playerctld like the Player ones, so that
players gaining those interfaces keep working and are not reported as
misbehaving."""

from dbus_next import Message
from dbus_next.service import Variant

from ..helpers.daemon import (
    SignalListener,
    player_names,
    playerctld_shift,
    settle,
    start_playerctld,
)
from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PLAYLISTS_INTERFACE,
    TRACKLIST_INTERFACE,
    MprisTrackList,
)

PREFIX = 'org.mpris.MediaPlayer2.'
PROPERTIES = 'org.freedesktop.DBus.Properties'
MPRIS_PATH = '/org/mpris/MediaPlayer2'
WARNING = "doesn't appear to support interface"


def warnings(playerctld, interface):
    return [
        line
        for line in playerctld.log
        if WARNING in line and interface in line
    ]


async def test_tracklist_change_makes_the_player_active(
    bus_address, daemon_bus, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory(
        'player1', 'player2', tracklist=True
    )
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    await start_playerctld(bus_address)
    assert (await player_names(daemon_bus))[0] == PREFIX + 'player2'

    mpris1.tracklist.emit_properties_changed({'Tracks': ['/track/9']})
    await mpris1.ping()
    await settle()

    assert (await player_names(daemon_bus))[0] == PREFIX + 'player1'


async def test_playlists_change_makes_the_player_active(
    bus_address, daemon_bus, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory(
        'player1', 'player2', playlists=True
    )
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    await start_playerctld(bus_address)
    assert (await player_names(daemon_bus))[0] == PREFIX + 'player2'

    mpris1.playlists.emit_properties_changed({'PlaylistCount': 9})
    await mpris1.ping()
    await settle()

    assert (await player_names(daemon_bus))[0] == PREFIX + 'player1'


async def test_tracklist_change_of_a_tracklist_player_is_not_a_warning(
    bus_address, daemon_bus, mpris_factory
):
    # the player has TrackList but no Playlists; the check for the TrackList
    # branch looks at `playlists.supported`
    [mpris] = await mpris_factory('tracks', tracklist=True)
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address)

    mpris.tracklist.emit_properties_changed({'CanEditTracks': True})
    await mpris.ping()
    await settle()

    assert not warnings(playerctld, TRACKLIST_INTERFACE), playerctld.log


async def test_playlists_change_of_a_playlists_player_is_not_a_warning(
    bus_address, mpris_factory
):
    [mpris] = await mpris_factory('lists', playlists=True)
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address)

    mpris.playlists.emit_properties_changed({'PlaylistCount': 9})
    await mpris.ping()
    await settle()

    assert not warnings(playerctld, PLAYLISTS_INTERFACE), playerctld.log


async def test_change_of_an_unsupported_interface_is_warned_about(
    bus_address, mpris_factory
):
    [mpris] = await mpris_factory('plain')
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address)

    mpris.bus.send(
        Message.new_signal(
            MPRIS_PATH,
            PROPERTIES,
            'PropertiesChanged',
            'sa{sv}as',
            [PLAYLISTS_INTERFACE, {'PlaylistCount': Variant('u', 1)}, []],
        )
    )
    await mpris.ping()
    await settle()

    assert warnings(playerctld, PLAYLISTS_INTERFACE), playerctld.log


async def test_tracklist_change_of_a_player_without_tracklist_is_warned_about(
    bus_address, mpris_factory
):
    # only Playlists is supported, so a TrackList change is unexpected
    [mpris] = await mpris_factory('lists', playlists=True)
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address)

    mpris.bus.send(
        Message.new_signal(
            MPRIS_PATH,
            PROPERTIES,
            'PropertiesChanged',
            'sa{sv}as',
            [TRACKLIST_INTERFACE, {'CanEditTracks': Variant('b', True)}, []],
        )
    )
    await mpris.ping()
    await settle()

    assert warnings(playerctld, TRACKLIST_INTERFACE), playerctld.log


async def test_late_player_changes_do_not_warn_about_its_own_interfaces(
    bus_address, playerctld, mpris_factory
):
    # a player that appears while playerctld runs is not flagged as lacking
    # the interfaces it exports
    [mpris] = await mpris_factory('late', tracklist=True, playlists=True)
    await mpris.set_artist_title('artist1', 'title1')

    mpris.tracklist.emit_properties_changed({'CanEditTracks': True})
    mpris.playlists.emit_properties_changed({'PlaylistCount': 9})
    await mpris.ping()
    await settle()

    assert not warnings(playerctld, 'org.mpris'), playerctld.log


async def test_player_gaining_tracklist_is_announced_with_it(
    bus_address, playerctld, mpris_factory
):
    [plain, gaining] = await mpris_factory('plain', 'gaining')
    await gaining.set_artist_title('artist1', 'title1')
    await plain.set_artist_title('artist2', 'title2')
    # the interface appears after the player was registered
    gaining.tracklist = MprisTrackList()
    gaining.bus.export(MPRIS_PATH, gaining.tracklist)
    gaining.tracklist.emit_properties_changed({'CanEditTracks': True})
    await gaining.ping()
    await settle()
    listener = await SignalListener.start(bus_address)

    # 'gaining' made itself active again, so shift away and back to it
    assert await playerctld_shift(bus_address) == 0
    await listener.until_end()
    assert await playerctld_shift(bus_address) == 0
    seen = await listener.until_end()

    announced = [
        body[0] for _, member, body in seen if member == 'PropertiesChanged'
    ]
    assert TRACKLIST_INTERFACE in announced
    await listener.close()


async def test_change_of_an_unknown_interface_does_not_crash_the_daemon(
    bus_address, daemon_bus, mpris_factory
):
    # altdesktop/playerctl#268: playerctld aborted on PropertiesChanged for
    # interfaces
    # that are not part of MPRIS
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    playerctld = await start_playerctld(bus_address)

    mpris1.bus.send(
        Message.new_signal(
            MPRIS_PATH,
            PROPERTIES,
            'PropertiesChanged',
            'sa{sv}as',
            ['org.example.Custom', {'Foo': Variant('u', 1)}, []],
        )
    )
    await mpris1.ping()
    await settle()

    assert playerctld.returncode is None, playerctld.log
    assert any('unknown interface' in line for line in playerctld.log)
    # the unknown change does not make the player active
    assert (await player_names(daemon_bus))[0] == PREFIX + 'player2'


async def test_wrongly_typed_properties_do_not_crash_the_daemon(
    bus_address, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address)

    mpris.bus.send(
        Message.new_signal(
            MPRIS_PATH,
            PROPERTIES,
            'PropertiesChanged',
            'sa{su}as',
            [PLAYER_INTERFACE, {'Volume': 1}, []],
        )
    )
    await mpris.ping()
    await settle()

    assert playerctld.returncode is None, playerctld.log
    assert any('unknown type' in line for line in playerctld.log)

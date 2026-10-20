"""US-10.18: As an integrator, I want playerctld to follow the MPRIS spec when
it announces optional interfaces and to survive players that disappear while
it is still initialising them."""

from dbus_next import Variant

from ..helpers.daemon import (
    SignalListener,
    player_names,
    settle,
    start_playerctld,
    wait_for_player_names,
)
from ..helpers.gi import FATAL_CRITICALS
from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PLAYLISTS_INTERFACE,
    ROOT_INTERFACE,
    TRACKLIST_INTERFACE,
    gated,
)

PREFIX = 'org.mpris.MediaPlayer2.'


async def property_changes(listener):
    """(interface, changed, invalidated) of every PropertiesChanged until the
    active player change ended."""
    seen = await listener.until_end()
    return [
        (body[0], body[1], body[2])
        for _, member, body in seen
        if member == 'PropertiesChanged'
    ]


async def test_invalidated_optional_properties_name_their_interface(
    bus_address, playerctld, mpris_factory
):
    # audit: playerctl-daemon.c:527,548 the TrackList and Playlists
    # invalidations were sent with the Root interface name
    [rich] = await mpris_factory('rich', tracklist=True, playlists=True)
    [bare] = await mpris_factory('bare')
    await rich.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await bare.set_artist_title('artist2', 'title2')

    changes = await property_changes(listener)
    tracklist = [
        inv for iface, _, inv in changes if iface == TRACKLIST_INTERFACE
    ]
    playlists = [
        inv for iface, _, inv in changes if iface == PLAYLISTS_INTERFACE
    ]
    assert any('Tracks' in inv for inv in tracklist), changes
    assert any('PlaylistCount' in inv for inv in playlists), changes
    root = [inv for iface, _, inv in changes if iface == ROOT_INTERFACE]
    assert not any('Tracks' in inv or 'PlaylistCount' in inv for inv in root)
    await listener.close()


async def test_late_player_announces_its_optional_interfaces(
    bus_address, playerctld, mpris_factory
):
    # audit: playerctl-daemon.c:1385-1427 a player that appears after startup
    # never got tracklist.supported / playlists.supported set
    [plain] = await mpris_factory('plain')
    await plain.set_artist_title('artist1', 'title1')
    [late] = await mpris_factory('late', tracklist=True, playlists=True)
    await late.set_artist_title('artist2', 'title2')
    await plain.set_artist_title('artist1', 'title1')
    await settle()
    listener = await SignalListener.start(bus_address)

    await late.set_artist_title('artist2', 'title2')

    changes = await property_changes(listener)
    announced = {iface for iface, changed, _ in changes if changed}
    assert TRACKLIST_INTERFACE in announced, changes
    assert PLAYLISTS_INTERFACE in announced, changes
    await listener.close()


async def test_player_vanishing_during_initialisation_does_not_crash(
    bus_address, daemon_bus, mpris_factory
):
    # audit: playerctl-daemon.c:1443 the player was freed while its async
    # GetAll calls were in flight (use-after-free in the reply callback)
    playerctld = await start_playerctld(bus_address)
    [slow] = await mpris_factory(
        'slow',
        prepare=gated(
            lambda g: g.hold_get_all(PLAYER_INTERFACE, ROOT_INTERFACE)
        ),
    )
    await slow.gate.wait_held(2)

    await slow.disconnect()
    await settle()

    assert playerctld.returncode is None, playerctld.log
    assert await player_names(daemon_bus) == []

    [fresh] = await mpris_factory('fresh')
    await fresh.set_artist_title('artist', 'title')
    assert await wait_for_player_names(daemon_bus, [PREFIX + 'fresh'])
    assert playerctld.returncode is None, playerctld.log


async def test_same_name_can_reappear_after_a_failed_initialisation(
    daemon_bus, playerctld, mpris_factory
):
    # audit: playerctl-daemon.c:1443 a player whose GetAll(Player) failed
    # stayed in pending_players, so a healthy successor was never promoted
    [broken] = await mpris_factory(
        'again', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )
    await settle()
    await broken.disconnect()
    await settle()

    [healthy] = await mpris_factory('again')
    await healthy.set_artist_title('artist', 'title')

    assert await wait_for_player_names(daemon_bus, [PREFIX + 'again'])
    assert playerctld.returncode is None, playerctld.log


async def test_wrongly_typed_position_does_not_abort_the_daemon(
    bus_address, mpris_factory
):
    # audit: playerctl-daemon.c:238 g_variant_lookup_value(..., NULL) with a
    # wrong typed Position raises GLib criticals
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    playerctld = await start_playerctld(bus_address, env=FATAL_CRITICALS)

    await mpris.send_properties_changed({'Position': Variant('s', 'soon')})
    await mpris.send_properties_changed({'Volume': Variant('s', 'loud')})
    await settle()

    assert playerctld.returncode is None, playerctld.log

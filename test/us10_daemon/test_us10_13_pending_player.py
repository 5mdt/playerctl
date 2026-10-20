"""US-10.13: As a user, I want playerctld to wait for a new player's initial
property reply before using it, so that a slow player never shows up half
initialised."""

from ..helpers.daemon import (
    SignalListener,
    player_names,
    settle,
    wait_for_player_names,
)
from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PLAYLISTS_INTERFACE,
    ROOT_INTERFACE,
    TRACKLIST_INTERFACE,
    gated,
)

PREFIX = 'org.mpris.MediaPlayer2.'
PLAYERCTLD = 'org._5mdt.playerctld'


def hold_player_and_root(gate):
    gate.hold_get_all(PLAYER_INTERFACE, ROOT_INTERFACE)


async def test_player_is_hidden_until_its_properties_arrive(
    playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory('slow', prepare=gated(hold_player_and_root))
    await slow.gate.wait_held(2)
    await settle()

    assert await player_names(daemon_bus) == []

    slow.gate.release()

    assert await wait_for_player_names(daemon_bus, [PREFIX + 'slow'])


async def test_pending_player_does_not_displace_the_active_player(
    playerctld, daemon_bus, playerctl, mpris_factory
):
    [fast] = await mpris_factory('fast')
    await fast.set_artist_title('artist1', 'title1')
    [slow] = await mpris_factory('slow', prepare=gated(hold_player_and_root))
    await slow.gate.wait_held(2)
    await settle()

    assert await player_names(daemon_bus) == [PREFIX + 'fast']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert fast.play_called
    assert not slow.play_called


async def test_signals_of_a_pending_player_are_ignored(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory('slow', prepare=gated(hold_player_and_root))
    await slow.gate.wait_held(2)
    await settle()
    listener = await SignalListener.start(bus_address)

    await slow.set_artist_title('artist1', 'title1')
    slow.seeked_value = 5000000
    slow.Seeked()
    await slow.ping()
    await settle()

    # nothing is forwarded or announced, and the player stays pending
    assert listener.queue.empty(), listener.queue.get_nowait()
    assert await player_names(daemon_bus) == []
    await listener.close()


async def test_pending_player_is_promoted_and_announced_on_reply(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [fast] = await mpris_factory('fast')
    await fast.set_artist_title('artist1', 'title1')
    [slow] = await mpris_factory('slow', prepare=gated(hold_player_and_root))
    await slow.gate.wait_held(2)
    await slow.set_artist_title('artist2', 'title2')
    await settle()
    listener = await SignalListener.start(bus_address)

    slow.gate.release()

    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == [
        PREFIX + 'slow'
    ]
    assert await player_names(daemon_bus) == [
        PREFIX + 'slow',
        PREFIX + 'fast',
    ]
    # the properties it changed while pending are what the daemon serves
    result = await playerctl.run('-p playerctld metadata xesam:title')
    assert result.stdout == 'title2'
    await listener.close()


async def test_player_stays_pending_until_both_replies_arrived(
    playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory(
        'slow', prepare=gated(lambda gate: gate.hold_get_all(ROOT_INTERFACE))
    )
    await slow.gate.wait_held(1)
    await settle()

    # the Player reply alone is not enough
    assert await player_names(daemon_bus) == []

    slow.gate.release()

    assert await wait_for_player_names(daemon_bus, [PREFIX + 'slow'])


async def test_late_optional_replies_do_not_demote_the_new_player(
    playerctld, daemon_bus, mpris_factory
):
    [old] = await mpris_factory('old')
    await old.set_artist_title('artist1', 'title1')
    [new] = await mpris_factory(
        'new',
        tracklist=True,
        playlists=True,
        prepare=gated(
            lambda gate: gate.hold_get_all(
                TRACKLIST_INTERFACE, PLAYLISTS_INTERFACE
            )
        ),
    )
    await new.gate.wait_held(2)
    # Player and Root replies promoted it already
    expected = [PREFIX + 'new', PREFIX + 'old']
    assert await wait_for_player_names(daemon_bus, expected)

    new.gate.release()
    await settle()

    # the TrackList/Playlists replies must not push it back behind `old`
    assert await player_names(daemon_bus) == expected

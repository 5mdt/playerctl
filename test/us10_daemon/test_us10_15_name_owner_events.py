"""US-10.15: As a user, I want playerctld to follow players that quit, come
back or hand their name over, so that the active player is always one that
is actually running."""

from dbus_next import NameFlag

from ..helpers.daemon import (
    SignalListener,
    player_names,
    settle,
    wait_for_player_names,
)
from ..helpers.mpris import PLAYER_INTERFACE, ROOT_INTERFACE, gated

PREFIX = 'org.mpris.MediaPlayer2.'
PLAYERCTLD = 'org._5mdt.playerctld'


async def test_player_can_release_and_reacquire_its_name(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [first] = await mpris_factory('again')
    await first.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await first.disconnect()
    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == ['']
    assert await player_names(daemon_bus) == []

    [second] = await mpris_factory('again')
    await second.set_artist_title('artist2', 'title2')

    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == [
        PREFIX + 'again'
    ]
    assert await player_names(daemon_bus) == [PREFIX + 'again']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert second.play_called
    assert not first.play_called
    await listener.close()


async def test_swapped_owner_of_an_inactive_player_becomes_active(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [old] = await mpris_factory('swap', name_flags=NameFlag.ALLOW_REPLACEMENT)
    [other] = await mpris_factory('other')
    await old.set_artist_title('artist1', 'title1')
    await other.set_artist_title('artist2', 'title2')
    assert await player_names(daemon_bus) == [
        PREFIX + 'other',
        PREFIX + 'swap',
    ]
    listener = await SignalListener.start(bus_address)

    # the name changes hands without a moment in between
    [new] = await mpris_factory('swap', name_flags=NameFlag.REPLACE_EXISTING)

    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == [
        PREFIX + 'swap'
    ]
    assert await player_names(daemon_bus) == [
        PREFIX + 'swap',
        PREFIX + 'other',
    ]
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert new.play_called
    assert not old.play_called
    await listener.close()


async def test_swapped_owner_keeps_working_after_the_old_one_quits(
    playerctld, daemon_bus, playerctl, mpris_factory
):
    [old] = await mpris_factory('swap', name_flags=NameFlag.ALLOW_REPLACEMENT)
    await old.set_artist_title('artist1', 'title1')
    [new] = await mpris_factory('swap', name_flags=NameFlag.REPLACE_EXISTING)
    await settle()

    # the old connection going away must not remove the new owner's player
    await old.disconnect()
    await settle()

    assert await player_names(daemon_bus) == [PREFIX + 'swap']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert new.play_called


async def test_active_player_vanishing_while_another_is_pending(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [active] = await mpris_factory('active')
    await active.set_artist_title('artist1', 'title1')
    [slow] = await mpris_factory(
        'slow',
        prepare=gated(
            lambda g: g.hold_get_all(PLAYER_INTERFACE, ROOT_INTERFACE)
        ),
    )
    await slow.gate.wait_held(2)
    await settle()
    listener = await SignalListener.start(bus_address)

    await active.disconnect()

    # the pending player is not a candidate yet: nobody is active
    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == ['']
    assert await player_names(daemon_bus) == []
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 1

    slow.gate.release()

    assert await listener.next(PLAYERCTLD, 'ActivePlayerChangeEnd') == [
        PREFIX + 'slow'
    ]
    assert await player_names(daemon_bus) == [PREFIX + 'slow']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert slow.play_called
    await listener.close()


async def test_pending_player_vanishing_before_its_reply(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [active] = await mpris_factory('active')
    await active.set_artist_title('artist1', 'title1')
    [slow] = await mpris_factory(
        'slow',
        prepare=gated(
            lambda g: g.hold_get_all(PLAYER_INTERFACE, ROOT_INTERFACE)
        ),
    )
    await slow.gate.wait_held(2)
    await settle()
    listener = await SignalListener.start(bus_address)

    await slow.disconnect()
    await settle()

    assert playerctld.returncode is None
    assert await player_names(daemon_bus) == [PREFIX + 'active']
    assert listener.queue.empty(), listener.queue.get_nowait()
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert active.play_called
    await listener.close()


async def test_reacquired_name_while_old_player_is_still_pending(
    playerctld, daemon_bus, mpris_factory
):
    [slow] = await mpris_factory(
        'twice',
        prepare=gated(
            lambda g: g.hold_get_all(PLAYER_INTERFACE, ROOT_INTERFACE)
        ),
    )
    await slow.gate.wait_held(2)
    await slow.disconnect()
    await settle()

    [fresh] = await mpris_factory('twice')
    await fresh.set_artist_title('artist1', 'title1')

    assert await wait_for_player_names(daemon_bus, [PREFIX + 'twice'])
    assert playerctld.returncode is None

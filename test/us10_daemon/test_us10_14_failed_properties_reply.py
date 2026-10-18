"""US-10.14: As a user, I want playerctld to never use a player that cannot
answer its initial property request, so that a broken player cannot take over
or crash the daemon."""

from ..helpers.daemon import (
    SignalListener,
    player_names,
    settle,
    wait_for_player_names,
)
from ..helpers.mpris import PLAYER_INTERFACE, ROOT_INTERFACE, gated

PREFIX = 'org.mpris.MediaPlayer2.'
PLAYERCTLD = 'org._5mdt.playerctld'


async def test_player_whose_player_reply_fails_never_becomes_active(
    playerctld, daemon_bus, mpris_factory
):
    [broken] = await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )
    await settle()

    assert await player_names(daemon_bus) == []
    assert any(
        'could not get properties for active player' in line
        for line in playerctld.log
    ), playerctld.log
    assert playerctld.returncode is None
    assert broken.bus.connected


async def test_player_whose_root_reply_fails_never_becomes_active(
    playerctld, daemon_bus, mpris_factory
):
    await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(ROOT_INTERFACE))
    )
    await settle()

    assert await player_names(daemon_bus) == []


async def test_failed_player_does_not_disturb_the_active_player(
    bus_address, playerctld, daemon_bus, playerctl, mpris_factory
):
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )
    await settle()

    assert listener.queue.empty(), listener.queue.get_nowait()
    assert await player_names(daemon_bus) == [PREFIX + 'good']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert good.play_called
    await listener.close()


async def test_failed_player_signals_do_not_make_it_active(
    playerctld, daemon_bus, mpris_factory
):
    [broken] = await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(ROOT_INTERFACE))
    )
    await settle()

    await broken.set_artist_title('artist1', 'title1')
    await settle()

    assert await player_names(daemon_bus) == []
    assert playerctld.returncode is None


async def test_failed_player_signals_after_another_player_appeared(
    playerctld, daemon_bus, playerctl, mpris_factory
):
    # once a later player appeared, the failed one is no longer the
    # `pending_active` player whose signals are dropped
    [broken] = await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(ROOT_INTERFACE))
    )
    await settle()
    [good] = await mpris_factory('good')
    await wait_for_player_names(daemon_bus, [PREFIX + 'good'])

    await broken.set_artist_title('artist1', 'title1')
    await settle()

    assert playerctld.returncode is None, playerctld.log
    assert await player_names(daemon_bus) == [PREFIX + 'good']
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert good.play_called


async def test_failed_player_can_vanish_quietly(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [good] = await mpris_factory('good')
    await good.set_artist_title('artist1', 'title1')
    [broken] = await mpris_factory(
        'broken', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )
    await settle()
    listener = await SignalListener.start(bus_address)

    await broken.disconnect()
    await settle()

    assert playerctld.returncode is None
    assert await player_names(daemon_bus) == [PREFIX + 'good']
    assert listener.queue.empty(), listener.queue.get_nowait()
    await listener.close()


async def test_missing_optional_interfaces_do_not_block_promotion(
    playerctld, daemon_bus, mpris_factory
):
    # GetAll for TrackList/Playlists fails with an error for a plain player
    await mpris_factory('plain')

    assert await wait_for_player_names(daemon_bus, [PREFIX + 'plain'])
    assert any(
        'could not get properties for active player' in line
        for line in playerctld.log
    ), playerctld.log

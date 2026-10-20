"""US-11.10: As a developer, I want the library to survive players that
vanish mid-call or answer slowly, failing or not at all."""

import asyncio

import pytest

from ..helpers.mpris import PLAYER_INTERFACE, gated

HELD_CALLS = {
    'play': ("play()", lambda g: g.hold('Play')),
    'seek': ("seek(1000)", lambda g: g.hold('Seek')),
    'open': ("open('file:///a')", lambda g: g.hold('OpenUri')),
    'get_position': ("get_position()", lambda g: g.hold('Get')),
}


@pytest.mark.parametrize(
    ('call', 'configure'), HELD_CALLS.values(), ids=HELD_CALLS.keys()
)
async def test_player_vanishing_during_a_call(
    call, configure, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('van', prepare=gated(configure))
    call_task = asyncio.ensure_future(
        gi_run(f"""
            player = Playerctl.Player.new('van')
            try:
                player.{call}
                out('no error')
            except GLib.Error as e:
                out('error')
        """)
    )

    await mpris.gate.wait_held()
    await mpris.disconnect()
    result = await asyncio.wait_for(call_task, 4)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['error']


async def test_slow_get_all_delays_creation(gi_run, mpris_factory):
    [mpris] = await mpris_factory(
        'van', prepare=gated(lambda g: g.hold_get_all(PLAYER_INTERFACE))
    )
    mpris.volume = 0.5
    task = asyncio.ensure_future(
        gi_run("""
            player = Playerctl.Player.new('van')
            out(player.props.volume, player.props.can_play)
        """)
    )

    await mpris.gate.wait_held()
    await asyncio.sleep(0.3)
    assert not task.done()
    mpris.gate.release()
    result = await asyncio.wait_for(task, 4)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['0.5 True']


async def test_failing_get_all_still_gives_a_usable_player(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory(
        'van', prepare=gated(lambda g: g.fail_get_all(PLAYER_INTERFACE))
    )

    result = await gi_run("""
        player = Playerctl.Player.new('van')
        p = player.props
        out(p.volume, p.can_play, p.shuffle, p.loop_status.value_nick)
        player.play()
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['0.0 False False None']
    assert mpris.play_called


async def test_player_vanishing_during_creation(gi_run, mpris_factory):
    [mpris] = await mpris_factory(
        'van', prepare=gated(lambda g: g.hold_get_all(PLAYER_INTERFACE))
    )
    task = asyncio.ensure_future(
        gi_run("""
            try:
                player = Playerctl.Player.new('van')
            except GLib.Error as e:
                out('creation failed')
            else:
                try:
                    player.play()
                    out('no error')
                except GLib.Error as e:
                    out('call failed')
        """)
    )

    await mpris.gate.wait_held()
    await mpris.disconnect()
    result = await asyncio.wait_for(task, 4)

    # either the creation or the first call must report the vanished player
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() in (
        ['creation failed'],
        ['call failed'],
    )


async def test_exit_is_emitted_once_and_getters_survive(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('van')
    proc = await gi_start("""
        player = Playerctl.Player.new('van')

        def on_exit(player):
            out('exit')
            p = player.props
            out(p.can_play, p.can_control, p.can_seek, p.can_go_next)
            out(p.volume, p.shuffle, p.loop_status.value_nick)
            out(p.position >= 0, p.player_name)

        player.connect('exit', on_exit)
        run_loop(1500)
    """)

    await mpris.disconnect()

    assert await proc.queue.get() == 'exit'
    assert await proc.queue.get() == 'False False False False'
    assert await proc.queue.get() == '0.0 False None'
    assert await proc.queue.get() == 'True van'
    await asyncio.sleep(1.5)
    assert proc.queue.empty()


async def test_metadata_error_surfaces_from_the_helpers(gi_run, mpris_factory):
    def configure(gate):
        gate.strip_get_all(PLAYER_INTERFACE, 'Metadata')
        gate.fail('Get', arg=PLAYER_INTERFACE)

    [mpris] = await mpris_factory('van', prepare=gated(configure))

    result = await gi_run("""
        player = Playerctl.Player.new('van')
        for call in (player.get_title, player.get_artist, player.get_album,
                     lambda: player.print_metadata_prop(None),
                     lambda: player.set_position(5)):
            try:
                call()
                out('no error')
            except GLib.Error as e:
                out('error')
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['error'] * 5

"""US-11.8: As a developer, I want errors from the player to surface as
`GLib.Error` and the control methods to work for players on the system bus."""

import pytest

CALLS = {
    'play': 'play()',
    'pause': 'pause()',
    'play_pause': 'play_pause()',
    'stop': 'stop()',
    'next': 'next()',
    'previous': 'previous()',
    'seek': 'seek(1000)',
    'open': "open('file:///tmp/a.mp3')",
    'set_volume': 'set_volume(0.5)',
    'set_loop_status': 'set_loop_status(Playerctl.LoopStatus.TRACK)',
    'set_shuffle': 'set_shuffle(True)',
}


@pytest.mark.parametrize('call', CALLS.values(), ids=CALLS.keys())
async def test_player_error_surfaces_as_glib_error(
    call, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    mpris.error = 'it broke'

    result = await gi_run(f"""
        player = Playerctl.Player.new('lib')
        try:
            player.{call}
        except GLib.Error as e:
            out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    [line] = result.stdout.splitlines()
    assert line.startswith('error ')
    assert 'it broke' in line


async def test_set_position_error_surfaces_as_glib_error(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')
    mpris.error = 'it broke'

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        try:
            player.set_position(1000)
        except GLib.Error as e:
            out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    assert 'it broke' in result.stdout


async def test_calls_after_the_player_exits_fail(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start("""
        player = Playerctl.Player.new('lib')

        def on_exit(player):
            for call in (player.get_position, player.play):
                try:
                    call()
                    out('no error')
                except GLib.Error as e:
                    out('error')

        player.connect('exit', on_exit)
        run_loop()
    """)

    await mpris.disconnect()

    assert [await proc.queue.get() for _ in range(2)] == ['error', 'error']


async def test_control_methods_on_system_bus_player(gi_run, mpris_factory):
    [mpris] = await mpris_factory('sys', system=True)

    result = await gi_run("""
        player = Playerctl.Player.new_for_source(
            'sys', Playerctl.Source.DBUS_SYSTEM)
        player.play()
        player.next()
        player.seek(5)
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.play_called
    assert mpris.next_called
    assert mpris.seek_called_with == 5


async def test_setters_on_system_bus_player(gi_run, mpris_factory):
    [mpris] = await mpris_factory('sys', system=True)

    result = await gi_run("""
        player = Playerctl.Player.new_for_source(
            'sys', Playerctl.Source.DBUS_SYSTEM)
        for call in (
            lambda: player.set_volume(0.5),
            lambda: player.set_loop_status(Playerctl.LoopStatus.PLAYLIST),
            lambda: player.set_shuffle(True),
        ):
            try:
                call()
            except GLib.Error as e:
                out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == []
    assert mpris.volume == 0.5
    assert mpris.loop_status == 'Playlist'
    assert mpris.shuffle

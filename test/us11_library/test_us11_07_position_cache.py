"""US-11.7: As a developer, I want the `position` property to be extrapolated
from the last known position while the player is playing, frozen while it is
paused and reset when it stops or the track changes."""

START = 5_000_000  # microseconds

# Prints `<label>-now <position>` right after the start / 20ms after each
# signal and `<label>-later <position>` 300ms after that.
WATCH = """
    import time
    player = Playerctl.Player.new('pos')

    def report(label):
        out(label, player.props.position)

    def settle(label):
        # read after the handler: the cache is updated once signals are out
        def first():
            report(label + '-now')
            GLib.timeout_add(300, lambda: report(label + '-later') or False)
            return False

        GLib.timeout_add(20, first)

    player.connect('play', lambda p: settle('play'))
    player.connect('pause', lambda p: settle('pause'))
    player.connect('stop', lambda p: settle('stop'))
    player.connect('metadata', lambda p, m: settle('metadata'))
    player.connect('seeked', lambda p, pos: settle('seeked'))
    out('ready')
    report('initial-now')
    time.sleep(0.3)
    report('initial-later')
    loop = GLib.MainLoop()
    GLib.timeout_add(4000, loop.quit)
    loop.run()
"""


async def read(proc, label):
    '''Positions reported right after and 300ms after the given event.'''
    seen = {}
    while len(seen) < 2:
        name, value = (await proc.queue.get()).split()
        if name in (f'{label}-now', f'{label}-later'):
            seen[name] = int(value)
    return seen[f'{label}-now'], seen[f'{label}-later']


async def start(gi_start, mpris, status, position=START):
    mpris.playback_status = status
    mpris.position = position
    return await gi_start(WATCH)


async def test_position_advances_while_playing(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Playing')

    first, later = await read(proc, 'initial')

    assert START <= first < START + 250_000
    assert 250_000 <= later - first < 1_500_000


async def test_position_is_frozen_while_paused(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Paused')

    assert await read(proc, 'initial') == (START, START)


async def test_position_is_zero_while_stopped(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Stopped')

    assert await read(proc, 'initial') == (0, 0)


async def test_pausing_freezes_the_position(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Playing')
    await read(proc, 'initial')

    await mpris.emit_properties(playback_status='Paused')

    now, later = await read(proc, 'pause')
    assert now >= START + 250_000
    assert later == now


async def test_resuming_continues_from_the_frozen_position(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Paused')
    await read(proc, 'initial')

    await mpris.emit_properties(playback_status='Playing')

    now, later = await read(proc, 'play')
    assert START <= now < START + 250_000
    assert 250_000 <= later - now < 1_500_000


async def test_stopping_resets_the_position(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Playing')
    await read(proc, 'initial')

    await mpris.emit_properties(playback_status='Stopped')

    assert await read(proc, 'stop') == (0, 0)


async def test_position_is_zero_inside_the_stop_handler(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('pos')
    mpris.position = START
    proc = await gi_start("""
        player = Playerctl.Player.new('pos')
        player.connect('stop', lambda p: out('stop', p.props.position))
        run_loop()
    """)

    await mpris.emit_properties(playback_status='Stopped')

    assert await proc.queue.get() == 'stop 0'


async def test_track_change_resets_the_position(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    await mpris.set_artist_title('A', 'One')
    proc = await start(gi_start, mpris, 'Playing')
    await read(proc, 'initial')

    await mpris.set_artist_title('A', 'Two')

    now, later = await read(proc, 'metadata')
    assert 0 <= now < 250_000
    assert 250_000 <= later - now < 1_500_000


async def test_same_track_keeps_the_position(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Playing', position=0)
    await read(proc, 'initial')
    await mpris.set_artist_title('A', 'One', '/track/1')
    await read(proc, 'metadata')

    await mpris.set_artist_title('A', 'One (remaster)', '/track/1')

    now, _ = await read(proc, 'metadata')
    assert now >= 300_000


async def test_seeked_signal_updates_the_position(gi_start, mpris_factory):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Playing')
    await read(proc, 'initial')

    mpris.seeked_value = 9_000_000
    mpris.Seeked()
    await mpris.ping()

    now, later = await read(proc, 'seeked')
    assert 9_000_000 <= now < 9_250_000
    assert 250_000 <= later - now < 1_500_000


async def test_seeked_signal_while_paused_sets_the_position(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('pos')
    proc = await start(gi_start, mpris, 'Paused')
    await read(proc, 'initial')

    mpris.seeked_value = 9_000_000
    mpris.Seeked()
    await mpris.ping()

    assert await read(proc, 'seeked') == (9_000_000, 9_000_000)

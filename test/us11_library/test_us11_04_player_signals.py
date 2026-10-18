"""US-11.4: As a developer, I want GObject signals (`playback-status`, `play`,
`pause`, `stop`, `metadata`, `seeked`, `volume`, `exit`, ...)."""

import pytest

CONNECT = """
    player = Playerctl.Player.new('sig')
    player.connect('playback-status', lambda p, s: out('playback-status', s.value_nick))
    player.connect('play', lambda p: out('play'))
    player.connect('pause', lambda p: out('pause'))
    player.connect('stop', lambda p: out('stop'))
    player.connect('volume', lambda p, v: out('volume', v))
    player.connect('shuffle', lambda p, s: out('shuffle', s))
    player.connect('loop-status', lambda p, s: out('loop-status', s.value_nick))
    player.connect('metadata', lambda p, m: out('metadata', m['xesam:artist'][0], m['xesam:title']))
    player.connect('seeked', lambda p, pos: out('seeked', pos))
    player.connect('exit', lambda p: out('exit'))
    run_loop()
"""

# initial mock state, property change to emit, lines the signals should print
PROPERTY_SIGNALS = {
    'play': (
        {'playback_status': 'Paused'},
        {'playback_status': 'Playing'},
        ['play', 'playback-status Playing'],
    ),
    'pause': (
        {'playback_status': 'Playing'},
        {'playback_status': 'Paused'},
        ['pause', 'playback-status Paused'],
    ),
    'stop': (
        {'playback_status': 'Playing'},
        {'playback_status': 'Stopped'},
        ['playback-status Stopped', 'stop'],
    ),
    'volume': ({'volume': 1.0}, {'volume': 0.25}, ['volume 0.25']),
    'shuffle': ({'shuffle': False}, {'shuffle': True}, ['shuffle True']),
    'loop-status': (
        {'loop_status': 'None'},
        {'loop_status': 'Track'},
        ['loop-status Track'],
    ),
}


@pytest.mark.parametrize(
    ('initial', 'change', 'expected'),
    PROPERTY_SIGNALS.values(),
    ids=PROPERTY_SIGNALS.keys(),
)
async def test_property_signals(
    initial, change, expected, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('sig')
    for attr, value in initial.items():
        setattr(mpris, attr, value)
    proc = await gi_start(CONNECT)

    await mpris.emit_properties(**change)

    lines = [await proc.queue.get() for _ in expected]
    assert sorted(lines) == sorted(expected)


async def test_metadata_signal(gi_start, mpris_factory):
    [mpris] = await mpris_factory('sig')
    proc = await gi_start(CONNECT)

    await mpris.set_artist_title('Artist', 'Title')

    assert await proc.queue.get() == 'metadata Artist Title'


async def test_seeked_signal(gi_start, mpris_factory):
    [mpris] = await mpris_factory('sig')
    proc = await gi_start(CONNECT)

    mpris.seeked_value = 123456
    mpris.Seeked()
    await mpris.ping()

    assert await proc.queue.get() == 'seeked 123456'


async def test_exit_signal(gi_start, mpris_factory):
    [mpris] = await mpris_factory('sig')
    proc = await gi_start(CONNECT)

    await mpris.disconnect()

    assert await proc.queue.get() == 'exit'

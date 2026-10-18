"""US-11.3: As a developer, I want control methods and cached GObject
properties."""

import pytest
from dbus_next import Variant

from ..helpers.mpris import was_called


@pytest.mark.parametrize(
    'method', ['play', 'pause', 'play_pause', 'stop', 'next', 'previous']
)
async def test_control_methods(method, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(f"""
        Playerctl.Player.new('lib').{method}()
    """)

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, method)


async def test_seek_and_set_position(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        player.seek(1000000)
        player.set_position(2000000)
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.seek_called_with == 1000000
    assert mpris.set_position_called_with == ('/track/1', 2000000)


async def test_open(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run("""
        Playerctl.Player.new('lib').open('file:///tmp/song.mp3')
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == 'file:///tmp/song.mp3'


async def test_setters(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        player.set_volume(0.5)
        player.set_loop_status(Playerctl.LoopStatus.PLAYLIST)
        player.set_shuffle(True)
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.volume == 0.5
    assert mpris.loop_status == 'Playlist'
    assert mpris.shuffle


async def test_cached_properties_and_getters(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.volume = 0.25
    mpris.shuffle = True
    mpris.loop_status = 'Track'
    mpris.can_seek = False
    mpris.metadata = {
        'xesam:title': Variant('s', 'A Title'),
        'xesam:artist': Variant('as', ['An Artist']),
        'xesam:album': Variant('s', 'An Album'),
    }

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        props = player.props
        out(props.volume)
        out(props.shuffle)
        out(props.loop_status == Playerctl.LoopStatus.TRACK)
        out(props.playback_status == Playerctl.PlaybackStatus.PLAYING)
        out(props.can_play, props.can_pause, props.can_seek)
        out(player.get_title())
        out(player.get_artist())
        out(player.get_album())
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        '0.25',
        'True',
        'True',
        'True',
        'True True False',
        'A Title',
        'An Artist',
        'An Album',
    ]


async def test_get_position_reads_the_live_value(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.position = 1500000

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        out(player.get_position())
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['1500000']


async def test_set_position_with_string_track_id(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    # players that send mpris:trackid as a plain string are tolerated
    mpris.metadata = {'mpris:trackid': Variant('s', '/track/str')}

    result = await gi_run("""
        Playerctl.Player.new('lib').set_position(3000000)
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.set_position_called_with == ('/track/str', 3000000)


async def test_set_position_without_track_id_fails(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        try:
            Playerctl.Player.new('lib').set_position(3000000)
        except GLib.Error as e:
            out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'error Could not get track id to set position'
    ]


async def test_gobject_properties(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib.inst')
    mpris.can_control = False
    mpris.can_go_next = False
    mpris.can_go_previous = False
    mpris.playback_status = 'Paused'
    mpris.position = 2000000
    mpris.metadata = {'xesam:title': Variant('s', 'T')}

    result = await gi_run("""
        player = Playerctl.Player.new('lib.inst')
        props = player.props
        out(props.player_name)
        out(props.source.value_nick)
        out(props.can_control, props.can_go_next, props.can_go_previous)
        out(props.status)
        out(props.position)
        out(props.metadata.unpack())
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'lib',
        'dbus-session',
        'False False False',
        'Paused',
        '2000000',
        "{'xesam:title': 'T'}",
    ]


async def test_volume_property_is_writable(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        player.props.volume = 0.3
        loop = GLib.MainLoop()
        GLib.timeout_add(500, loop.quit)
        loop.run()
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.volume == 0.3


async def test_deprecated_on_connects_a_closure(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start("""
        player = Playerctl.Player.new('lib')
        player.on('volume', lambda p, v: out('volume', v))
        run_loop()
    """)

    await mpris.emit_properties(volume=0.5)

    assert await proc.queue.get() == 'volume 0.5'


async def test_metadata_printing(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.metadata = {
        'xesam:title': Variant('s', 'A Title'),
        'xesam:artist': Variant('as', ['One', 'Two']),
        'mpris:length': Variant('x', 123),
    }

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        out(player.print_metadata_prop('xesam:title'))
        out(player.print_metadata_prop('xesam:artist'))
        out(player.print_metadata_prop('mpris:length'))
        out(player.print_metadata_prop('xesam:album'))
        out(player.get_artist())
        out(player.print_metadata_prop(None))
    """)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:5] == ['A Title', 'One, Two', '123', 'None', 'One, Two']
    table = [line.split() for line in lines[5:]]
    assert sorted(table) == sorted(
        [
            ['lib', 'xesam:title', 'A', 'Title'],
            ['lib', 'xesam:artist', 'One'],
            ['lib', 'xesam:artist', 'Two'],
            ['lib', 'mpris:length', '123'],
        ]
    )


async def test_getters_are_none_without_metadata(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        out(player.get_artist(), player.get_title(), player.get_album())
        out(player.print_metadata_prop(None))
        out(player.print_metadata_prop('xesam:title'))
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['None None None', 'None', 'None']

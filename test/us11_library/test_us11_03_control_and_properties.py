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

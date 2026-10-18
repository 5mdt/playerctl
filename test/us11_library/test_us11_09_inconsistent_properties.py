"""US-11.9: As a developer, I want the library to cope with players that send
PropertiesChanged inconsistently (Spotify-style cache bypass, invalidated
properties, missing track ids, wrong types, unknown status strings)."""

import pytest
from dbus_next import Variant

from ..helpers.mpris import PLAYER_INTERFACE, gated

LISTEN = """
    player = Playerctl.Player.new('inc')
    player.connect('playback-status', lambda p, s: out('playback-status', s.value_nick))
    player.connect('play', lambda p: out('play'))
    player.connect('pause', lambda p: out('pause'))
    player.connect('stop', lambda p: out('stop'))
    player.connect('volume', lambda p, v: out('volume', v))
    player.connect('shuffle', lambda p, s: out('shuffle', s))
    player.connect('loop-status', lambda p, s: out('loop-status', s.value_nick))
    player.connect('metadata', lambda p, m: out('metadata', m.get_type_string()))
    run_loop()
"""

TRACK = {
    'xesam:title': Variant('s', 'title'),
    'xesam:artist': Variant('as', ['artist']),
    'mpris:trackid': Variant('o', '/track/1'),
}


def spotify_style(gate):
    gate.strip_get_all(PLAYER_INTERFACE, 'Metadata')


async def settle(proc, mpris):
    """Send a valid change and wait for it: everything sent before it was
    processed, and the process survived it."""
    await mpris.emit_properties(volume=0.125)
    return await proc.queue.get()


async def test_metadata_missing_from_the_cache_is_fetched_directly(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory('inc', prepare=gated(spotify_style))
    await mpris.set_artist_title('artist', 'title', '/track/1')

    result = await gi_run("""
        player = Playerctl.Player.new('inc')
        out(player.props.metadata['xesam:title'])
        out(player.get_artist(), player.get_title())
        out(player.print_metadata_prop('mpris:trackid'))
        player.set_position(5)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'title',
        'artist title',
        "'/track/1'",
    ]
    assert mpris.set_position_called_with == ('/track/1', 5)


async def test_invalidated_metadata_is_fetched_directly(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    await mpris.set_artist_title('artist', 'title', '/track/1')
    proc = await gi_start("""
        player = Playerctl.Player.new('inc')
        GLib.timeout_add(500, lambda: out('title', player.get_title()) or False)
        run_loop()
    """)

    await mpris.send_properties_changed({}, ['Metadata'])

    assert await proc.queue.get() == 'title title'


@pytest.mark.parametrize(
    ('prop', 'attr', 'value', 'expected'),
    [
        ('Volume', 'volume', 0.5, '0.5'),
        ('Shuffle', 'shuffle', True, 'True'),
        ('CanPlay', 'can_play', True, 'True'),
    ],
)
async def test_invalidated_property_is_refetched(
    prop, attr, value, expected, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    setattr(mpris, attr, value)
    proc = await gi_start(
        f"""
        player = Playerctl.Player.new('inc')
        GLib.timeout_add(500, lambda: out('value', player.props.{attr}) or False)
        run_loop()
        """
    )

    await mpris.send_properties_changed({}, [prop])

    assert await proc.queue.get() == f'value {expected}'


async def test_metadata_without_track_id(gi_start, mpris_factory):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)

    await mpris.send_properties_changed(
        {'Metadata': Variant('a{sv}', {'xesam:title': Variant('s', 't')})}
    )
    assert await proc.queue.get() == 'metadata a{sv}'

    # a track id after none is a track change: the status is fetched again
    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', TRACK)})
    assert await proc.queue.get() == 'metadata a{sv}'
    assert await proc.queue.get() == 'play'
    assert await settle(proc, mpris) == 'volume 0.125'


async def test_metadata_with_a_wrongly_typed_track_id(gi_start, mpris_factory):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)

    bogus = {'mpris:trackid': Variant('i', 7)}
    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', bogus)})

    assert await proc.queue.get() == 'metadata a{sv}'
    assert await settle(proc, mpris) == 'volume 0.125'


async def test_playback_status_is_fetched_on_track_change(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)

    # the player changes state and track but only announces the track
    mpris.playback_status = 'Paused'
    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', TRACK)})

    lines = [await proc.queue.get() for _ in range(3)]
    assert lines == ['metadata a{sv}', 'pause', 'playback-status Paused']


async def test_playback_status_not_fetched_for_the_same_track(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)
    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', TRACK)})
    assert [await proc.queue.get() for _ in range(2)] == [
        'metadata a{sv}',
        'play',
    ]

    mpris.playback_status = 'Paused'
    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', TRACK)})

    assert await proc.queue.get() == 'metadata a{sv}'
    assert await settle(proc, mpris) == 'volume 0.125'


async def test_same_track_at_startup_does_not_reset_the_position(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    await mpris.set_artist_title('artist', 'title', '/track/1')
    mpris.playback_status = 'Paused'
    mpris.position = 5_000_000
    proc = await gi_start(
        """
        player = Playerctl.Player.new('inc')
        GLib.timeout_add(500, lambda: out('position', player.props.position) or False)
        run_loop()
        """
    )

    # only the title changed, the track is still the one the client found
    await mpris.send_properties_changed(
        {
            'Metadata': Variant(
                'a{sv}', {**TRACK, 'xesam:title': Variant('s', 'x')}
            )
        }
    )

    assert await proc.queue.get() == 'position 5000000'


async def test_playback_status_fetch_failure_is_ignored(
    gi_start, mpris_factory
):
    def configure(gate):
        gate.fail('Get', arg=PLAYER_INTERFACE)

    [mpris] = await mpris_factory('inc', prepare=gated(configure))
    proc = await gi_start(LISTEN)

    await mpris.send_properties_changed({'Metadata': Variant('a{sv}', TRACK)})

    assert await proc.queue.get() == 'metadata a{sv}'
    assert await settle(proc, mpris) == 'volume 0.125'


@pytest.mark.parametrize(
    ('prop', 'variant'),
    [
        ('PlaybackStatus', Variant('s', 'Buffering')),
        ('PlaybackStatus', Variant('s', '')),
        ('LoopStatus', Variant('s', 'Forever')),
    ],
    ids=['playback-unknown', 'playback-empty', 'loop-unknown'],
)
async def test_unknown_status_strings_are_ignored(
    prop, variant, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)

    await mpris.send_properties_changed({prop: variant})

    assert await settle(proc, mpris) == 'volume 0.125'


@pytest.mark.parametrize(
    'changed',
    [
        {'PlaybackStatus': Variant('i', 1)},
        {'LoopStatus': Variant('b', True)},
        {'Volume': Variant('s', 'loud')},
        {'Shuffle': Variant('s', 'yes')},
        {'Metadata': Variant('s', 'not a dictionary')},
        {'Position': Variant('s', 'start')},
    ],
    ids=[
        'playback-status',
        'loop-status',
        'volume',
        'shuffle',
        'metadata',
        'position',
    ],
)
async def test_wrongly_typed_changes_are_ignored(
    changed, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    proc = await gi_start(LISTEN)

    await mpris.send_properties_changed(changed)

    # no signal for the bogus value, and the next valid change still arrives
    assert await settle(proc, mpris) == 'volume 0.125'
    assert proc.running()


@pytest.mark.parametrize('status', ['Buffering', ''])
async def test_unknown_initial_playback_status_is_not_playing(
    status, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('inc')
    mpris.playback_status = status

    result = await gi_run("""
        player = Playerctl.Player.new('inc')
        out(player.props.playback_status == Playerctl.PlaybackStatus.PLAYING)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['False']


async def test_unknown_initial_loop_status_is_none(gi_run, mpris_factory):
    [mpris] = await mpris_factory('inc')
    mpris.loop_status = 'Forever'

    result = await gi_run("""
        player = Playerctl.Player.new('inc')
        out(player.props.loop_status.value_nick)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['None']


async def test_playback_status_missing_at_startup_is_not_playing(
    gi_run, mpris_factory
):
    await mpris_factory('inc', hidden=('PlaybackStatus',))

    result = await gi_run("""
        player = Playerctl.Player.new('inc')
        out(player.props.playback_status == Playerctl.PlaybackStatus.PLAYING)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['False']

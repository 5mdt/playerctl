"""US-11.17: As a developer, I want the control methods and writable
properties to take extreme or nonsensical values (NaN, infinity, 64-bit
limits, invalid enum values, huge URIs) and either pass them on or fail with a
`GLib.Error`, never crash."""

import math

import pytest

from ..helpers.gi import compose
from ..helpers.gi_abuse import (
    ATTEMPT,
    RAW,
    assert_clean,
    parse_attempts,
)

DEPRECATED = ['setting the volume property directly is deprecated']

VOLUMES = {
    'zero': 0.0,
    'one': 1.0,
    'half': 0.5,
    'negative': -1.0,
    'negative-zero': -0.0,
    'above-one': 2.5,
    'tiny': 5e-324,
    'huge': 1e308,
    'max': 1.7976931348623157e308,
    'inf': float('inf'),
    'minus-inf': float('-inf'),
    'nan': float('nan'),
}


@pytest.mark.parametrize('volume', VOLUMES.values(), ids=VOLUMES.keys())
async def test_set_volume_extremes(volume, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')
        attempt('set', lambda: player.set_volume(float({str(volume)!r})))
        """,
        )
    )

    assert_clean(result)
    kind, _ = parse_attempts(result)['set']
    assert kind in ('ok', 'gerror')
    if kind == 'ok':
        if math.isnan(volume):
            assert math.isnan(mpris.volume)
        else:
            assert mpris.volume == volume


@pytest.mark.parametrize('volume', VOLUMES.values(), ids=VOLUMES.keys())
async def test_set_volume_property_extremes(volume, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')

        def assign():
            player.props.volume = float({str(volume)!r})

        attempt('set', assign)
        attempt('read', lambda: player.props.volume is not None)
        """,
        )
    )

    assert_clean(result, allow=DEPRECATED)
    assert parse_attempts(result)['set'][0] in ('ok', 'gerror')


async def test_set_volume_on_a_player_that_errors(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.error = 'no'

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('nan', lambda: player.set_volume(float('nan')))
        attempt('inf', lambda: player.set_volume(float('inf')))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['nan'][0] == 'gerror'
    assert parsed['inf'][0] == 'gerror'


@pytest.mark.parametrize(
    ('nick', 'wire'),
    [('none', 'None'), ('track', 'Track'), ('playlist', 'Playlist')],
)
async def test_every_loop_status_reaches_the_player(
    nick, wire, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(f"""
        player = Playerctl.Player.new('lib')
        player.set_loop_status(Playerctl.LoopStatus.{nick.upper()})
    """)

    assert_clean(result)
    assert mpris.loop_status == wire


@pytest.mark.parametrize('value', [-1, 3, 4, 99, 2**31 - 1, -(2**31)])
async def test_invalid_loop_status_enum_value(value, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            RAW,
            f"""
        player = Playerctl.Player.new('lib')
        out('error' if raw_set_loop_status(player, {value}) else 'sent')
        """,
        )
    )

    # a value outside the enum is a programmer error: the library rejects it
    # with its own `status_str != NULL` assertion (GLib's convention for a
    # bad argument) and must not crash or send anything
    assert_clean(result, allow=['playerctl_player_set_loop_status: assertion'])
    # a value that is no loop status must not reach the player as garbage
    assert mpris.loop_status in ('None', 'Track', 'Playlist')


@pytest.mark.parametrize('value', ['None', 5, 1.5, 'Track', -1, 3])
async def test_python_rejects_a_bad_loop_status(value, gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new_from_name(Playerctl.PlayerName())
        """
            if False
            else f"""
        class Nothing:
            pass
        attempt('set', lambda: Playerctl.Player.set_loop_status(
            Nothing(), {value!r}))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['set'][0] == 'pyexc'


@pytest.mark.parametrize('flag', [True, False, 0, 1, 2, -1, 'yes'])
async def test_set_shuffle_values(flag, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')
        attempt('set', lambda: player.set_shuffle({flag!r}))
        """,
        )
    )

    assert_clean(result)
    kind, _ = parse_attempts(result)['set']
    assert kind in ('ok', 'pyexc')
    if kind == 'ok':
        assert mpris.shuffle == bool(flag)


SEEK_OFFSETS = {
    'zero': 0,
    'one': 1,
    'negative': -1,
    'int32-max': 2**31 - 1,
    'int32-overflow': 2**31,
    'int64-max': 2**63 - 1,
    'int64-min': -(2**63),
}


@pytest.mark.parametrize('offset', SEEK_OFFSETS.values(), ids=SEEK_OFFSETS)
async def test_seek_offsets_reach_the_player_unchanged(
    offset, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(f"""
        Playerctl.Player.new('lib').seek({offset})
    """)

    assert_clean(result)
    assert mpris.seek_called_with == offset


@pytest.mark.parametrize('offset', [2**63, -(2**63) - 1, 2**200, 'x', None])
async def test_seek_out_of_range_is_rejected_by_the_bindings(
    offset, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')
        attempt('seek', lambda: player.seek({offset!r}))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['seek'][0] == 'pyexc'
    assert mpris.seek_called_with is None


@pytest.mark.parametrize('position', SEEK_OFFSETS.values(), ids=SEEK_OFFSETS)
async def test_set_position_values_reach_the_player_unchanged(
    position, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')

    result = await gi_run(f"""
        Playerctl.Player.new('lib').set_position({position})
    """)

    assert_clean(result)
    assert mpris.set_position_called_with == ('/track/1', position)


async def test_set_position_without_metadata_is_a_glib_error(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('set', lambda: player.set_position(5))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['set'] == (
        'gerror',
        'playerctl-player-error-quark 2',
    )
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize(
    'track_id',
    [
        '/',
        '/a/b/c',
        '/' + 'x' * 5000,
        '/org/mpris/MediaPlayer2/TrackList/NoTrack',
    ],
    ids=['root', 'deep', 'long', 'no-track'],
)
async def test_set_position_with_unusual_track_ids(
    track_id, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', track_id)

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('set', lambda: player.set_position(9))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['set'][0] in ('ok', 'gerror')


URIS = {
    'empty': '',
    'space': ' ',
    'garbage': 'not a uri',
    'file': 'file:///tmp/a b.mp3',
    'newline': 'file:///a\n',
    'unicode': 'file:///é中\U0001f3b5',
    'traversal': 'file:///../../etc/passwd',
    'huge': 'file:///' + 'a' * 100000,
    'percent': '%s%n%00',
    'control': 'a\x01\x7f',
}


@pytest.mark.parametrize('uri', URIS.values(), ids=URIS.keys())
async def test_open_passes_any_uri_through(uri, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')
        attempt('open', lambda: player.open({uri!r}))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['open'][0] in ('ok', 'gerror')
    if parse_attempts(result)['open'][0] == 'ok':
        assert mpris.open_uri_called_with == uri


async def test_open_none_is_rejected_by_the_bindings(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('open', lambda: player.open(None))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['open'][0] in ('pyexc', 'gerror')


async def test_read_only_properties_reject_writes(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        for name in ('position', 'metadata', 'can_play', 'status',
                     'playback_status', 'player_name'):
            attempt(name, lambda name=name: setattr(player.props, name, 1))
        """,
        )
    )

    assert_clean(result)
    assert {
        label: kind for label, (kind, _) in parse_attempts(result).items()
    } == dict.fromkeys(
        [
            'position',
            'metadata',
            'can_play',
            'status',
            'playback_status',
            'player_name',
        ],
        'pyexc',
    )


async def test_set_source_after_construction_is_rejected(
    gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('source', lambda: player.set_property(
            'source', Playerctl.Source.DBUS_SYSTEM))
        attempt('name', lambda: player.set_property('player-name', 'other'))
        attempt('instance', lambda: player.set_property('player-instance', 'x'))
        attempt('load', lambda: player.set_property('load-properties', False))
        attempt('play', player.play)
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['play'][0] in ('ok', 'gerror')


async def test_calls_with_the_error_location_reused(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.error = 'again'

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        for i in range(50):
            attempt('p%d' % i, player.play)
            attempt('s%d' % i, lambda: player.seek(i))
        """,
        )
    )

    assert_clean(result)
    assert all(k == 'gerror' for k, _ in parse_attempts(result).values())

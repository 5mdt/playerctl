"""US-11.18: As a developer, I want hostile metadata, `PropertiesChanged` and
`Seeked` data from a player (wrong types, junk values, storms) to leave my
program alive and its GLib log free of CRITICALs."""

import asyncio

import pytest
from dbus_next import Message, Variant

from ..helpers.gi import compose
from ..helpers.gi_abuse import (
    ATTEMPT,
    LISTEN_ALL,
    assert_clean,
    assert_survived,
    parse_attempts,
    settle_and_stop,
)
from ..helpers.mpris import PLAYER_INTERFACE, gated
from ..helpers.playerctl import CommandResult

# GDBus itself drops a property or signal of the wrong type and says so
GDBUS_TYPE_WARNINGS = [
    'does not match expected type',
    'Dropping signal',
    'Received property',
]

TRACK = {
    'xesam:title': Variant('s', 'title'),
    'xesam:artist': Variant('as', ['artist']),
    'mpris:trackid': Variant('o', '/track/1'),
}

HOSTILE_METADATA = {
    'title-int': {'xesam:title': Variant('i', 5)},
    'title-array': {'xesam:title': Variant('as', ['a', 'b'])},
    'title-double': {'xesam:title': Variant('d', 1.5)},
    'title-bool': {'xesam:title': Variant('b', True)},
    'title-object-path': {'xesam:title': Variant('o', '/x')},
    'title-nested-variant': {'xesam:title': Variant('v', Variant('s', 'x'))},
    'title-empty': {'xesam:title': Variant('s', '')},
    'title-huge': {'xesam:title': Variant('s', 'x' * 500000)},
    'title-newlines': {
        'xesam:title': Variant('s', 'a\n\r\t\x00b'.replace('\x00', ''))
    },
    'title-unicode': {'xesam:title': Variant('s', 'é中\U0001f3b5​')},
    'artist-string': {'xesam:artist': Variant('s', 'solo')},
    'artist-empty-array': {'xesam:artist': Variant('as', [])},
    'artist-int-array': {'xesam:artist': Variant('ai', [1, 2])},
    'artist-1000': {
        'xesam:artist': Variant('as', [f'a{i}' for i in range(1000)])
    },
    'album-int64': {'xesam:album': Variant('x', 2**63 - 1)},
    'trackid-string': {'mpris:trackid': Variant('s', 'not a path')},
    'trackid-int': {'mpris:trackid': Variant('i', 3)},
    'trackid-array': {'mpris:trackid': Variant('ao', ['/a'])},
    'length-string': {'mpris:length': Variant('s', 'long')},
    'dict-value': {'xesam:title': Variant('a{sv}', {'k': Variant('s', 'v')})},
    'struct-value': {'xesam:title': Variant('(si)', ['a', 1])},
    'many-keys': {f'key{i}': Variant('s', 'v') for i in range(1000)},
    'empty-key': {'': Variant('s', 'v')},
    'odd-keys': {':': Variant('s', 'v'), 'a' * 5000: Variant('i', 1)},
    'bytes': {'xesam:title': Variant('ay', b'\xff\xfe')},
}

ODD_KEYS = {
    'empty': '',
    'colon': ':',
    'artist': 'xesam:artist',
    'length': 'mpris:length',
    'trackid': 'mpris:trackid',
    'unicode': 'é中',
    'long': 'k' * 10000,
    'case': 'XESAM:TITLE',
    'percent': '%s%n',
    'missing': 'xesam:nothing',
}


@pytest.mark.parametrize(
    'metadata', HOSTILE_METADATA.values(), ids=HOSTILE_METADATA.keys()
)
async def test_hostile_metadata_through_the_getters(
    metadata, gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    mpris.metadata = {'mpris:trackid': Variant('o', '/track/1'), **metadata}

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('title', player.get_title)
        attempt('artist', player.get_artist)
        attempt('album', player.get_album)
        attempt('all', lambda: player.print_metadata_prop(None))
        attempt('trackid', lambda: player.print_metadata_prop('mpris:trackid'))
        attempt('prop', lambda: player.props.metadata.get_type_string())
        attempt('position', lambda: player.set_position(5))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    for label in ('title', 'artist', 'album', 'all', 'trackid', 'prop'):
        assert parsed[label][0] in ('ok', 'gerror'), (label, parsed[label])
    assert parsed['position'][0] in ('ok', 'gerror')


@pytest.mark.parametrize('key', ODD_KEYS.values(), ids=ODD_KEYS.keys())
async def test_print_metadata_prop_with_odd_keys(key, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')
    mpris.metadata['mpris:length'] = Variant('x', 2**40)

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        player = Playerctl.Player.new('lib')
        attempt('prop', lambda: player.print_metadata_prop({key!r}))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['prop'][0] == 'ok'


async def test_metadata_getters_with_no_metadata_at_all(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.metadata = {}

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('title', player.get_title)
        attempt('all', lambda: player.print_metadata_prop(None))
        attempt('set_position', lambda: player.set_position(1))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['title'] == ('ok', 'None')
    assert parsed['set_position'][0] == 'gerror'


async def test_metadata_without_cache_and_a_wrongly_typed_reply(
    gi_run, mpris_factory
):
    def configure(gate):
        gate.strip_get_all(PLAYER_INTERFACE, 'Metadata')

        def wrong(reply):
            reply.signature = 's'
            reply.body = ['not a variant']
            return reply

        gate.rewrite('Get', None, PLAYER_INTERFACE, wrong)

    [mpris] = await mpris_factory('lib', prepare=gated(configure))

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('title', player.get_title)
        attempt('set_position', lambda: player.set_position(1))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['title'][0] == 'gerror'
    assert parsed['set_position'][0] == 'gerror'


async def test_get_position_when_the_player_has_no_position(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib', hidden=('Position',))

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('get', player.get_position)
        attempt('prop', lambda: player.props.position)
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['get'][0] == 'gerror'
    assert parsed['prop'][0] == 'ok'


@pytest.mark.parametrize('status', ['Stopped', 'Paused'])
async def test_get_position_when_not_playing(status, gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    mpris.playback_status = status
    mpris.position = 12345

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('get', player.get_position)
        attempt('prop', lambda: player.props.position)
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['get'] == ('ok', '12345')
    assert parsed['prop'][0] == 'ok'


@pytest.mark.parametrize(
    'reply',
    [
        pytest.param(('s', 'later'), id='string'),
        pytest.param(('d', 1.5), id='double'),
        pytest.param(('as', ['x']), id='array'),
        pytest.param(('b', True), id='bool'),
        pytest.param(('t', 2**64 - 1), id='uint64'),
    ],
)
async def test_get_position_with_a_wrongly_typed_reply(
    reply, gi_run, mpris_factory
):
    signature, value = reply

    def configure(gate):
        def wrong(r):
            r.signature = 'v'
            r.body = [Variant(signature, value)]
            return r

        gate.rewrite('Get', None, PLAYER_INTERFACE, wrong)

    await mpris_factory('lib', prepare=gated(configure))

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        attempt('get', player.get_position)
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['get'] == (
        'gerror',
        'playerctl-player-error-quark 3',
    )


PAYLOADS = {
    'metadata-int': {'Metadata': Variant('i', 5)},
    'metadata-string': {'Metadata': Variant('s', 'x')},
    'metadata-string-array': {'Metadata': Variant('as', ['x'])},
    'metadata-garbage-dict': {
        'Metadata': Variant(
            'a{sv}',
            {
                'mpris:trackid': Variant('s', 'nope'),
                'xesam:title': Variant('i', 1),
            },
        )
    },
    'metadata-empty': {'Metadata': Variant('a{sv}', {})},
    'metadata-1000-keys': {
        'Metadata': Variant(
            'a{sv}', {f'k{i}': Variant('s', 'v') for i in range(1000)}
        )
    },
    'volume-string': {'Volume': Variant('s', 'loud')},
    'volume-array': {'Volume': Variant('ad', [1.0])},
    'volume-int': {'Volume': Variant('i', 1)},
    'volume-nan': {'Volume': Variant('d', float('nan'))},
    'volume-inf': {'Volume': Variant('d', float('inf'))},
    'volume-negative': {'Volume': Variant('d', -3.0)},
    'shuffle-int': {'Shuffle': Variant('i', 1)},
    'shuffle-string': {'Shuffle': Variant('s', 'yes')},
    'loop-int': {'LoopStatus': Variant('i', 3)},
    'loop-bogus': {'LoopStatus': Variant('s', 'Bogus')},
    'loop-empty': {'LoopStatus': Variant('s', '')},
    'loop-lowercase': {'LoopStatus': Variant('s', 'track')},
    'status-int': {'PlaybackStatus': Variant('i', 1)},
    'status-empty': {'PlaybackStatus': Variant('s', '')},
    'status-bogus': {'PlaybackStatus': Variant('s', 'Exploding')},
    'status-lowercase': {'PlaybackStatus': Variant('s', 'playing')},
    'status-long': {'PlaybackStatus': Variant('s', 'P' * 100000)},
    'position-string': {'Position': Variant('s', 'x')},
    'position-negative': {'Position': Variant('x', -5)},
    'position-max': {'Position': Variant('x', 2**63 - 1)},
    'can-string': {'CanPlay': Variant('s', 'yes'), 'CanSeek': Variant('i', 1)},
    'unknown-property': {'Nonsense': Variant('s', 'x')},
    'empty-name': {'': Variant('s', 'x')},
    'everything-at-once': {
        'Volume': Variant('s', 'x'),
        'Shuffle': Variant('s', 'x'),
        'LoopStatus': Variant('s', 'x'),
        'PlaybackStatus': Variant('s', 'x'),
        'Metadata': Variant('s', 'x'),
        'Position': Variant('s', 'x'),
    },
    'nothing': {},
}


@pytest.mark.parametrize('payload', PAYLOADS.values(), ids=PAYLOADS.keys())
async def test_hostile_properties_changed(payload, gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(LISTEN_ALL)

    await mpris.send_properties_changed(payload)
    lines, stderr, returncode = await settle_and_stop(proc, mpris)

    assert_survived(stderr, returncode, allow=GDBUS_TYPE_WARNINGS)


@pytest.mark.parametrize(
    'interface',
    [
        '',
        'x' * 1000,
        'org.mpris.MediaPlayer2',
        'org.freedesktop.DBus.Properties',
    ],
    ids=['empty', 'long', 'root', 'properties'],
)
async def test_properties_changed_for_another_interface(
    interface, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(LISTEN_ALL)

    await mpris.send_properties_changed(
        {
            'Volume': Variant('d', 0.9),
            'PlaybackStatus': Variant('s', 'Paused'),
        },
        interface=interface,
    )
    lines, stderr, returncode = await settle_and_stop(proc, mpris)

    assert_survived(stderr, returncode, allow=GDBUS_TYPE_WARNINGS)
    assert 'volume 0.9' not in lines


@pytest.mark.parametrize(
    'invalidated',
    [
        ['Nope'],
        [''],
        ['Volume'] * 50,
        ['Metadata', 'Position', 'PlaybackStatus', 'Volume', 'Shuffle'],
        ['x' * 10000],
        [f'p{i}' for i in range(40)],
    ],
    ids=['unknown', 'empty', 'repeated', 'known', 'long', 'many'],
)
async def test_hostile_invalidated_properties(
    invalidated, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')
    proc = await gi_start(LISTEN_ALL)

    await mpris.send_properties_changed({}, invalidated)
    lines, stderr, returncode = await settle_and_stop(proc, mpris)

    assert_survived(
        stderr,
        returncode,
        allow=['could not get metadata', *GDBUS_TYPE_WARNINGS],
    )


async def send_seeked(mpris, signature, body):
    await mpris.bus.send(
        Message.new_signal(
            '/org/mpris/MediaPlayer2',
            PLAYER_INTERFACE,
            'Seeked',
            signature,
            body,
        )
    )
    await mpris.ping()


@pytest.mark.parametrize(
    ('signature', 'body'),
    [
        ('', []),
        ('s', ['soon']),
        ('d', [1.5]),
        ('ii', [1, 2]),
        ('as', [['a']]),
        ('t', [2**64 - 1]),
    ],
    ids=['none', 'string', 'double', 'two-ints', 'array', 'uint64'],
)
async def test_wrongly_typed_seeked(signature, body, gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(LISTEN_ALL)

    await send_seeked(mpris, signature, body)
    lines, stderr, returncode = await settle_and_stop(proc, mpris)

    assert_survived(stderr, returncode, allow=GDBUS_TYPE_WARNINGS)


@pytest.mark.parametrize('position', [0, -1, 2**63 - 1, -(2**63)])
async def test_seeked_extremes_reach_the_handler(
    position, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(LISTEN_ALL)

    await send_seeked(mpris, 'x', [position])
    lines, stderr, returncode = await settle_and_stop(proc, mpris)

    assert_survived(stderr, returncode, allow=GDBUS_TYPE_WARNINGS)
    assert f'seeked {position}' in lines


async def test_signal_storm(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(
        """
        player = Playerctl.Player.new('lib')
        seen = []
        player.connect('volume', lambda p, v: seen.append(v))
        player.connect('metadata', lambda p, m: seen.append('m'))
        player.connect('seeked', lambda p, v: seen.append('s'))

        def report():
            out('count', len(seen))
            return False

        loop = GLib.MainLoop()
        GLib.timeout_add(1500, report)
        GLib.timeout_add(1600, loop.quit)
        out('ready')
        loop.run()
        """
    )

    for i in range(400):
        mpris.emit_properties_changed(
            {
                'Volume': (i % 10) / 10,
                'Metadata': {'mpris:trackid': Variant('o', f'/t/{i}')},
            }
        )
        mpris.Seeked()
        if i % 10 == 9:
            await mpris.ping()

    count = await asyncio.wait_for(proc.queue.get(), 4)
    assert count.startswith('count ')
    assert int(count.split()[1]) > 100
    await proc.proc.wait()
    stderr = (await proc.proc.stderr.read()).decode()
    assert proc.proc.returncode == 0
    assert_clean(
        CommandResult(b"", stderr.encode(), 0), allow=GDBUS_TYPE_WARNINGS
    )

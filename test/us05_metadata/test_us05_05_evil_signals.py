"""US-5.5: As a bar author running `--follow`, I want a player that emits
PropertiesChanged or Seeked signals with wrong types, unknown interfaces or
garbage invalidated lists to be ignored: the follower keeps running, prints no
GLib noise, and still shows the next valid change."""

import asyncio

import pytest
from dbus_next import Variant

from ..helpers.sanitizer import xfail_under_asan
from ..helpers.evil_mpris import (
    GIO_TYPE_WARNING,
    INT64_MAX,
    INT64_MIN,
    metadata_with,
    send_signal,
)
from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    ROOT_INTERFACE,
)

FOLLOWS = {
    'metadata': "-p evil metadata --format '{{title}}|{{artist}}' --follow",
    'status': '-p evil status --follow',
    'metadata-all': (
        "-p evil metadata --format "
        "'{{title}}|{{status}}|{{volume}}|{{position}}|{{loop}}' --follow"
    ),
    'all-players': "-a metadata --format '{{title}}' --follow",
}

PCHANGED = [
    ('metadata-string', {'Metadata': Variant('s', 'x')}, []),
    ('metadata-ai', {'Metadata': Variant('ai', [1])}, []),
    (
        'metadata-trackid-int',
        {'Metadata': Variant('a{sv}', {'mpris:trackid': Variant('i', 3)})},
        [],
    ),
    (
        'metadata-title-int',
        {'Metadata': Variant('a{sv}', {'xesam:title': Variant('i', 3)})},
        [],
    ),
    (
        'metadata-empty',
        {'Metadata': Variant('a{sv}', {})},
        [],
    ),
    ('status-int', {'PlaybackStatus': Variant('i', 1)}, []),
    ('status-banana', {'PlaybackStatus': Variant('s', 'Banana')}, []),
    ('status-empty', {'PlaybackStatus': Variant('s', '')}, []),
    ('volume-string', {'Volume': Variant('s', 'x')}, []),
    ('volume-nan', {'Volume': Variant('d', float('nan'))}, []),
    ('position-string', {'Position': Variant('s', 'x')}, []),
    ('position-max', {'Position': Variant('x', INT64_MAX)}, []),
    ('loop-garbage', {'LoopStatus': Variant('s', 'garbage')}, []),
    ('loop-int', {'LoopStatus': Variant('i', 2)}, []),
    ('shuffle-string', {'Shuffle': Variant('s', 'maybe')}, []),
    ('can-string', {'CanPlay': Variant('s', 'x')}, []),
    ('unknown-property', {'Bogus': Variant('s', 'x')}, []),
    ('empty-name', {'': Variant('s', 'x')}, []),
    ('long-name', {'N' * 5000: Variant('s', 'x')}, []),
    (
        'nested-variant',
        {'Metadata': Variant('v', Variant('v', Variant('s', 'x')))},
        [],
    ),
    ('invalidate-garbage', {}, ['Bogus', '', 'x' * 1000, '‮', 'Metadata']),
    (
        'invalidate-all',
        {},
        [
            'PlaybackStatus',
            'Volume',
            'Position',
            'Metadata',
            'LoopStatus',
            'Shuffle',
            'CanPlay',
        ],
    ),
    ('invalidate-dupes', {}, ['Metadata'] * 200),
    ('changed-and-invalidated', {'Volume': Variant('d', 0.5)}, ['Volume']),
    ('big-changed', {f'K{i}': Variant('s', 'x') for i in range(2000)}, []),
]


async def start_follow(playerctl, mpris_factory, follow):
    [mpris] = await mpris_factory('evil')
    await mpris.set_artist_title('first', 'before')
    proc = await playerctl.start(FOLLOWS[follow])
    await asyncio.wait_for(proc.queue.get(), 3)
    return mpris, proc


async def assert_follower_healthy(proc, mpris, follow):
    """Still running, then a valid change is shown, and stderr is clean."""
    assert proc.running(), 'follower exited'
    if follow != 'status':
        await mpris.set_artist_title('second', 'after')
        # an invalidated list repeats the update once per entry
        for _ in range(1000):
            line = await asyncio.wait_for(proc.queue.get(), 3)
            if line.startswith('after'):
                break
        else:
            raise AssertionError('valid change was never printed')
    assert proc.running()
    proc.proc.terminate()
    await proc.proc.wait()
    stderr = (await proc.proc.stderr.read()).decode()
    # BUG-E1 (GIO type warning) is tracked in us05_03
    stderr = '\n'.join(
        line for line in stderr.splitlines() if GIO_TYPE_WARNING not in line
    )
    for noise in ('CRITICAL', 'WARNING', 'assertion'):
        assert noise not in stderr, stderr[:500]
    assert proc.proc.returncode in (0, -15)


@pytest.mark.parametrize('follow', ['metadata', 'status', 'metadata-all'])
@pytest.mark.parametrize(
    ('changed', 'invalidated'),
    [(c, i) for _, c, i in PCHANGED],
    ids=[n for n, _, _ in PCHANGED],
)
async def test_garbage_properties_changed(
    changed, invalidated, follow, playerctl, mpris_factory
):
    mpris, proc = await start_follow(playerctl, mpris_factory, follow)

    await mpris.send_properties_changed(changed, invalidated)

    await assert_follower_healthy(proc, mpris, follow)


@pytest.mark.parametrize(
    'interface',
    [
        'org.example.Unknown',
        '',
        ROOT_INTERFACE,
        'org.mpris.MediaPlayer2.TrackList',
        'org.mpris.MediaPlayer2.Player.Extra',
        'x' * 1000,
        '‮',
    ],
    ids=[
        'unknown',
        'empty',
        'root',
        'tracklist',
        'player-extra',
        'long',
        'rtl',
    ],
)
@pytest.mark.parametrize('follow', ['metadata', 'metadata-all'])
async def test_properties_changed_for_other_interface(
    interface, follow, playerctl, mpris_factory
):
    mpris, proc = await start_follow(playerctl, mpris_factory, follow)

    await mpris.send_properties_changed(
        {
            'Metadata': Variant(
                'a{sv}', metadata_with(xesam__title=Variant('s', 'hijack'))
            ),
            'PlaybackStatus': Variant('s', 'Stopped'),
        },
        ['Metadata'],
        interface=interface,
    )

    await assert_follower_healthy(proc, mpris, follow)


@pytest.mark.parametrize(
    ('signature', 'body'),
    [
        ('ss', ['a', 'b']),
        ('s', [PLAYER_INTERFACE]),
        ('', []),
        ('a{sv}', [{}]),
        ('sa{sv}', [PLAYER_INTERFACE, {}]),
        ('sa{sv}as', [PLAYER_INTERFACE, {'Metadata': Variant('i', 1)}, []]),
        ('i', [7]),
        ('sa{ss}as', [PLAYER_INTERFACE, {'Metadata': 'x'}, []]),
        ('sa{sv}asi', [PLAYER_INTERFACE, {}, [], 5]),
        ('as', [[PLAYER_INTERFACE]]),
        ('v', [Variant('s', 'x')]),
    ],
    ids=[
        'ss',
        's',
        'empty',
        'dict-only',
        'no-invalidated',
        'no-invalidated-bad',
        'int',
        'ss-dict',
        'extra-arg',
        'as',
        'variant',
    ],
)
@pytest.mark.parametrize('follow', ['metadata', 'status'])
async def test_properties_changed_wrong_signature(
    signature, body, follow, playerctl, mpris_factory
):
    mpris, proc = await start_follow(playerctl, mpris_factory, follow)

    await send_signal(
        mpris, 'PropertiesChanged', signature, body, PROPERTIES_INTERFACE
    )

    await assert_follower_healthy(proc, mpris, follow)


@pytest.mark.parametrize(
    ('signature', 'body'),
    [
        ('x', [INT64_MAX]),
        ('x', [INT64_MIN]),
        ('x', [-1]),
        ('s', ['now']),
        ('d', [1.5]),
        ('t', [2**64 - 1]),
        ('', []),
        ('xx', [1, 2]),
        ('ai', [[1, 2]]),
        ('v', [Variant('x', 1)]),
    ],
    ids=[
        'max',
        'min',
        'neg',
        'string',
        'double',
        'uint',
        'none',
        'two',
        'array',
        'variant',
    ],
)
@pytest.mark.parametrize('follow', ['metadata', 'metadata-all'])
async def test_garbage_seeked(
    signature, body, follow, playerctl, mpris_factory, request
):
    if request.node.callspec.id == 'metadata-all-max':
        # {{position}} renders cached_position + elapsed time: INT64_MAX + n is
        # signed overflow (playerctl-player.c:106). Silent wrap in the plain
        # build, UBSan abort (exit 1) in the sanitizer build.
        xfail_under_asan(
            request,
            'BUG-E4: signed overflow in calculate_cached_position '
            '(UBSan aborts the follower)',
        )
    mpris, proc = await start_follow(playerctl, mpris_factory, follow)

    await send_signal(mpris, 'Seeked', signature, body, PLAYER_INTERFACE)

    await assert_follower_healthy(proc, mpris, follow)


@pytest.mark.parametrize(
    ('interface', 'member'),
    [
        (PLAYER_INTERFACE, 'Bogus'),
        (PLAYER_INTERFACE, ''.join(['M'] * 255)),
        ('org.example.Foo', 'Seeked'),
        (ROOT_INTERFACE, 'Seeked'),
        (PROPERTIES_INTERFACE, 'Bogus'),
    ],
)
async def test_unknown_signals(interface, member, playerctl, mpris_factory):
    mpris, proc = await start_follow(playerctl, mpris_factory, 'metadata')

    await send_signal(mpris, member, 's', ['x'], interface)

    await assert_follower_healthy(proc, mpris, 'metadata')


@pytest.mark.parametrize('follow', ['metadata', 'status', 'metadata-all'])
async def test_signal_storm_of_garbage(follow, playerctl, mpris_factory):
    mpris, proc = await start_follow(playerctl, mpris_factory, follow)

    for i in range(100):
        await mpris.send_properties_changed(
            {
                'Metadata': Variant('s', str(i)),
                'PlaybackStatus': Variant('i', i),
                'Volume': Variant('s', 'x'),
            },
            ['Metadata', 'Bogus'],
        )
        await send_signal(mpris, 'Seeked', 's', ['x'], PLAYER_INTERFACE)

    await assert_follower_healthy(proc, mpris, follow)


async def test_all_players_follow_with_garbage_from_one(
    playerctl, mpris_factory
):
    [evil, good] = await mpris_factory('evil', 'good')
    await good.set_artist_title('g', 'good-before')
    proc = await playerctl.start(FOLLOWS['all-players'])
    await asyncio.sleep(0.3)

    await evil.send_properties_changed(
        {'Metadata': Variant('s', 'x'), 'PlaybackStatus': Variant('i', 1)},
        ['Bogus'],
    )
    await send_signal(evil, 'Seeked', 's', ['x'], PLAYER_INTERFACE)
    await good.set_artist_title('g', 'good-after')

    for _ in range(8):
        line = await asyncio.wait_for(proc.queue.get(), 3)
        if line == 'good-after':
            break
    else:
        raise AssertionError('good player update lost')
    assert proc.running()


@pytest.mark.xfail(
    strict=True,
    reason='BUG-E1: GIO prints GLib-GIO-WARNING on stderr when a player '
    'sends PropertiesChanged with the wrong signature',
)
@pytest.mark.parametrize(
    ('signature', 'body'),
    [('s', [PLAYER_INTERFACE]), ('sa{sv}', [PLAYER_INTERFACE, {}])],
    ids=['s', 'no-invalidated'],
)
async def test_wrong_signature_does_not_warn(
    signature, body, playerctl, mpris_factory
):
    mpris, proc = await start_follow(playerctl, mpris_factory, 'status')
    await send_signal(
        mpris, 'PropertiesChanged', signature, body, PROPERTIES_INTERFACE
    )
    await asyncio.sleep(0.2)
    proc.proc.terminate()
    await proc.proc.wait()
    stderr = (await proc.proc.stderr.read()).decode()

    assert 'WARNING' not in stderr

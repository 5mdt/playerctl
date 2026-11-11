"""US-5.4: As a bar author, I want a player that publishes hostile metadata
(control characters, ANSI escapes, megabyte values, thousands of keys, wrong
value types, absurd lengths and track ids) to never crash or hang playerctl,
and the values that are valid to be printed unchanged."""

import pytest
from dbus_next import Variant

from ..helpers.evil_mpris import (
    HUGE,
    INT64_MAX,
    INT64_MIN,
    NASTY_STRINGS,
    assert_sane,
    metadata_with,
    run,
)


async def evil_meta(mpris_factory, name='evil', **extra):
    [mpris] = await mpris_factory(name)
    mpris.metadata = metadata_with(**extra)
    await mpris.ping()
    return mpris


@pytest.mark.parametrize('text', NASTY_STRINGS.values(), ids=NASTY_STRINGS)
async def test_nasty_title_is_printed_verbatim(text, playerctl, mpris_factory):
    await evil_meta(mpris_factory, xesam__title=Variant('s', text))

    result = await run(playerctl, '-p evil metadata title')

    assert_sane(result, allowed=(0,))
    assert result.stdout == text.strip()


@pytest.mark.parametrize('text', NASTY_STRINGS.values(), ids=NASTY_STRINGS)
async def test_nasty_title_in_table(text, playerctl, mpris_factory):
    await evil_meta(mpris_factory, xesam__title=Variant('s', text))

    result = await run(playerctl, '-p evil metadata')

    assert_sane(result, allowed=(0,))
    assert 'mpris:trackid' in result.stdout


@pytest.mark.parametrize('text', NASTY_STRINGS.values(), ids=NASTY_STRINGS)
async def test_nasty_artist_in_format(text, playerctl, mpris_factory):
    await evil_meta(mpris_factory, xesam__artist=Variant('as', [text, text]))

    result = await run(
        playerctl, "-p evil metadata --format '[{{artist}}] {{title}}'"
    )

    assert_sane(result, allowed=(0,))
    assert result.stdout.endswith(' T')


@pytest.mark.parametrize('key', ['title', 'artist', 'album'])
async def test_megabyte_value(key, playerctl, mpris_factory):
    big = 'x' * HUGE
    value = Variant('as', [big]) if key == 'artist' else Variant('s', big)
    await evil_meta(mpris_factory, **{f'xesam__{key}': value})

    result = await run(playerctl, f'-p evil metadata {key}')
    assert_sane(result, allowed=(0,))
    assert result.stdout == big

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    assert big in result.stdout


async def test_megabyte_value_in_format(playerctl, mpris_factory):
    big = 'y' * HUGE
    await evil_meta(mpris_factory, xesam__title=Variant('s', big))

    result = await run(playerctl, "-p evil metadata --format '{{title}}'")
    assert_sane(result, allowed=(0,))
    assert result.stdout == big

    result = await run(
        playerctl, "-p evil metadata --format '{{trunc(title, 10)}}'"
    )
    assert_sane(result, allowed=(0,))
    assert result.stdout.startswith('y' * 9)
    assert len(result.stdout) < 20


@pytest.mark.parametrize('count', [1000, 1500, 5000])
async def test_many_keys(count, playerctl, mpris_factory):
    extra = {f'xesam__k{i}': Variant('s', f'v{i}') for i in range(count)}
    await evil_meta(mpris_factory, **extra)

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    # trackid + title + artist + count keys
    assert len(result.stdout.splitlines()) == count + 3

    result = await run(playerctl, f'-p evil metadata xesam:k{count - 1}')
    assert_sane(result, allowed=(0,))
    assert result.stdout == f'v{count - 1}'

    result = await run(
        playerctl, f"-p evil metadata --format '{{{{xesam:k{count // 2}}}}}'"
    )
    assert_sane(result, allowed=(0,))
    assert result.stdout == f'v{count // 2}'


async def test_long_key_name(playerctl, mpris_factory):
    key = 'xesam:' + 'k' * 10000
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {key: Variant('s', 'val')}
    await mpris.ping()

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    assert key in result.stdout

    result = await run(playerctl, f'-p evil metadata {key}')
    assert result.stdout == 'val'


@pytest.mark.parametrize('count', [1000, 20000])
async def test_many_artists(count, playerctl, mpris_factory):
    artists = [f'artist{i}' for i in range(count)]
    await evil_meta(mpris_factory, xesam__artist=Variant('as', artists))

    result = await run(playerctl, '-p evil metadata artist')
    assert_sane(result, allowed=(0,))
    assert result.stdout.startswith('artist0, artist1, ')
    assert result.stdout.endswith(f'artist{count - 1}')

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    assert result.stdout.count('xesam:artist') >= 1

    result = await run(playerctl, "-p evil metadata --format '{{artist}}'")
    assert_sane(result, allowed=(0,))
    assert result.stdout.startswith('artist0')


async def test_empty_artist_array(playerctl, mpris_factory):
    await evil_meta(mpris_factory, xesam__artist=Variant('as', []))

    for cmd in (
        'metadata',
        'metadata artist',
        "metadata --format '[{{artist}}] {{title}}'",
    ):
        result = await run(playerctl, f'-p evil {cmd}')
        assert_sane(result, allowed=(0,))


async def test_artist_as_plain_string(playerctl, mpris_factory):
    await evil_meta(mpris_factory, xesam__artist=Variant('s', 'Solo'))

    result = await run(playerctl, '-p evil metadata artist')
    assert_sane(result, allowed=(0,))
    assert result.stdout == 'Solo'

    result = await run(
        playerctl, "-p evil metadata --format '{{artist}} - {{title}}'"
    )
    assert_sane(result, allowed=(0,))
    assert result.stdout == 'Solo - T'


@pytest.mark.parametrize(
    'value',
    [
        Variant('ai', [1, 2, 3]),
        Variant('i', 5),
        Variant('b', True),
        Variant('d', 1.5),
        Variant('a{sv}', {'a': Variant('s', 'b')}),
        Variant('(ss)', ['x', 'y']),
        Variant('v', Variant('s', 'nested')),
        Variant('v', Variant('v', Variant('v', Variant('as', ['deep'])))),
        Variant('aas', [['a', 'b'], ['c']]),
        Variant('av', [Variant('s', 'x'), Variant('i', 1)]),
        Variant('ay', b'\x00\xff'),
        Variant('g', 'a{sv}'),
        Variant('o', '/a/b'),
    ],
    ids=lambda v: v.signature,
)
@pytest.mark.parametrize('key', ['title', 'artist', 'album'])
async def test_odd_value_types(key, value, playerctl, mpris_factory):
    await evil_meta(mpris_factory, **{f'xesam__{key}': value})

    for cmd in (
        'metadata',
        f'metadata {key}',
        "metadata --format '{{artist}}|{{title}}|{{album}}'",
        f"metadata --format '{{{{uc(lc({key}))}}}}'",
        f"metadata --format '{{{{markup_escape({key})}}}}'",
        f"metadata --format '{{{{json_escape({key})}}}}'",
        f"metadata --format '{{{{trunc({key}, 3)}}}}'",
        f"metadata --format '{{{{pad({key}, 8)}}}}'",
    ):
        result = await run(playerctl, f'-p evil {cmd}')
        assert_sane(result)


@pytest.mark.parametrize(
    'length',
    [
        Variant('x', -1),
        Variant('x', 0),
        Variant('x', INT64_MAX),
        Variant('x', INT64_MIN),
        Variant('t', 2**64 - 1),
        Variant('i', -(2**31)),
        Variant('d', 1e300),
        Variant('d', float('nan')),
        Variant('d', float('inf')),
        Variant('s', 'long'),
    ],
    ids=lambda v: f'{v.signature}-{v.value}',
)
async def test_absurd_length(length, playerctl, mpris_factory):
    await evil_meta(mpris_factory, mpris__length=length)

    for cmd in (
        'metadata',
        'metadata mpris:length',
        "metadata --format '{{mpris:length}}'",
        "metadata --format '{{duration(mpris:length)}}'",
        "metadata --format '{{duration(mpris:length - position)}}'",
        "metadata --format '{{mpris:length * 2}} {{mpris:length / 0}}'",
        "metadata --format '{{round(mpris:length)}} {{int(mpris:length)}}'",
    ):
        result = await run(playerctl, f'-p evil {cmd}')
        assert_sane(result)


@pytest.mark.parametrize(
    'track_id',
    [
        Variant('s', 'not-a-path'),
        Variant('s', '/'),
        Variant('s', ''),
        Variant('s', '//double//slash'),
        Variant('s', '/trailing/'),
        Variant('s', '/has space'),
        Variant('s', '/' + 'a' * 100000),
        Variant('s', '/é'),
        Variant('o', '/'),
        Variant('i', 5),
        Variant('as', ['/a']),
    ],
    ids=lambda v: f'{v.signature}-{str(v.value)[:12]}',
)
async def test_odd_track_id(track_id, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {
        'mpris:trackid': track_id,
        'xesam:title': Variant('s', 'T'),
    }
    await mpris.ping()

    for cmd in (
        'metadata',
        'metadata mpris:trackid',
        "metadata --format '{{mpris:trackid}}'",
        'position 5',
        'position 5+',
        'position 5-',
    ):
        result = await run(playerctl, f'-p evil {cmd}')
        assert_sane(result)


async def test_missing_track_id_set_position_fails_cleanly(
    playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {}
    await mpris.ping()

    result = await run(playerctl, '-p evil position 5')

    assert_sane(result, allowed=(1,))
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize(
    'key',
    ['', ':', 'a', 'xesam:', ':x', 'a b', 'x\ny', '‮', 'é' * 300, '%s%n'],
    ids=lambda k: k[:8].encode('unicode_escape').decode() or 'empty',
)
async def test_weird_key_names(key, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {
        key: Variant('s', 'val'),
        'xesam:title': Variant('s', 'T'),
    }
    await mpris.ping()

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    assert 'val' in result.stdout

    result = await run(playerctl, "-p evil metadata --format '{{title}}'")
    assert_sane(result, allowed=(0,))
    assert result.stdout == 'T'


async def test_duplicate_looking_keys(playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {
        'xesam:title': Variant('s', 'one'),
        'xesam:Title': Variant('s', 'two'),
        'XESAM:TITLE': Variant('s', 'three'),
    }
    await mpris.ping()

    result = await run(playerctl, '-p evil metadata')
    assert_sane(result, allowed=(0,))
    assert sorted(line.split()[-1] for line in result.stdout.splitlines()) == [
        'one',
        'three',
        'two',
    ]

"""US-7.10: As a bar author, I want `--format` to stay safe when the player
feeds it hostile data: escaped output must be valid JSON / Pango markup for
any title, and absurd numbers or unknown statuses must never crash the
formatter or print GLib noise."""

import json
import math
import re

import pytest
from dbus_next import Variant

from ..helpers.evil_mpris import (
    HUGE,
    INT64_MAX,
    INT64_MIN,
    NASTY_STRINGS,
    PLAYER_LIES,
    assert_sane,
    metadata_with,
    run,
    tamper,
)

TEXTS = {**NASTY_STRINGS, 'huge': 'h' * HUGE, 'empty': ''}

_ENTITY = re.compile(r'&(?:amp|lt|gt|quot|apos);|&#x[0-9a-fA-F]+;|&#[0-9]+;')


def fmt(template):
    return "metadata --format '" + template.replace("'", r"\'") + "'"


async def titled(mpris_factory, text, key='xesam:title'):
    [mpris] = await mpris_factory('evil')
    value = (
        Variant('as', [text]) if key == 'xesam:artist' else Variant('s', text)
    )
    mpris.metadata = metadata_with(**{key.replace(':', '__'): value})
    await mpris.ping()
    return mpris


@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_json_escape_output_is_a_json_string(
    text, playerctl, mpris_factory
):
    await titled(mpris_factory, text)

    result = await run(playerctl, '-p evil ' + fmt('{{json_escape(title)}}'))

    assert_sane(result, allowed=(0,))
    assert json.loads(f'"{result.stdout}"') == text


@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_json_escape_artist(text, playerctl, mpris_factory):
    await titled(mpris_factory, text, 'xesam:artist')

    result = await run(playerctl, '-p evil ' + fmt('{{json_escape(artist)}}'))

    assert_sane(result, allowed=(0,))
    assert json.loads(f'"{result.stdout}"') == text


@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_json_escape_inside_a_json_document(
    text, playerctl, mpris_factory
):
    await titled(mpris_factory, text)

    result = await run(
        playerctl,
        '-p evil '
        + fmt('{"title": "{{json_escape(title)}}", "n": {{volume}}}'),
    )

    assert_sane(result, allowed=(0,))
    assert json.loads(result.stdout)['title'] == text


@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_markup_escape_output_is_pango_safe(
    text, playerctl, mpris_factory
):
    await titled(mpris_factory, text)

    result = await run(playerctl, '-p evil ' + fmt('{{markup_escape(title)}}'))

    assert_sane(result, allowed=(0,))
    leftover = _ENTITY.sub('', result.stdout)
    assert '<' not in leftover
    assert '>' not in leftover
    assert '&' not in leftover


@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_markup_escape_is_lossless(text, playerctl, mpris_factory):
    await titled(mpris_factory, text)

    result = await run(playerctl, '-p evil ' + fmt('{{markup_escape(title)}}'))

    named = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}

    def decode(m):
        body = m.group(0)[1:-1]
        if body.startswith('#x'):
            return chr(int(body[2:], 16))
        if body.startswith('#'):
            return chr(int(body[1:]))
        return named[body]

    assert_sane(result, allowed=(0,))
    assert _ENTITY.sub(decode, result.stdout).strip() == text.strip()


@pytest.mark.parametrize(
    'template',
    [
        '{{lc(title)}}',
        '{{uc(title)}}',
        '{{trunc(title, 0)}}',
        '{{trunc(title, 1)}}',
        '{{trunc(title, 5)}}',
        '{{trunc(title, 1000000)}}',
        '{{pad(title, 3)}}',
        '{{pad(title, -50)}}',
        '{{replace(title, "a", "bb")}}',
        '{{replace(title, "", "x")}}',
        '{{join(artist, "|")}}',
        '{{uri_decode(title)}}',
        '{{default(title, "none")}}',
        '[{{artist}}] {{title}} {{album}}',
    ],
)
@pytest.mark.parametrize('text', TEXTS.values(), ids=TEXTS)
async def test_helpers_on_nasty_text(template, text, playerctl, mpris_factory):
    await titled(mpris_factory, text)

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)
    assert result.returncode in (0, 1)


BUG_E5 = pytest.mark.xfail(
    strict=True,
    reason='BUG-E5: uri_decode of an escape that is not valid UTF-8 '
    '(%ff, %c0%af) trips GLib-CRITICAL g_variant_new_string',
)


@pytest.mark.parametrize(
    'text',
    [
        '%00',
        '%',
        '%%',
        '%zz',
        '%4',
        '%25',
        '%41%00B',
        '%e2%82%ac',
        pytest.param('%ff', marks=BUG_E5),
        pytest.param('%ff%fe', marks=BUG_E5),
        pytest.param('%c0%af', marks=BUG_E5),
        pytest.param('%e2%82', marks=BUG_E5),
    ],
)
async def test_uri_decode_hostile_escapes(text, playerctl, mpris_factory):
    await titled(mpris_factory, text)

    result = await run(playerctl, '-p evil ' + fmt('{{uri_decode(title)}}'))

    assert_sane(result)


# --- statuses and numbers ----------------------------------------------

STATUS_TEMPLATES = [
    '{{status}}',
    '{{uc(status)}}',
    '{{lc(status)}}',
    '{{emoji(status)}}',
    '{{emoji(loop)}}',
    '{{emoji(shuffle)}}',
    '{{emoji(volume)}}',
    '{{loop}} {{shuffle}} {{volume}}',
    '{{default(status, "?")}}',
]


@pytest.mark.parametrize('template', STATUS_TEMPLATES)
@pytest.mark.parametrize(
    ('prop', 'value'),
    [
        (p, v)
        for i, p, v in PLAYER_LIES
        if p in ('PlaybackStatus', 'LoopStatus', 'Shuffle', 'Volume')
    ],
    ids=[
        i
        for i, p, v in PLAYER_LIES
        if p in ('PlaybackStatus', 'LoopStatus', 'Shuffle', 'Volume')
    ],
)
async def test_hostile_status_in_format(
    template, prop, value, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil', prepare=tamper({prop: value}))
    await mpris.set_artist_title('a', 't')

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)


NUMBER_TEMPLATES = [
    '{{position}}',
    '{{duration(position)}}',
    '{{duration(position / 2)}}',
    '{{duration(mpris:length - position)}}',
    '{{position * position}}',
    '{{position + position}}',
    '{{-position}}',
    '{{round(position)}}',
    '{{int(position)}}',
    '{{position / 0}}',
    '{{position / (position - position)}}',
    '{{trunc(title, position)}}',
    '{{pad(title, position)}}',
]


@pytest.mark.parametrize('template', NUMBER_TEMPLATES)
@pytest.mark.parametrize(
    'position',
    [0, -1, INT64_MAX, INT64_MIN, 2**62, -(2**62), 10**15],
)
async def test_extreme_position_in_format(
    template, position, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil')
    mpris.playback_status = 'Paused'
    mpris.metadata = metadata_with(mpris__length=Variant('x', 1000))
    await mpris.emit_properties(position=position)

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)


VOLUME_TEMPLATES = [
    '{{volume}}',
    '{{round(volume * 100)}}',
    '{{int(volume * 100)}}',
    '{{emoji(volume)}}',
    '{{duration(volume)}}',
    '{{trunc(title, volume)}}',
    '{{pad(title, volume)}}',
    '{{volume / 0}}',
    '{{volume * volume}}',
]


@pytest.mark.parametrize('template', VOLUME_TEMPLATES)
@pytest.mark.parametrize(
    'volume',
    [
        -1.0,
        0.0,
        -0.0,
        1e308,
        -1e308,
        5e-324,
        math.nan,
        math.inf,
        -math.inf,
        2.5,
    ],
    ids=repr,
)
async def test_extreme_volume_in_format(
    template, volume, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = metadata_with()
    await mpris.emit_properties(volume=volume)

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)


@pytest.mark.parametrize(
    'value',
    [INT64_MAX, INT64_MIN, -1, 0, 2**62, -(2**62)],
)
@pytest.mark.parametrize(
    'template',
    [
        '{{duration(mpris:length)}}',
        '{{duration(-mpris:length)}}',
        '{{mpris:length * mpris:length}}',
        '{{mpris:length + mpris:length}}',
        '{{mpris:length - -mpris:length}}',
        '{{mpris:length / -1}}',
        '{{round(mpris:length)}}',
        '{{trunc(title, mpris:length)}}',
        '{{pad(title, mpris:length)}}',
    ],
)
async def test_extreme_length_arithmetic(
    template, value, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = metadata_with(mpris__length=Variant('x', value))
    await mpris.ping()

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)


@pytest.mark.parametrize(
    'template',
    [
        '{{title}}',
        '{{artist}}',
        '{{album}}',
        '{{mpris:length}}',
        '{{xesam:nonexistent}}',
        '{{default(title, "-")}}',
        '{{default(xesam:nonexistent, "-")}}',
        '{{duration(mpris:length)}}',
        '{{trunc(title, 3)}}',
        '{{lc(album)}}',
        '{{markup_escape(title)}}',
        '{{json_escape(title)}}',
        '{{join(artist, ",")}}',
    ],
)
async def test_empty_and_missing_metadata_in_format(
    template, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil')
    mpris.metadata = {}
    await mpris.ping()

    result = await run(playerctl, '-p evil ' + fmt(template))

    assert_sane(result)


def _lie_params():
    for i, p, _ in PLAYER_LIES:
        if p == 'Metadata':
            yield pytest.param(i, marks=BUG_E2)
        elif p in ('Position', 'Volume'):
            yield i


BUG_E2 = pytest.mark.xfail(
    strict=True,
    reason='BUG-E2: non-dict Metadata aborts in g_variant_lookup_value()',
)


@pytest.mark.parametrize('lie', list(_lie_params()))
async def test_every_template_variable_survives_a_lie(
    lie, playerctl, mpris_factory
):
    prop, value = next((p, v) for i, p, v in PLAYER_LIES if i == lie)
    [mpris] = await mpris_factory('evil', prepare=tamper({prop: value}))
    await mpris.set_artist_title('a', 't')

    result = await run(
        playerctl,
        '-p evil '
        + fmt(
            '{{playerName}}|{{playerInstance}}|{{status}}|{{loop}}|'
            '{{shuffle}}|{{volume}}|{{position}}|{{artist}}|{{title}}|'
            '{{album}}|{{mpris:length}}'
        ),
    )

    assert_sane(result)

"""US-7.4: As a bar author, I want the helpers `lc`, `uc`, `markup_escape`,
`default`, `emoji`, `trunc`, `json_escape`, `round`, `int`, `replace`, `join`, `pad`,
`uri_decode`."""

import pytest
from dbus_next import Variant

from ..helpers.format import ARTIST, TITLE


async def test_case_helpers(metadata_test):
    metadata_test.add('{{lc(artist)}}', ARTIST.lower())
    metadata_test.add('{{uc(title)}}', TITLE.upper())
    metadata_test.add('{{uc(lc(title))}}', TITLE.upper())

    await metadata_test.run()


async def test_markup_escape(metadata_test):
    metadata_test.add('{{markup_escape(xesam:escapeme)}}', '&lt;hi&gt;')

    await metadata_test.run()


async def test_default(metadata_test):
    metadata_test.add('{{default(xesam:missing, artist)}}', ARTIST)
    metadata_test.add('{{default(title, artist)}}', TITLE)
    metadata_test.add('{{default("", "ok")}}', 'ok')
    metadata_test.add('{{default("ok", "not")}}', 'ok')

    await metadata_test.run()


async def test_trunc(metadata_test):
    metadata_test.add('{{trunc(title, 10)}}', TITLE)
    metadata_test.add('{{trunc(title, 5)}}', f'{TITLE[:5]}…')
    metadata_test.add('{{trunc("", 0)}}', '')
    metadata_test.add('{{trunc("", 10)}}', '')

    await metadata_test.run()


async def test_emoji(playerctl, mpris_factory):
    [mpris] = await mpris_factory('emoji-format-test')
    mpris.metadata = {'mpris:length': Variant('x', 100000)}
    await mpris.ping()

    status_emoji_cmd = "metadata --format '{{emoji(status)}}'"

    mpris.playback_status = 'Playing'
    cmd = await playerctl.run(status_emoji_cmd)
    assert cmd.stdout == '▶️', cmd.stderr

    mpris.playback_status = 'Paused'
    cmd = await playerctl.run(status_emoji_cmd)
    assert cmd.stdout == '⏸️', cmd.stderr

    mpris.playback_status = 'Stopped'
    cmd = await playerctl.run(status_emoji_cmd)
    assert cmd.stdout == '⏹️', cmd.stderr

    volume_emoji_cmd = "metadata --format '{{emoji(volume)}}'"
    mpris.volume = 0.0
    cmd = await playerctl.run(volume_emoji_cmd)
    assert cmd.stdout == '🔈', cmd.stderr

    mpris.volume = 0.5
    cmd = await playerctl.run(volume_emoji_cmd)
    assert cmd.stdout == '🔉', cmd.stderr

    mpris.volume = 1.0
    cmd = await playerctl.run(volume_emoji_cmd)
    assert cmd.stdout == '🔊', cmd.stderr


async def test_helpers_on_missing_value_are_empty(metadata_test):
    for helper in ('lc', 'uc', 'markup_escape', 'emoji'):
        metadata_test.add('[{{' + helper + '(xesam:missing)}}]', '[]')
    metadata_test.add('[{{trunc(xesam:missing, 3)}}]', '[]')
    metadata_test.add('[{{trunc(title, xesam:missing)}}]', '[]')
    metadata_test.add('[{{default(xesam:missing, xesam:missing)}}]', '[]')

    await metadata_test.run()


async def test_case_helpers_on_non_strings(metadata_test):
    metadata_test.add('{{uc(mpris:length)}}', '100000')
    metadata_test.add('{{lc(mpris:length)}}', '100000')
    metadata_test.add('{{uc(1.5)}}', '1.5')
    metadata_test.add('{{uc(shuffle)}}', 'FALSE')
    metadata_test.add('{{lc(shuffle)}}', 'false')

    await metadata_test.run()


async def test_markup_escape_wrong_argument_count(metadata_test):
    metadata_test.add('{{markup_escape()}}', '', ret=1)
    metadata_test.add('{{markup_escape(title, title)}}', '', ret=1)

    await metadata_test.run()


async def test_markup_escape_special_characters(metadata_test):
    metadata_test.add(
        '{{markup_escape("a & b < c > d")}}', 'a &amp; b &lt; c &gt; d'
    )

    await metadata_test.run()


async def test_trunc_bad_length(metadata_test):
    # the length must be a number
    metadata_test.add('{{trunc(title, "5")}}', '', ret=1)
    metadata_test.add('{{trunc(title, title)}}', '', ret=1)

    await metadata_test.run()


async def test_trunc_zero_and_exact_length(metadata_test):
    metadata_test.add('{{trunc(title, 0)}}', '…')
    metadata_test.add('{{trunc(title, 7)}}', TITLE)
    metadata_test.add('{{trunc(title, 6)}}', f'{TITLE[:6]}…')

    await metadata_test.run()


async def test_emoji_passthrough_for_other_values(metadata_test):
    metadata_test.add('{{emoji(title)}}', TITLE)
    metadata_test.add('{{emoji(mpris:length)}}', '100000')
    metadata_test.add('{{emoji(artist)}}', ARTIST)

    await metadata_test.run()


async def test_emoji_loop_of_a_default_player(metadata_test):
    # the loop status of the test player is None
    metadata_test.add('{{emoji(loop)}}', '➡️')

    await metadata_test.run()


@pytest.mark.parametrize(
    ('volume', 'expected'),
    [
        (0.3332, '🔈'),
        (0.3334, '🔉'),
        (0.6665, '🔉'),
        (0.6667, '🔊'),
        (2.0, '🔊'),
    ],
)
async def test_emoji_volume_thresholds(
    volume, expected, playerctl, format_player
):
    format_player.volume = volume
    cmd = await playerctl.run("metadata --format '{{emoji(volume)}}'")
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == expected


async def test_default_with_non_string_first_argument(metadata_test):
    # only an empty *string* counts as unset; numbers are kept
    metadata_test.add('{{default(0, "x")}}', '0.0')
    metadata_test.add('{{default(mpris:length, "x")}}', '100000')
    metadata_test.add('{{default(shuffle, "x")}}', 'false')

    await metadata_test.run()


async def test_default_skips_a_list_with_an_empty_string(
    playerctl, mpris_factory
):
    # 5mdt/playerctl#32: podcasts have an empty artist and the name in album
    [mpris] = await mpris_factory('podcast')
    mpris.metadata = {
        'xesam:artist': Variant('as', ['']),
        'xesam:album': Variant('s', 'Podcast'),
    }
    await mpris.ping()

    result = await playerctl.run(
        "metadata --format '{{default(artist, album)}}'"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Podcast'


async def test_trunc_accepts_an_integer_length(metadata_test, format_player):
    format_player.playback_status = 'Paused'
    format_player.position = 5000000
    await format_player.ping()
    # position is an int64, not a number literal
    metadata_test.add('{{trunc(title, position / 1000000)}}', f'{TITLE[:5]}…')

    await metadata_test.run()


async def test_emoji_loop_and_shuffle(playerctl, mpris_factory):
    [mpris] = await mpris_factory('emoji-loop-shuffle-test')
    mpris.metadata = {'mpris:length': Variant('x', 100000)}
    await mpris.ping()

    for loop, emoji in (('Track', '🔂'), ('Playlist', '🔁'), ('None', '➡️')):
        mpris.loop_status = loop
        cmd = await playerctl.run("metadata --format '{{emoji(loop)}}'")
        assert cmd.stdout == emoji, cmd.stderr

    for shuffle, emoji in ((True, '🔀'), (False, '➡️')):
        mpris.shuffle = shuffle
        cmd = await playerctl.run("metadata --format '{{emoji(shuffle)}}'")
        assert cmd.stdout == emoji, cmd.stderr


async def test_round_and_int(metadata_test):
    metadata_test.add('{{round(volume * 100)}}', '200')
    metadata_test.add('{{round(2.5)}}', '3')
    metadata_test.add('{{round(-2.5)}}', '-3')
    metadata_test.add('{{round(2.4)}}', '2')
    metadata_test.add('{{int(2.9)}}', '2')
    metadata_test.add('{{int(-2.9)}}', '-2')
    metadata_test.add('{{round(xesam:missing)}}', '')

    await metadata_test.run()


async def test_round_rejects_text(metadata_test):
    metadata_test.add('{{round(title)}}', '', ret=1)
    metadata_test.add('{{int(title)}}', '', ret=1)

    await metadata_test.run()


async def test_replace(metadata_test):
    metadata_test.add('{{replace(title, " ", "_")}}', TITLE.replace(' ', '_'))
    metadata_test.add('{{replace(title, "zzz", "_")}}', TITLE)
    metadata_test.add('{{replace(title, "", "_")}}', TITLE)
    metadata_test.add('{{replace(xesam:missing, "a", "b")}}', '')

    await metadata_test.run()


async def test_join(metadata_test):
    metadata_test.add('{{join(artist, " & ")}}', ARTIST)
    metadata_test.add('{{join(title, ", ")}}', TITLE)
    metadata_test.add('{{join(xesam:missing, ", ")}}', '')

    await metadata_test.run()


async def test_pad(metadata_test):
    # the test helper strips the output, so mark both ends
    metadata_test.add('|{{pad("ab", 5)}}|', '|ab   |')
    metadata_test.add('|{{pad("ab", -5)}}|', '|   ab|')
    metadata_test.add('|{{pad("abcdef", 3)}}|', '|abcdef|')
    metadata_test.add('|{{pad(trunc(title, 3), 6)}}|', f'|{TITLE[:3]}…  |')

    await metadata_test.run()


async def test_pad_bad_width(metadata_test):
    metadata_test.add('{{pad("ab", "5")}}', '', ret=1)

    await metadata_test.run()


async def test_uri_decode(metadata_test):
    metadata_test.add('{{uri_decode("a%20b%26c")}}', 'a b&c')
    metadata_test.add('{{uri_decode("plain")}}', 'plain')
    metadata_test.add('{{uri_decode("bad%zz")}}', 'bad%zz')

    await metadata_test.run()


async def test_json_escape(metadata_test):
    metadata_test.add('{{json_escape(title)}}', TITLE)
    metadata_test.add('{{json_escape(xesam:escapeme)}}', '<hi>')
    metadata_test.add('{{json_escape(xesam:missing)}}', '')
    metadata_test.add(
        '{"title": "{{json_escape(title)}}"}', '{"title": "%s"}' % TITLE
    )

    await metadata_test.run()

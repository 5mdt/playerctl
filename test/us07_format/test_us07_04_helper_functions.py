"""US-7.4: As a bar author, I want the helpers `lc`, `uc`, `markup_escape`,
`default`, `emoji`, `trunc`."""

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
    metadata_test.add('{{trunc(title, mpris:length)}}', '', ret=1)

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


async def test_emoji_status_unknown_value_passthrough(metadata_test):
    # `status` is always a valid playback status, so use the loop string
    metadata_test.add('{{emoji(loop)}}', 'None')

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

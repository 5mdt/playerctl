"""US-7.4: As a bar author, I want the helpers `lc`, `uc`, `markup_escape`,
`default`, `emoji`, `trunc`."""

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

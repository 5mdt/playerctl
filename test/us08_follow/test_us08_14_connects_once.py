"""US-8.14: As a bar author, I want one line per change when the format of a
command uses that command's own property."""

import pytest

from ..helpers.follow import expect_no_line, next_line


@pytest.mark.parametrize(
    'command, prop, first, changed, expected',
    [
        ('volume', 'volume', 0.5, 0.25, '0.25'),
        ('status', 'playback_status', 'Playing', 'Paused', 'Paused'),
    ],
)
async def test_own_property_in_format_renders_once_per_change(
    command, prop, first, changed, expected, playerctl, mpris_factory
):
    # audit: playerctl-cli.c:1296 `&cmd != player_cmd` compares a stack copy,
    # so the follow signal was connected twice
    [mpris] = await mpris_factory('test1')
    await mpris.set_artist_title('artist', 'title')
    await mpris.emit_properties(**{prop: first})
    key = command
    proc = await playerctl.start(
        f'{command} --format "{{{{{key}}}}}" --follow'
    )
    await next_line(proc)

    await mpris.emit_properties(**{prop: changed})

    assert await next_line(proc) == expected
    await expect_no_line(proc)

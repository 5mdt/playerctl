"""US-8.1: As a bar author, I want `-F` to print a new line whenever the
queried property changes."""

import pytest

from ..helpers.follow import expect_no_line, follow_cmd, next_line


async def test_follow_metadata_changes(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    proc = await playerctl.start(follow_cmd())

    await mpris1.set_artist_title('artist', 'title')
    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    await mpris1.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris1.clear_metadata()
    line = await proc.queue.get()
    assert line == 'test1:  -'

    await mpris1.set_artist_title('artist3', 'title3')
    line = await proc.queue.get()
    assert line == 'test1: artist3 - title3'


# command, initial player state, then (property changes, expected line)
PROPERTY_CASES = [
    pytest.param(
        'status',
        {},
        [
            ({'playback_status': 'Paused'}, 'Paused'),
            ({'playback_status': 'Stopped'}, 'Stopped'),
            ({'playback_status': 'Playing'}, 'Playing'),
        ],
        id='status',
    ),
    pytest.param(
        'volume',
        {},
        [({'volume': 0.5}, '0.500000'), ({'volume': 0.25}, '0.250000')],
        id='volume',
    ),
    pytest.param(
        'loop',
        {},
        [
            ({'loop_status': 'Track'}, 'Track'),
            ({'loop_status': 'Playlist'}, 'Playlist'),
        ],
        id='loop',
    ),
    pytest.param(
        'shuffle',
        {},
        [({'shuffle': True}, 'On'), ({'shuffle': False}, 'Off')],
        id='shuffle',
    ),
]


@pytest.mark.parametrize('command,initial,changes', PROPERTY_CASES)
async def test_follow_property_changes(
    command, initial, changes, playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    proc = await playerctl.start(f'{command} --follow')
    # initial value is printed on startup
    assert await next_line(proc)

    for props, expected in changes:
        await mpris1.emit_properties(**props)
        assert await next_line(proc) == expected
    await expect_no_line(proc)


async def test_follow_position_changes(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Paused'  # a playing position advances
    mpris1.position = 0
    proc = await playerctl.start('position --follow')
    assert await next_line(proc) == '0.000000'

    mpris1.seeked_value = 5000000
    mpris1.Seeked()
    await mpris1.ping()
    assert await next_line(proc) == '5.000000'

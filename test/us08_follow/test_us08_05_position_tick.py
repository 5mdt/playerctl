"""US-8.5: As a bar author, I want a format that uses `position` to refresh
every second."""

from ..helpers.follow import expect_no_line, lines_until, next_line

POSITION_FORMAT = '--format "{{duration(position)}}"'


async def test_position_refreshes_every_second(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Playing'  # a playing position advances
    mpris1.position = 0
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(f'metadata {POSITION_FORMAT} --follow')

    assert await next_line(proc) == '0:00'
    # no property changes: only the one-second tick can print this line
    assert await next_line(proc, timeout=2.5) == '0:01'


async def test_paused_position_does_not_repeat(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Paused'
    mpris1.position = 0
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(f'metadata {POSITION_FORMAT} --follow')

    assert await next_line(proc) == '0:00'
    # the tick fires but the output is unchanged, so it is suppressed
    await expect_no_line(proc, wait=2.2)


async def test_no_tick_without_position(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start('metadata --format "{{title}}" --follow')

    assert await next_line(proc) == 'title'
    await expect_no_line(proc, wait=1.5)


async def test_tick_stops_and_resumes_with_playback_status(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Playing'
    mpris1.position = 0
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        'metadata --format "{{status}} {{duration(position)}}" --follow'
    )
    assert await next_line(proc) == 'Playing 0:00'

    await mpris1.emit_properties(playback_status='Paused')
    assert await next_line(proc) == 'Paused 0:00'
    # while paused the position does not move, so the tick prints nothing
    await expect_no_line(proc, wait=1.5)

    await mpris1.emit_properties(playback_status='Playing')
    assert (await next_line(proc)).startswith('Playing 0:0')


async def test_track_change_without_seeked_resets_position(
    playerctl, mpris_factory
):
    # 5mdt/playerctl#57: Strawberry and Finamp send no Seeked when the track
    # changes, so the line for the new track showed the old track's position
    [mpris] = await mpris_factory('test1')
    mpris.playback_status = 'Playing'
    mpris.position = 30000000
    await mpris.set_artist_title('artist', 'one')
    proc = await playerctl.start(
        'metadata --format "{{title}} {{duration(position)}}" --follow'
    )
    assert (await next_line(proc)).startswith('one 0:30')

    mpris.position = 0  # the player's own position restarts, silently
    await mpris.set_artist_title('artist', 'two')

    await lines_until(proc, 'two 0:00', limit=3)

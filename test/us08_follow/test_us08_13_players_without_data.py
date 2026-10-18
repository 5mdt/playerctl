"""US-8.13: As a bar author, I want follow mode to handle players that have
no metadata yet, and to re-render for players that appear after it started."""

from ..helpers.follow import expect_no_line, follow_cmd, lines_until, next_line


async def test_player_without_metadata_at_start(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    proc = await playerctl.start(follow_cmd())
    await expect_no_line(proc)
    assert proc.running()

    await mpris1.set_artist_title('artist', 'title')
    assert await next_line(proc) == 'test1: artist - title'


async def test_player_without_metadata_appearing_later(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist1 - title'

    # the new player is asked first but has nothing to show: test1 stays
    [mpris2] = await mpris_factory('test2')
    await expect_no_line(proc)
    assert proc.running()

    await mpris2.set_artist_title('artist2', 'title')
    assert await next_line(proc) == 'test2: artist2 - title'


async def test_player_with_empty_metadata_is_skipped(playerctl, mpris_factory):
    [mpris1, _mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(follow_cmd('test2,test1'))

    assert await next_line(proc) == 'test1: artist1 - title'


async def test_metadata_template_keys_for_player_without_metadata(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    proc = await playerctl.start(
        'metadata --format "{{status}} {{volume}} {{title}}" --follow'
    )
    await expect_no_line(proc)

    # properties used by the template do not matter until there is metadata
    await mpris1.emit_properties(volume=0.5)
    await expect_no_line(proc)

    await mpris1.set_artist_title('artist', 'title')
    assert await next_line(proc) == 'Playing 0.5 title'


async def test_metadata_cleared_prints_blank_fields(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist - title'

    # only a track id is left, so the template renders with empty fields
    await mpris1.clear_metadata()
    assert await next_line(proc) == 'test1:  -'

    await mpris1.set_artist_title('artist', 'back')
    assert await next_line(proc) == 'test1: artist - back'


async def test_appearing_player_rerenders_on_used_properties(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(
        'metadata --format "{{playerInstance}} {{status}} {{volume}}'
        ' {{loop}} {{shuffle}} {{title}}" --follow'
    )
    assert await next_line(proc) == 'test1 Playing 1.0 None false title'

    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'two')
    await lines_until(proc, 'test2 Playing 1.0 None false two')

    # the player that appeared later follows the same signals as the first
    await mpris2.emit_properties(volume=0.5)
    assert await next_line(proc) == 'test2 Playing 0.5 None false two'
    await mpris2.emit_properties(playback_status='Paused')
    assert await next_line(proc) == 'test2 Paused 0.5 None false two'
    await mpris2.emit_properties(loop_status='Track')
    assert await next_line(proc) == 'test2 Paused 0.5 Track false two'
    await mpris2.emit_properties(shuffle=True)
    assert await next_line(proc) == 'test2 Paused 0.5 Track true two'


async def test_appearing_player_ticks_for_position(playerctl, mpris_factory):
    proc = await playerctl.start(
        'metadata --format "{{duration(position)}} {{title}}" --follow'
    )
    await expect_no_line(proc)

    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Playing'
    await mpris1.set_artist_title('artist', 'title')
    assert await next_line(proc) == '0:00 title'
    assert await next_line(proc, timeout=2.5) == '0:01 title'

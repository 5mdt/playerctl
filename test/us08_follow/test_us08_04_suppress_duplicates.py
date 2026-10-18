"""US-8.4: As a bar author, I want duplicate lines suppressed."""

from ..helpers.follow import expect_no_line, follow_cmd, next_line


async def test_same_metadata_twice_prints_once(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())

    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    # setting metadata the same twice doesn't print
    await mpris1.set_artist_title('artist', 'title')
    assert proc.queue.empty()


async def test_identical_output_printed_once(playerctl, mpris_factory):
    '''Two property changes that render the same line print only once.'''
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    # the format only uses artist, so a title change renders the same line
    proc = await playerctl.start('metadata --format "{{artist}}" --follow')
    assert await next_line(proc) == 'artist'

    await mpris1.set_artist_title('artist', 'other title')
    await expect_no_line(proc)

    await mpris1.set_artist_title('artist2', 'other title')
    assert await next_line(proc) == 'artist2'
    await expect_no_line(proc)

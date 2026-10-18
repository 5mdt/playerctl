"""US-8.1: As a bar author, I want `-F` to print a new line whenever the
queried property changes."""

from ..helpers.follow import follow_cmd


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

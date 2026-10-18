"""US-8.4: As a bar author, I want duplicate lines suppressed."""

from ..helpers.follow import follow_cmd


async def test_same_metadata_twice_prints_once(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())

    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    # setting metadata the same twice doesn't print
    await mpris1.set_artist_title('artist', 'title')
    assert proc.queue.empty()

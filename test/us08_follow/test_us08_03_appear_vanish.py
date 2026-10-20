"""US-8.3: As a bar author, I want players appearing and disappearing to be
handled, with an empty line when none are left."""

from ..helpers.follow import expect_no_line, follow_cmd, lines_until, next_line


async def test_follow_last_player_vanishes(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())

    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    await mpris1.disconnect()
    line = await proc.queue.get()
    assert line == ''


async def test_follow_falls_back_to_next_player(playerctl, follow_players):
    [mpris1, mpris2, mpris3, _] = follow_players
    await mpris2.set_artist_title('artist2', 'title2')
    await mpris1.set_artist_title('artist2', 'title2')
    await mpris3.set_artist_title('artist', 'title')

    proc = await playerctl.start(follow_cmd('test3,test2,test1'))

    line = await proc.queue.get()
    assert line == 'test3: artist - title'

    # when player3 disconnects, it should show the next one
    await mpris3.disconnect()
    await mpris2.ping()
    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    # same for player2
    await mpris2.disconnect()
    await mpris1.ping()
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris1.disconnect()
    line = await proc.queue.get()
    assert line == ''


async def test_follow_player_appears_later(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist - title'

    # a newly appearing player is picked up and followed
    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title2')
    await lines_until(proc, 'test2: artist2 - title2')

    await mpris2.set_artist_title('artist3', 'title3')
    assert await next_line(proc) == 'test2: artist3 - title3'


async def test_follow_with_no_players_at_start(playerctl, mpris_factory):
    proc = await playerctl.start(follow_cmd())
    # nothing to print yet, and it keeps running
    await expect_no_line(proc)
    assert proc.running()

    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    await lines_until(proc, 'test1: artist - title')


async def test_follow_player_returns_after_vanishing(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist - title'

    await mpris1.disconnect()
    assert await next_line(proc) == ''

    [mpris1b] = await mpris_factory('test1')
    await mpris1b.set_artist_title('artist', 'back')
    await lines_until(proc, 'test1: artist - back')

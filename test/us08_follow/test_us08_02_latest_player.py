"""US-8.2: As a bar author, I want follow mode to track the player that
updated most recently."""

from ..helpers.follow import follow_cmd


async def test_follow_respects_selection_priority(playerctl, follow_players):
    [mpris1, mpris2, mpris3, mpris4] = follow_players
    await mpris1.set_artist_title('artist', 'title')

    proc = await playerctl.start(follow_cmd('test3,test2,test1'))

    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    # player4 is ignored
    await mpris4.set_artist_title('artist', 'title')
    assert proc.queue.empty()

    await mpris2.set_artist_title('artist', 'title')
    line = await proc.queue.get()
    assert line == 'test2: artist - title'

    # player2 takes precedence
    await mpris1.set_artist_title('artist2', 'title2')
    assert proc.queue.empty()

    await mpris3.set_artist_title('artist', 'title')
    line = await proc.queue.get()
    assert line == 'test3: artist - title'

    # player 3 takes precedence
    await mpris2.set_artist_title('artist2', 'title2')
    assert proc.queue.empty()

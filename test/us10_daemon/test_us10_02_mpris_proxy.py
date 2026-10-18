"""US-10.2: As a user, I want playerctld to appear as an MPRIS player that
forwards calls, properties and signals to the active player."""

from ..helpers.follow import follow_cmd


async def test_proxies_metadata_of_the_active_player(
    playerctl, playerctld, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    proc = await playerctl.start(follow_cmd('playerctld'))

    await mpris1.set_artist_title('artist1', 'title1')
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    [mpris3] = await mpris_factory('player3')
    await mpris3.set_artist_title('artist3', 'title3')
    line = await proc.queue.get()

    if line == '':
        # the line might be blank here because of the test setup
        line = await proc.queue.get()

    assert line == 'playerctld: artist3 - title3', proc.queue

    await mpris1.set_artist_title('artist4', 'title4')
    line = await proc.queue.get()
    assert line == 'playerctld: artist4 - title4', proc.queue

    await mpris1.set_artist_title('artist5', 'title5')
    line = await proc.queue.get()
    assert line == 'playerctld: artist5 - title5', proc.queue

    await mpris1.disconnect()
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue

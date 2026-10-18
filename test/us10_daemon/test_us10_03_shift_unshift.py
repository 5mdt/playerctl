"""US-10.3: As a user, I want `playerctld shift` / `unshift` to cycle the
active player, with exit code 1 when there is none."""

from ..helpers.daemon import playerctld_shift
from ..helpers.follow import follow_cmd


async def test_shift_and_unshift_cycle_players(
    bus_address, playerctl, playerctld, mpris_factory
):
    [mpris1, mpris2, mpris3] = await mpris_factory(
        'player1', 'player2', 'player3'
    )
    proc = await playerctl.start(follow_cmd('playerctld'))

    await mpris1.set_artist_title('artist1', 'title1')
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    await mpris3.set_artist_title('artist3', 'title3')
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue

    code = await playerctld_shift(bus_address)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    code = await playerctld_shift(bus_address)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue


async def test_shift_without_players_fails(
    bus_address, playerctl, playerctld, mpris_factory
):
    await playerctl.start(follow_cmd('playerctld'))

    code = await playerctld_shift(bus_address)
    assert code == 1

    [mpris1] = await mpris_factory('player1')
    code = await playerctld_shift(bus_address)
    assert code == 0

    await mpris1.disconnect()
    code = await playerctld_shift(bus_address)
    assert code == 1

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 1

    [mpris1] = await mpris_factory('player1')
    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0

    await mpris1.disconnect()
    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 1

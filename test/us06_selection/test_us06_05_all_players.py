"""US-6.5: As a user, I want `-a/--all-players` to send the command to every
matching player."""

import asyncio

import pytest

from ..helpers.follow import follow_cmd
from ..helpers.selection import SELECTIONS


@pytest.mark.parametrize(
    ('selection', 'expected'),
    SELECTIONS.items(),
    ids=['-'.join(s) for s in SELECTIONS],
)
async def test_every_matching_player_in_priority_order(
    selection, expected, selection_players, select_many
):
    assert await select_many(*selection) == expected


async def test_follow_all_players(playerctl, mpris_factory):
    [mpris1, mpris2, mpris3, mpris4] = await mpris_factory(
        'test1', 'test2', 'test3', 'test4'
    )

    await asyncio.gather(
        *[
            mpris.set_artist_title('artist', 'title')
            for mpris in [mpris1, mpris2, mpris3, mpris4]
        ]
    )

    proc = await playerctl.start(
        follow_cmd('test3,test2,test1', all_players=True)
    )

    # player4 is ignored
    await mpris4.set_artist_title('artist', 'title')
    assert proc.queue.empty()

    # no precedence, just whoever changes metadata last
    await mpris1.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris3.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test3: artist2 - title2'

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris1.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris1.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris2.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == 'test3: artist2 - title2'

    await mpris3.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == ''

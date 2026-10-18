"""US-6.3: As a user, I want a `%any` placeholder in the `-p` list to rank
players before and after "everything else"."""

import pytest

from ..helpers.follow import follow_cmd
from ..helpers.selection import ANY_SELECTIONS


@pytest.mark.parametrize(
    ('selection', 'expected'),
    ANY_SELECTIONS.items(),
    ids=['-'.join(s) for s in ANY_SELECTIONS],
)
async def test_any_ranks_unlisted_players(
    selection, expected, selection_players, select
):
    assert await select(*selection) == expected[0], (selection, expected)


async def test_follow_with_any(playerctl, mpris_factory):
    [mpris1, mpris2, mpris3, mpris4] = await mpris_factory(
        'test1', 'test2', 'test3', 'test4'
    )
    proc = await playerctl.start(follow_cmd('test3,%any,test1'))

    # test3 takes first precedence
    await mpris3.set_artist_title('artist', 'title')
    line = await proc.queue.get()
    assert line == 'test3: artist - title', proc.queue

    await mpris2.set_artist_title('artist', 'title')
    assert proc.queue.empty()

    await mpris1.set_artist_title('artist', 'title')
    assert proc.queue.empty()

    await mpris3.disconnect()
    line = await proc.queue.get()
    assert line == 'test2: artist - title'

    await mpris2.disconnect()
    line = await proc.queue.get()
    assert line == 'test1: artist - title'

    await mpris1.disconnect()
    line = await proc.queue.get()
    assert line == ''

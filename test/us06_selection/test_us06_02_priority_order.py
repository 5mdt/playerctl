"""US-6.2: As a user, I want `-p a,b` to choose players in my order of
priority; `vlc` also matches `vlc.instance123`."""

import pytest

from ..helpers.selection import PLAIN_SELECTIONS


@pytest.mark.parametrize(
    ('selection', 'expected'),
    PLAIN_SELECTIONS.items(),
    ids=['-'.join(s) for s in PLAIN_SELECTIONS],
)
async def test_first_selected_player_wins(
    selection, expected, selection_players, select
):
    assert await select(*selection) == expected[0], (selection, expected)

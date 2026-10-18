"""US-6.2: As a user, I want `-p a,b` to choose players in my order of
priority; `vlc` also matches `vlc.instance123`."""

import pytest

from ..helpers.selection import PLAIN_SELECTIONS, S1, S1I, S2


@pytest.mark.parametrize(
    ('selection', 'expected'),
    PLAIN_SELECTIONS.items(),
    ids=['-'.join(s) for s in PLAIN_SELECTIONS],
)
async def test_first_selected_player_wins(
    selection, expected, selection_players, select
):
    assert await select(*selection) == expected[0], (selection, expected)


@pytest.mark.parametrize(
    'arg',
    [
        '" selection2 , selection1 "',
        '"selection2,,selection1"',
        '",selection2,selection1,"',
        '"selection2 ,  , selection1"',
    ],
)
async def test_blank_and_padded_tokens_ignored(
    arg, playerctl, selection_players
):
    result = await playerctl.run(
        f'-a -p {arg} status --format "{{{{playerInstance}}}}"'
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split('\n') == [S2, S1, S1I]

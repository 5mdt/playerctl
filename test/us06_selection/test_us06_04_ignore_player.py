"""US-6.4: As a user, I want `-i/--ignore-player` to exclude players (ignore
always wins over select)."""

import pytest

from ..helpers.selection import S1, S1I, S2, S3, S6I


@pytest.mark.parametrize('flag', ['-i', '--ignore-player'])
async def test_ignored_player_is_not_listed(
    flag, playerctl, selection_players
):
    result = await playerctl.run(f'--list-all {flag} {S2}')

    assert result.returncode == 0, result.stderr
    players = result.stdout.splitlines()
    assert S2 not in players
    assert sorted(players) == sorted([S1, S1I, S3, S6I])


async def test_ignored_player_is_not_selected(playerctl, selection_players):
    result = await playerctl.run(
        f'-p {S2},{S3} -i {S2} status --format "{{{{playerInstance}}}}"'
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == S3


async def test_ignore_wins_over_select(playerctl, selection_players):
    result = await playerctl.run(f'-p {S2} -i {S2} status')

    assert result.returncode == 1
    assert 'No players found' in result.stderr.splitlines()


async def test_ignore_comma_list(playerctl, selection_players):
    players = await playerctl.list(ignored=[S1, S2, S3])
    assert sorted(players) == [S6I]


async def test_ignore_name_matches_instances(playerctl, selection_players):
    # ignoring `selection1` also ignores `selection1.i_123`
    players = await playerctl.list(ignored=[S1])
    assert S1 not in players
    assert S1I not in players
    assert S2 in players


async def test_ignore_instance_leaves_base_name(playerctl, selection_players):
    players = await playerctl.list(ignored=[S1I])
    assert S1I not in players
    assert S1 in players


async def test_ignore_with_all_players(playerctl, selection_players):
    result = await playerctl.run(
        f'-a -i {S1},{S2} status --format "{{{{playerInstance}}}}"'
    )

    assert result.returncode == 0, result.stderr
    assert sorted(result.stdout.splitlines()) == sorted([S3, S6I])


async def test_ignore_with_all_players_and_select(
    playerctl, selection_players
):
    result = await playerctl.run(
        f'-a -p {S1},{S2},{S3} -i {S1} status --format "{{{{playerInstance}}}}"'
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [S2, S3]


async def test_ignore_with_list_all_and_select(playerctl, selection_players):
    assert await playerctl.list(players=[S3, S1, S2], ignored=[S1]) == [
        S3,
        S2,
    ]


@pytest.mark.parametrize(
    'arg', ['" selection1 , selection2 "', '"selection1,,selection2"']
)
async def test_blank_and_padded_tokens_ignored(
    arg, playerctl, selection_players
):
    result = await playerctl.run(f'--list-all -i {arg}')

    assert result.returncode == 0, result.stderr
    assert sorted(result.stdout.splitlines()) == sorted([S3, S6I])


async def test_any_placeholder_ignores_every_player(
    playerctl, selection_players
):
    result = await playerctl.run('--list-all -i %any')

    assert result.returncode == 0, result.stderr
    assert result.stdout == ''

    result = await playerctl.run('-i %any status')

    assert result.returncode == 1
    assert 'No players found' in result.stderr

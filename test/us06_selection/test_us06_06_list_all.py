"""US-6.6: As a user, I want `-l/--list-all` to list players, respecting `-p`
order."""

import pytest

from ..helpers.mpris import (
    PLAYERCTLD_INTERFACE,
    PLAYERCTLD_INTERFACE_LEGACY,
    setup_playerctld,
)
from ..helpers.selection import DAEMON_SELECTIONS


async def test_list_all_without_players(playerctl):
    result = await playerctl.run('--list-all')

    assert result.returncode == 0, result.stderr
    assert not result.stdout
    assert result.stderr


async def test_list_all_names(playerctl, mpris_factory):
    await mpris_factory('basics1', 'basics2', 'basics3')

    result = await playerctl.run('--list-all')

    assert result.returncode == 0, result.stderr
    players = result.stdout.splitlines()
    assert 'basics1' in players
    assert 'basics2' in players
    assert 'basics3' in players


@pytest.mark.parametrize(
    'interface', [PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY]
)
async def test_list_all_through_playerctld(bus_address, playerctl, interface):
    # the legacy interface is what an older playerctld serves
    playerctld = await setup_playerctld(
        bus_address=bus_address, interface=interface
    )

    for selection, players, expected in DAEMON_SELECTIONS:
        playerctld.player_names = [
            f'org.mpris.MediaPlayer2.{p}' for p in players
        ]
        # one playerctld only, so the cases can't run in parallel
        result = await playerctl.list(players=selection)
        assert result == expected, (selection, players, expected)

    await playerctld.disconnect()


@pytest.mark.parametrize('flag', ['-s', '--no-messages'])
async def test_list_all_without_players_and_no_messages(flag, playerctl):
    result = await playerctl.run(f'--list-all {flag}')

    assert result.returncode == 0, result.stderr
    assert result.stdout == ''
    assert result.stderr == ''


async def test_list_all_short_flag(playerctl, mpris_factory):
    await mpris_factory('basics1')

    result = await playerctl.run('-l')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['basics1']


async def test_list_all_with_no_selected_player_is_not_an_error(
    playerctl, mpris_factory
):
    # altdesktop/playerctl#47: an empty list is a valid result, unlike a
    # command that could not act on a player, so --list-all exits 0
    await mpris_factory('basics1')

    result = await playerctl.run('--list-all --player missing')

    assert result.returncode == 0, result.stderr
    assert result.stdout == ''

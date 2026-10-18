"""US-9.3: As a scripter, I want `-s/--no-messages` to hide these messages."""

import pytest

FLAGS = ('-s', '--no-messages')
COMMANDS = ('play', 'pause', 'status', 'metadata', 'position', 'volume')


@pytest.mark.parametrize('flag', FLAGS)
@pytest.mark.parametrize('command', COMMANDS)
async def test_no_players_found_hidden(flag, command, playerctl):
    result = await playerctl.run(f'{flag} {command}')

    assert result.returncode == 1
    assert not result.stdout
    assert result.stderr == ''


@pytest.mark.parametrize('flag', FLAGS)
@pytest.mark.parametrize('command', COMMANDS)
async def test_cannot_handle_hidden(flag, command, playerctl):
    # playerctld without any active player: selected but cannot handle
    result = await playerctl.run(f'{flag} -p playerctld {command}')

    assert result.returncode == 1
    assert not result.stdout
    assert result.stderr == ''


async def test_messages_shown_without_flag(playerctl):
    result = await playerctl.run('status')
    assert 'No players found' in result.stderr

    result = await playerctl.run('-p playerctld status')
    assert 'No player could handle this command' in result.stderr

"""US-9.1: As a scripter, I want exit code 1 and "No players found" when no
players are running."""

import asyncio

COMMANDS = (
    'play',
    'pause',
    'play-pause',
    'stop',
    'next',
    'previous',
    'position',
    'position 5',
    'volume',
    'volume 0.5',
    'status',
    'metadata',
    'loop',
    'loop None',
    'shuffle',
    'shuffle On',
    'open https://google.com',
)


async def test_commands_without_players(playerctl):
    results = await asyncio.gather(*(playerctl.run(cmd) for cmd in COMMANDS))

    for result in results:
        assert result.returncode == 1
        assert not result.stdout
        assert 'No players found' in result.stderr.split('\n')

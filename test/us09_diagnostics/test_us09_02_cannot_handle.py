"""US-9.2: As a scripter, I want exit code 1 and "No player could handle this
command" when no player can run the command."""

import asyncio

COMMANDS = (
    'play',
    'pause',
    'play-pause',
    'stop',
    'next',
    'previous',
    'position',
    'volume',
    'status',
    'metadata',
    'loop',
    'shuffle',
)


async def test_playerctld_without_active_player(playerctl):
    # with no other players running, these should error because there's no
    # active player (not no players found). This tests activation and property
    # errors as well.
    results = await asyncio.gather(
        *(playerctl.run(f'-p playerctld {cmd}') for cmd in COMMANDS)
    )

    for result in results:
        assert result.returncode == 1
        assert (
            'No player could handle this command' in result.stderr.splitlines()
        )

"""US-9.4: As a user, I want `--help`/`--version` (and help when no command is
given)."""


async def test_help(playerctl):
    result = await playerctl.run('--help')

    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert not result.stderr


async def test_version(playerctl):
    result = await playerctl.run('--version')

    assert result.returncode == 0, result.stderr
    assert result.stdout
    assert not result.stderr

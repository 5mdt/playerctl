"""US-6.7: As a user, I want players on both the session bus and the system
bus to be found."""


async def test_lists_session_and_system_players(playerctl, mpris_factory):
    await mpris_factory('system', system=True)
    await mpris_factory('session1')

    result = await playerctl.run('-l')

    assert result.returncode == 0, result.stdout
    assert result.stdout.split() == ['session1', 'system']

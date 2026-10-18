"""US-11.1: As a developer, I want `playerctl_list_players()` to cover both
buses."""


async def test_list_players_covers_session_and_system(gi_run, mpris_factory):
    await mpris_factory('system', system=True)
    await mpris_factory('session1')

    result = await gi_run("""
        names = Playerctl.list_players()
        for n in sorted(names, key=lambda n: n.instance):
            out(n.instance, n.name, n.source == Playerctl.Source.DBUS_SYSTEM)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'session1 session1 False',
        'system system True',
    ]

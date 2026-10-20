"""US-11.1: As a developer, I want `playerctl_list_players()` to cover both
buses."""

from ..helpers.gi import run_gi
from ..helpers.mpris import setup_partial_player, setup_playerctld


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


async def test_list_is_sorted_per_bus_session_first(gi_run, mpris_factory):
    await mpris_factory('zeta', 'alpha', 'mid')
    await mpris_factory('sys_b', 'sys_a', system=True)

    result = await gi_run("""
        for n in Playerctl.list_players():
            out(n.instance, n.source.value_nick)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'alpha dbus-session',
        'mid dbus-session',
        'zeta dbus-session',
        'sys_a dbus-system',
        'sys_b dbus-system',
    ]


async def test_player_name_fields(gi_run, mpris_factory):
    await mpris_factory('vlc.instance42')

    result = await gi_run("""
        [name] = Playerctl.list_players()
        out(name.name, name.instance, name.source.value_nick)
        copy = name.copy()
        out(copy.name, copy.instance, copy.source.value_nick, copy is name)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'vlc vlc.instance42 dbus-session',
        'vlc vlc.instance42 dbus-session False',
    ]


async def test_names_follow_playerctld_order(
    bus_address, gi_run, mpris_factory
):

    playerctld = await setup_playerctld(bus_address)
    playerctld.player_names = [
        'org.mpris.MediaPlayer2.zeta',
        'org.mpris.MediaPlayer2.alpha',
    ]

    result = await gi_run("""
        out(*[n.instance for n in Playerctl.list_players()
              if n.source == Playerctl.Source.DBUS_SESSION])
    """)
    await playerctld.disconnect()

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['zeta', 'alpha']


async def test_playerctld_without_player_names_falls_back_to_list_names(
    bus_address, gi_run, mpris_factory
):

    await mpris_factory('player1')
    # owns the playerctld name but serves no PlayerNames property
    playerctld = await setup_partial_player('playerctld', bus_address)

    result = await gi_run("""
        names = [n.instance for n in Playerctl.list_players()]
        out('player1' in names)
    """)
    playerctld.disconnect()

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['True']
    assert 'Could not get player names from playerctld' in result.stderr


async def test_invalid_session_bus_address_gives_empty_list(gi_run):

    result = await run_gi(
        'unix:path=/nonexistent/bus',
        """
        out(len(Playerctl.list_players()))
        out(len(Playerctl.PlayerManager().props.player_names))
        """,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['0', '0']
    assert 'D-Bus socket address not found' in result.stderr

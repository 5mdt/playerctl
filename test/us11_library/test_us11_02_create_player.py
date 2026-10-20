"""US-11.2: As a developer, I want to create a `PlayerctlPlayer` by name, by
name plus source, or from a `PlayerctlPlayerName`."""

import pytest

# Only new_from_name() fills in `player-instance`; new() and new_for_source()
# just look the player up by name.
CREATE = {
    'by_name': (
        "Playerctl.Player.new('create.instance123')",
        'create',
    ),
    'by_name_and_source': (
        "Playerctl.Player.new_for_source("
        "'create.instance123', Playerctl.Source.DBUS_SESSION)",
        'create',
    ),
    'from_player_name': (
        'Playerctl.Player.new_from_name(Playerctl.list_players()[0])',
        'create create.instance123',
    ),
}


@pytest.mark.parametrize(
    ('expr', 'expected'), CREATE.values(), ids=CREATE.keys()
)
async def test_create_player(expr, expected, gi_run, mpris_factory):
    await mpris_factory('create.instance123')

    result = await gi_run(f"""
        player = {expr}
        out(player.props.player_name, player.props.player_instance or '')
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == expected.split()


async def test_unknown_player_is_not_found(gi_run, mpris_factory):
    await mpris_factory('other')

    result = await gi_run("""
        try:
            Playerctl.Player.new('nonexistent')
        except GLib.Error as e:
            out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['error Player not found']


async def test_no_name_connects_to_first_available(gi_run, mpris_factory):
    await mpris_factory('only')

    result = await gi_run("""
        out(Playerctl.Player.new(None).props.player_name)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['only']


async def test_name_matches_an_instance(gi_run, mpris_factory):
    await mpris_factory('create.instance123')

    result = await gi_run("""
        player = Playerctl.Player.new('create')
        out(player.props.player_name, player.props.source.value_nick)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['create', 'dbus-session']


async def test_create_for_system_source(gi_run, mpris_factory):
    await mpris_factory('sysplayer', system=True)

    result = await gi_run("""
        player = Playerctl.Player.new_for_source(
            'sysplayer', Playerctl.Source.DBUS_SYSTEM)
        out(player.props.player_name, player.props.source.value_nick)
        try:
            Playerctl.Player.new_for_source(
                'sysplayer', Playerctl.Source.DBUS_SESSION)
        except GLib.Error as e:
            out('error', e.message)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        'sysplayer dbus-system',
        'error Player not found',
    ]


async def test_new_without_source_finds_system_player(gi_run, mpris_factory):
    await mpris_factory('sysplayer', system=True)

    result = await gi_run("""
        player = Playerctl.Player.new('sysplayer')
        out(player.props.source.value_nick)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.split() == ['dbus-system']


@pytest.mark.timeout(60)
async def test_creating_players_in_a_loop_does_not_leak(gi_run, mpris_factory):
    # 5mdt/playerctl#51: memory grew by about 2 KiB per created Player
    await mpris_factory('leak')

    result = await gi_run("""
        def rss_kib():
            with open('/proc/self/statm') as f:
                return int(f.read().split()[1]) * 4

        for i in range(2000):
            Playerctl.Player.new_from_name(Playerctl.list_players()[0])
            if i == 300:
                base = rss_kib()
        out(rss_kib() - base)
    """)

    assert result.returncode == 0, result.stderr
    assert int(result.stdout) < 1024, f'grew by {result.stdout} KiB'

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

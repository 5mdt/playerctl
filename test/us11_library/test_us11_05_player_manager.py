"""US-11.5: As a developer, I want `PlayerctlPlayerManager` to emit
appeared/vanished signals and keep a sortable player list."""

MANAGE = """
    manager = Playerctl.PlayerManager()

    def on_name_appeared(manager, name):
        out('name-appeared', name.instance)
        manager.manage_player(Playerctl.Player.new_from_name(name))

    manager.connect('name-appeared', on_name_appeared)
    manager.connect('name-vanished', lambda m, n: out('name-vanished', n.instance))
    manager.connect('player-appeared', lambda m, p: out('player-appeared', p.props.player_instance))
    manager.connect('player-vanished', lambda m, p: out('player-vanished', p.props.player_instance))
    run_loop()
"""


async def test_appeared_and_vanished_signals(gi_start, mpris_factory):
    proc = await gi_start(MANAGE)

    [mpris] = await mpris_factory('mgr1')
    lines = [await proc.queue.get() for _ in range(2)]
    assert sorted(lines) == ['name-appeared mgr1', 'player-appeared mgr1']

    await mpris.disconnect()
    lines = [await proc.queue.get() for _ in range(2)]
    assert sorted(lines) == ['name-vanished mgr1', 'player-vanished mgr1']


async def test_move_player_to_top(gi_run, mpris_factory):
    await mpris_factory('mgr_a', 'mgr_b')

    result = await gi_run("""
        manager = Playerctl.PlayerManager()
        for name in Playerctl.list_players():
            manager.manage_player(Playerctl.Player.new_from_name(name))

        def instances():
            return [p.props.player_instance for p in manager.props.players]

        out(*instances())
        manager.move_player_to_top(manager.props.players[-1])
        out(*instances())
    """)

    assert result.returncode == 0, result.stderr
    before, after = (line.split() for line in result.stdout.splitlines())
    assert sorted(before) == ['mgr_a', 'mgr_b']
    assert after == [before[-1], before[0]]

"""US-11.11: As a developer, I want `PlayerctlPlayerManager` to track names
and players through re-appearing names, instances, both buses, many players
and a sort function."""

from ..helpers.gi import SORT_FUNC, compose
from ..helpers.mpris import setup_partial_player, setup_playerctld

AUTO_MANAGE = """
    manager = Playerctl.PlayerManager()

    def key(player):
        return '%s/%s' % (player.props.source.value_nick, player.props.player_instance)

    def on_name_appeared(manager, name):
        out('name-appeared', name.name, name.instance, name.source.value_nick)
        try:
            manager.manage_player(Playerctl.Player.new_from_name(name))
        except GLib.Error:
            out('not-managed', name.instance)

    def listing():
        return ' '.join(key(p) for p in manager.props.players)

    def names():
        return ' '.join(
            '%s/%s' % (n.source.value_nick, n.instance)
            for n in manager.props.player_names)

    manager.connect('name-appeared', on_name_appeared)
    manager.connect('name-vanished', lambda m, n: out('name-vanished', n.instance, n.source.value_nick))
    manager.connect('player-appeared', lambda m, p: out('player-appeared', key(p)))
    manager.connect('player-vanished', lambda m, p: out('player-vanished', key(p)))
"""


async def expect(proc, *lines):
    got = [await proc.queue.get() for _ in lines]
    assert sorted(got) == sorted(lines)


async def test_name_reappears_after_vanishing(gi_start, mpris_factory):
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        GLib.timeout_add(
            2500, lambda: out('final', listing(), '|', names()) or False)
        run_loop(3000)
    """,
        )
    )

    for _ in range(2):
        [mpris] = await mpris_factory('back')
        await expect(
            proc,
            'name-appeared back back dbus-session',
            'player-appeared dbus-session/back',
        )
        await mpris.disconnect()
        await expect(
            proc,
            'name-vanished back dbus-session',
            'player-vanished dbus-session/back',
        )
    [mpris] = await mpris_factory('back')
    await expect(
        proc,
        'name-appeared back back dbus-session',
        'player-appeared dbus-session/back',
    )
    assert (
        await proc.queue.get() == 'final dbus-session/back | dbus-session/back'
    )


async def test_instance_names(gi_start, mpris_factory):
    proc = await gi_start(compose(AUTO_MANAGE, 'run_loop()'))

    [mpris] = await mpris_factory('vlc.instance77')
    await expect(
        proc,
        'name-appeared vlc vlc.instance77 dbus-session',
        'player-appeared dbus-session/vlc.instance77',
    )
    await mpris.disconnect()
    await expect(
        proc,
        'name-vanished vlc.instance77 dbus-session',
        'player-vanished dbus-session/vlc.instance77',
    )


async def test_properties_follow_the_events(gi_start, mpris_factory):
    await mpris_factory('first')
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        def start():
            out('initial', names(), '|', listing())
            manager.manage_player(Playerctl.Player.new_from_name(manager.props.player_names[0]))
            out('managed', names(), '|', listing())
            manager.connect('player-appeared', lambda m, p: out('now', names(), '|', listing()))
            manager.connect('name-vanished', lambda m, n: out('gone', names(), '|', listing()))

        GLib.idle_add(start)
        run_loop()
    """,
        )
    )
    assert await proc.queue.get() == 'initial dbus-session/first |'
    assert await proc.queue.get() == 'player-appeared dbus-session/first'
    assert (
        await proc.queue.get()
        == 'managed dbus-session/first | dbus-session/first'
    )

    [second] = await mpris_factory('second')
    lines = [await proc.queue.get() for _ in range(3)]
    assert (
        'now dbus-session/second dbus-session/first | dbus-session/second dbus-session/first'
        in lines
    )

    await second.disconnect()
    lines = [await proc.queue.get() for _ in range(3)]
    assert 'gone dbus-session/first | dbus-session/first' in lines


async def test_same_name_on_both_buses_vanishes_independently(
    gi_start, mpris_factory
):
    await mpris_factory('twin')
    [system] = await mpris_factory('twin', system=True)
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        def start():
            # the session player ends up first in the list
            for name in reversed(manager.props.player_names):
                manager.manage_player(Playerctl.Player.new_from_name(name))
            out('managed', len(manager.props.players))

        GLib.idle_add(start)
        run_loop()
    """,
        )
    )
    await expect(
        proc,
        'player-appeared dbus-session/twin',
        'player-appeared dbus-system/twin',
    )
    assert await proc.queue.get() == 'managed 2'

    await system.disconnect()

    # the session player is still there and is not the one that vanished
    assert await proc.queue.get() == 'player-vanished dbus-system/twin'
    assert await proc.queue.get() == 'name-vanished twin dbus-system'


async def test_vanishing_unmanaged_name_keeps_players_on_both_buses(
    gi_start, mpris_factory
):
    [_, other] = await mpris_factory('twin', 'other')
    await mpris_factory('twin', system=True)
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        def start():
            for name in manager.props.player_names:
                if name.name != 'other':
                    manager.manage_player(Playerctl.Player.new_from_name(name))
            out('managed', len(manager.props.players))

        GLib.idle_add(start)
        run_loop()
    """,
        )
    )
    await expect(
        proc,
        'player-appeared dbus-session/twin',
        'player-appeared dbus-system/twin',
    )
    assert await proc.queue.get() == 'managed 2'

    await other.disconnect()

    # no managed player has that name, so nothing but the name vanishes
    assert await proc.queue.get() == 'name-vanished other dbus-session'


async def test_name_appearing_while_players_are_managed(
    gi_start, mpris_factory
):
    await mpris_factory('old_a', 'old_b')
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        def start():
            for name in manager.props.player_names:
                manager.manage_player(Playerctl.Player.new_from_name(name))

        GLib.idle_add(start)
        GLib.timeout_add(1200, lambda: out('final', names(), '|', listing()) or False)
        run_loop(1500)
    """,
        )
    )

    await expect(
        proc,
        'player-appeared dbus-session/old_a',
        'player-appeared dbus-session/old_b',
    )
    await mpris_factory('new_a')
    await mpris_factory('new_b', system=True)

    await expect(
        proc,
        'name-appeared new_a new_a dbus-session',
        'player-appeared dbus-session/new_a',
        'name-appeared new_b new_b dbus-system',
        'player-appeared dbus-system/new_b',
    )
    final = await proc.queue.get()
    assert final.startswith('final ')
    names, listing = final[len('final ') :].split(' | ')
    assert sorted(names.split()) == sorted(listing.split())
    assert len(listing.split()) == 4


async def test_player_that_cannot_be_created_is_not_managed(
    gi_start, bus_address
):
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        GLib.timeout_add(800, lambda: out('final', names(), '|', listing()) or False)
        run_loop(1200)
    """,
        )
    )

    bus = await setup_partial_player('broken', bus_address, root=True)
    lines = [await proc.queue.get() for _ in range(2)]
    bus.disconnect()

    assert lines[0] == 'name-appeared broken broken dbus-session'
    assert lines[1] in (
        'not-managed broken',
        'player-appeared dbus-session/broken',
    )


async def test_unmanaged_name_vanishes_without_player_signal(
    gi_start, mpris_factory
):
    proc = await gi_start(
        """
        manager = Playerctl.PlayerManager()
        manager.connect('name-appeared', lambda m, n: out('name-appeared', n.instance))
        manager.connect('name-vanished', lambda m, n: out('name-vanished', n.instance))
        manager.connect('player-vanished', lambda m, p: out('player-vanished'))
        run_loop(1500)
        """
    )

    [mpris] = await mpris_factory('lone')
    assert await proc.queue.get() == 'name-appeared lone'
    await mpris.disconnect()
    assert await proc.queue.get() == 'name-vanished lone'


async def test_move_player_to_top_with_many_players(gi_run, mpris_factory):
    await mpris_factory(*(f'm{i}' for i in range(6)))

    result = await gi_run("""
        manager = Playerctl.PlayerManager()
        for name in manager.props.player_names:
            manager.manage_player(Playerctl.Player.new_from_name(name))

        def order():
            return ' '.join(p.props.player_instance for p in manager.props.players)

        by_name = {p.props.player_instance: p for p in manager.props.players}
        out(order())
        manager.move_player_to_top(by_name['m3'])
        out(order())
        manager.move_player_to_top(by_name['m3'])
        out(order())
        manager.move_player_to_top(manager.props.players[-1])
        out(order())
        manager.move_player_to_top(Playerctl.Player.new('m0'))
        out(order())
    """)

    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    start = lines[0].split()
    assert sorted(start) == [f'm{i}' for i in range(6)]
    moved = ['m3'] + [n for n in start if n != 'm3']
    assert lines[1].split() == moved
    assert lines[2].split() == moved
    assert lines[3].split() == [moved[-1]] + moved[:-1]
    assert lines[4].split() == lines[3].split()


async def test_sort_function_orders_the_players(gi_run, mpris_factory):
    await mpris_factory(*(f'p{i}' for i in (3, 1, 5, 0, 4, 2)))

    result = await gi_run(
        compose(
            SORT_FUNC,
            """
        manager = Playerctl.PlayerManager()
        players = [Playerctl.Player.new_from_name(n) for n in manager.props.player_names]

        def order():
            return ' '.join(p.props.player_instance for p in manager.props.players)

        for player in players[:3]:
            manager.manage_player(player)
        set_sort_func(manager, lambda instance: instance)
        out(order())
        for player in players[3:]:
            manager.manage_player(player)
        out(order())
        manager.move_player_to_top(manager.props.players[-1])
        out(order())
    """,
        )
    )

    assert result.returncode == 0, result.stderr
    first, second, third = (
        line.split() for line in result.stdout.splitlines()
    )
    assert first == sorted(first) and len(first) == 3
    assert second == [f'p{i}' for i in range(6)]
    # after the move the sort function puts the player back in order
    assert third == second


async def test_equal_players_keep_the_moved_one_on_top(gi_run, mpris_factory):
    await mpris_factory('e0', 'e1', 'e2')

    result = await gi_run(
        compose(
            SORT_FUNC,
            """
        manager = Playerctl.PlayerManager()
        set_sort_func(manager, lambda instance: 0)
        for name in manager.props.player_names:
            manager.manage_player(Playerctl.Player.new_from_name(name))

        def order():
            return ' '.join(p.props.player_instance for p in manager.props.players)

        out(order())
        manager.move_player_to_top(manager.props.players[-1])
        out(order())
    """,
        )
    )

    assert result.returncode == 0, result.stderr
    before, after = (line.split() for line in result.stdout.splitlines())
    assert after[0] == before[-1]
    assert sorted(after) == sorted(before)


async def test_playerctld_order_is_used_for_the_names(
    bus_address, gi_start, mpris_factory
):
    await mpris_factory('a', 'b', 'c')
    playerctld = await setup_playerctld(bus_address)
    playerctld.player_names = [
        'org.mpris.MediaPlayer2.c',
        'org.mpris.MediaPlayer2.a',
        'org.mpris.MediaPlayer2.b',
    ]
    proc = await gi_start(
        compose(
            AUTO_MANAGE,
            """
        GLib.idle_add(lambda: out('names', names()))
        run_loop(1000)
    """,
        )
    )

    assert (
        await proc.queue.get()
        == 'names dbus-session/c dbus-session/a dbus-session/b'
    )
    await playerctld.disconnect()

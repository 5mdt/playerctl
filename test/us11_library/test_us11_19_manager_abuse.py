"""US-11.19: As a developer, I want `PlayerctlPlayerManager` to survive
misuse: sort functions that raise, re-enter or contradict themselves, a NULL
sort function, players managed twice, unmanaged or already vanished, many
managers on one bus and managers destroyed with live players."""

import asyncio

import pytest

from ..helpers.gi import compose
from ..helpers.gi_abuse import (
    ATTEMPT,
    MANAGE_ALL,
    SORT_RAW,
    assert_clean,
)

NAMES = ('alpha', 'bravo', 'charlie')

CRASH_ON_NULL_SORT = (
    'BUG-L2: set_sort_func(NULL) sorts the managed players with a NULL compare '
    'function (g_list_sort_with_data) and crashes the client with 2 or more '
    'players'
)


# --- sort function misuse ---------------------------------------------------


@pytest.mark.parametrize(
    'count',
    [
        0,
        1,
        pytest.param(
            2, marks=pytest.mark.xfail(strict=True, reason=CRASH_ON_NULL_SORT)
        ),
        pytest.param(
            3, marks=pytest.mark.xfail(strict=True, reason=CRASH_ON_NULL_SORT)
        ),
    ],
)
async def test_null_sort_function(count, gi_run, mpris_factory):
    if count:
        await mpris_factory(*NAMES[:count])

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        set_sort_null(manager)
        out('players', len(manager.props.players))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == f'players {count}'


@pytest.mark.parametrize(
    'count',
    [
        0,
        1,
        pytest.param(
            2, marks=pytest.mark.xfail(strict=True, reason=CRASH_ON_NULL_SORT)
        ),
    ],
)
async def test_sort_function_cleared_after_it_was_set(
    count, gi_run, mpris_factory
):
    if count:
        await mpris_factory(*NAMES[:count])

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        set_sort_raw(manager, lambda a, b: (a > b) - (a < b))
        out(listing())
        set_sort_null(manager)
        out('cleared', len(manager.props.players))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout.splitlines()[-1] == f'cleared {count}'


async def test_raising_sort_function(gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        def compare(a, b):
            raise RuntimeError('no order for you')

        set_sort_raw(manager, compare)
        out('players', len(manager.props.players))
        manager.move_player_to_top(manager.props.players[-1])
        out('players', len(manager.props.players))
        """,
        )
    )

    # Python reports the exception raised in a ctypes callback and goes on
    assert_clean(result, allow=['Traceback'])
    assert result.stdout.splitlines() == ['players 3', 'players 3']


@pytest.mark.parametrize(
    'answer',
    ['1', '-1', '0', '2**31 - 1', '-2**31', 'random.choice([-1, 0, 1])'],
    ids=['always-1', 'always--1', 'always-0', 'int-max', 'int-min', 'random'],
)
async def test_inconsistent_sort_function(answer, gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            f"""
        import random
        random.seed(7)
        set_sort_raw(manager, lambda a, b: {answer})
        for player in list(manager.props.players):
            manager.move_player_to_top(player)
        out(sorted(p.props.player_name for p in manager.props.players))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == str(sorted(NAMES))


async def test_sort_function_that_reads_the_manager(gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        seen = []

        def compare(a, b):
            seen.append(len(manager.props.players))
            seen.append(len(manager.props.player_names))
            return (a > b) - (a < b)

        set_sort_raw(manager, compare)
        out(listing(), bool(seen))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == 'alpha bravo charlie True'


@pytest.mark.parametrize(
    'reentry',
    [
        'manager.move_player_to_top(manager.props.players[0])',
        'manager.set_property("player-names", None)',
    ],
    ids=['move-to-top', 'write-property'],
)
async def test_sort_function_that_calls_back_into_the_manager(
    reentry, gi_run, mpris_factory
):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            f"""
        depth = []

        def compare(a, b):
            if not depth:
                depth.append(1)
                try:
                    {reentry}
                except Exception:
                    pass
            return (a > b) - (a < b)

        set_sort_raw(manager, compare)
        out('survived', len(manager.props.players))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == 'survived 3'


@pytest.mark.parametrize('order', ['ascending', 'descending'])
async def test_sort_function_orders_the_players(order, gi_run, mpris_factory):
    await mpris_factory(*NAMES)
    sign = '' if order == 'ascending' else '-'

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            f"""
        set_sort_raw(manager, lambda a, b: {sign}((a > b) - (a < b)))
        out(listing())
        """,
        )
    )

    assert_clean(result)
    expected = NAMES if order == 'ascending' else NAMES[::-1]
    assert result.stdout == ' '.join(expected)


async def test_replaced_sort_function_notifies_the_old_one(
    gi_run, mpris_factory
):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        notified = []
        set_sort_raw(manager, lambda a, b: 0, lambda: notified.append(1))
        set_sort_raw(manager, lambda a, b: 0)
        out('notified', len(notified))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == 'notified 1'


test_replaced_sort_function_notifies_the_old_one = pytest.mark.xfail(
    strict=True,
    reason='BUG-L3: the destroy notify given to set_sort_func() is never '
    'called, not when the sort function is replaced nor when the manager is '
    'destroyed (documented as "notify when the sort function will no longer '
    'be used"); the sort data leaks',
)(test_replaced_sort_function_notifies_the_old_one)


@pytest.mark.xfail(
    strict=True,
    reason='BUG-L3: the destroy notify given to set_sort_func() is never '
    'called when the manager is destroyed',
)
async def test_destroyed_manager_notifies_its_sort_function(
    gi_run, mpris_factory
):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            SORT_RAW,
            MANAGE_ALL,
            """
        import gc
        notified = []
        set_sort_raw(manager, lambda a, b: 0, lambda: notified.append(1))
        del manager
        gc.collect()
        out('notified', len(notified))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout == 'notified 1'


# --- managing players ------------------------------------------------------


async def test_managing_a_player_twice_lists_it_once(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        manager = Playerctl.PlayerManager()
        appeared = []
        manager.connect('player-appeared', lambda m, p: appeared.append(p))
        player = Playerctl.Player.new('lib')
        for _ in range(5):
            manager.manage_player(player)
        out(len(manager.props.players), len(appeared))
    """)

    assert_clean(result)
    assert result.stdout == '1 1'


async def test_two_player_objects_for_one_name_are_both_managed(
    gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run("""
        manager = Playerctl.PlayerManager()
        manager.manage_player(Playerctl.Player.new('lib'))
        manager.manage_player(Playerctl.Player.new('lib'))
        out(len(manager.props.players))
    """)

    assert_clean(result)
    assert result.stdout == '2'


async def test_move_to_top_of_an_unmanaged_player(gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            MANAGE_ALL,
            """
        before = listing()
        stranger = Playerctl.Player.new('alpha')
        manager.move_player_to_top(stranger)
        out(before == listing(), len(manager.props.players))
        other = Playerctl.PlayerManager()
        other.move_player_to_top(manager.props.players[0])
        out(len(other.props.players), len(manager.props.players))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout.splitlines() == ['True 3', '0 3']


async def test_move_to_top_reorders(gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run(
        compose(
            MANAGE_ALL,
            """
        for name in ('alpha', 'bravo', 'charlie', 'alpha'):
            player = [p for p in manager.props.players
                      if p.props.player_name == name][0]
            manager.move_player_to_top(player)
            out(listing().split()[0])
        """,
        )
    )

    assert_clean(result)
    assert result.stdout.splitlines() == ['alpha', 'bravo', 'charlie', 'alpha']


async def test_manager_without_any_player(gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            """
        manager = Playerctl.PlayerManager()
        out(len(manager.props.players), len(manager.props.player_names))
        attempt('move', lambda: manager.move_player_to_top(
            Playerctl.PlayerManager()))
        """,
        )
    )

    assert_clean(result)
    assert result.stdout.splitlines()[0] == '0 0'


@pytest.mark.xfail(
    strict=True,
    reason='BUG-L4: a player that vanished before manage_player() is never '
    'removed: no player-vanished, and it stays in the players list forever '
    '(the manager only matches later NameOwnerChanged signals)',
)
async def test_managing_a_player_that_vanished_before_it_was_managed(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(
        """
        player = Playerctl.Player.new('lib')
        manager = Playerctl.PlayerManager()
        loop = GLib.MainLoop()
        gone = []
        player.connect('exit', lambda p: gone.append(1))
        manager.connect('player-vanished', lambda m, p: out('vanished'))

        def check():
            if not gone:
                return True
            manager.manage_player(player)
            out('managed', len(manager.props.players))
            GLib.timeout_add(500, lambda: out(
                'later', len(manager.props.players)) or loop.quit())
            return False

        GLib.timeout_add(50, check)
        GLib.timeout_add(3000, loop.quit)
        out('ready')
        loop.run()
        """
    )
    await mpris.disconnect()

    assert await asyncio.wait_for(proc.queue.get(), 4) == 'managed 1'
    assert await asyncio.wait_for(proc.queue.get(), 4) == 'later 0'


# --- many managers, destruction, races ---------------------------------------


async def test_fifty_managers_share_a_bus(gi_start, mpris_factory):
    proc = await gi_start(
        """
        managers = [Playerctl.PlayerManager() for _ in range(50)]
        counts = {'appeared': 0, 'vanished': 0}
        for manager in managers:
            manager.connect('name-appeared', lambda m, n: counts.__setitem__(
                'appeared', counts['appeared'] + 1))
            manager.connect('name-vanished', lambda m, n: counts.__setitem__(
                'vanished', counts['vanished'] + 1))
        loop = GLib.MainLoop()
        GLib.timeout_add(2200, lambda: out(
            'counts', counts['appeared'], counts['vanished'],
            [len(m.props.player_names) for m in managers].count(0)) or loop.quit())
        out('ready')
        loop.run()
        """
    )
    [mpris] = await mpris_factory('lib')
    await asyncio.sleep(0.3)
    await mpris.disconnect()

    assert await asyncio.wait_for(proc.queue.get(), 4) == 'counts 50 50 50'
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()


async def test_fifty_managers_manage_the_same_players(gi_run, mpris_factory):
    await mpris_factory(*NAMES)

    result = await gi_run("""
        managers = []
        for _ in range(50):
            manager = Playerctl.PlayerManager()
            for name in manager.props.player_names:
                manager.manage_player(Playerctl.Player.new_from_name(name))
            managers.append(manager)
        out(sum(len(m.props.players) for m in managers))
    """)

    assert_clean(result)
    assert result.stdout == '150'


async def test_manager_destroyed_with_live_players(gi_start, mpris_factory):
    mpris_a, mpris_b = await mpris_factory('alpha', 'bravo')
    proc = await gi_start(
        compose(
            MANAGE_ALL,
            """
        import gc
        kept = list(manager.props.players)
        del manager
        gc.collect()
        loop = GLib.MainLoop()
        for p in kept:
            p.connect('exit', lambda p: out('exit', p.props.player_name))
        GLib.timeout_add(2500, loop.quit)
        out('ready')
        loop.run()
        out('done')
        """,
        )
    )
    await mpris_a.disconnect()
    await mpris_b.disconnect()

    lines = [await asyncio.wait_for(proc.queue.get(), 4) for _ in range(3)]
    assert sorted(lines) == ['done', 'exit alpha', 'exit bravo']
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()


async def test_manager_destroyed_while_names_churn(gi_start, mpris_factory):
    proc = await gi_start(
        """
        import gc
        loop = GLib.MainLoop()
        state = {'manager': Playerctl.PlayerManager(), 'rounds': 0}

        def recreate():
            state['manager'] = Playerctl.PlayerManager()
            state['manager'].connect('name-appeared', lambda m, n: None)
            gc.collect()
            state['rounds'] += 1
            return True

        GLib.timeout_add(5, recreate)
        GLib.timeout_add(1800, lambda: out('rounds', state['rounds'] > 10)
                         or loop.quit())
        out('ready')
        loop.run()
        """
    )
    for i in range(25):
        [mpris] = await mpris_factory(f'churn{i}')
        await mpris.disconnect()

    assert await asyncio.wait_for(proc.queue.get(), 4) == 'rounds True'
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()


async def test_player_created_before_its_name_exists(gi_start, mpris_factory):
    proc = await gi_start(
        compose(
            ATTEMPT,
            """
        manager = Playerctl.PlayerManager()
        loop = GLib.MainLoop()

        def appeared(m, name):
            attempt('from_name', lambda: Playerctl.Player.new_from_name(name))
            attempt('new', lambda: Playerctl.Player.new('late'))
            loop.quit()

        manager.connect('name-appeared', appeared)
        GLib.timeout_add(3000, loop.quit)
        out('ready')
        attempt('early', lambda: Playerctl.Player.new('late'))
        loop.run()
        """,
        )
    )
    assert (await proc.queue.get()).startswith('early gerror')

    await mpris_factory('late')

    lines = [await asyncio.wait_for(proc.queue.get(), 4) for _ in range(2)]
    assert all(line.split()[1] == 'ok' for line in lines), lines
    assert await proc.proc.wait() == 0


async def test_player_new_races_with_a_name_that_appears(
    gi_start, mpris_factory
):
    proc = await gi_start(
        compose(
            ATTEMPT,
            """
        loop = GLib.MainLoop()
        results = []

        def poll():
            try:
                Playerctl.Player.new('race')
                results.append('ok')
            except GLib.Error:
                results.append('err')
            return len(results) < 60

        GLib.timeout_add(10, poll)
        GLib.timeout_add(2000, lambda: out('results', results[0], results[-1])
                         or loop.quit())
        out('ready')
        loop.run()
        """,
        )
    )
    await asyncio.sleep(0.2)
    await mpris_factory('race')

    assert await asyncio.wait_for(proc.queue.get(), 4) == 'results err ok'
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()

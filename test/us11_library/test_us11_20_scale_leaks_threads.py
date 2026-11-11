"""US-11.20: As a developer, I want libplayerctl to stay correct and leak-free
under volume (hundreds of players or objects) and to cope with being called
from several threads."""

import asyncio

import pytest
from dbus_next.aio import MessageBus

from ..helpers.gi import compose
from ..helpers.gi_abuse import ATTEMPT, LEAK, assert_clean

# generous: a leak of a few KiB per object over 500 rounds is 2 MiB or more
LEAK_LIMIT_KB = 2048

LEAKS = {
    'player': 'lambda: Playerctl.Player.new("lib")',
    'player-and-properties': 'player_props',
    'manager': 'Playerctl.PlayerManager',
    'manager-with-player': 'managed_player',
    'failed-lookup': 'failed_lookup',
    'list-players': 'Playerctl.list_players',
    'wrong-call-on-vanished-name': 'ghost_calls',
    'player-name-copy': 'name_copy',
}


@pytest.mark.parametrize('case', LEAKS.values(), ids=LEAKS.keys())
async def test_creating_and_destroying_does_not_leak(
    case, gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            LEAK,
            """
        def player_props():
            player = Playerctl.Player.new('lib')
            player.props.volume
            player.props.metadata
            player.get_title()

        def managed_player():
            manager = Playerctl.PlayerManager()
            manager.manage_player(Playerctl.Player.new('lib'))

        def failed_lookup():
            try:
                Playerctl.Player.new('nope')
            except GLib.Error:
                pass

        ghost = Playerctl.PlayerName()
        ghost.name = ghost.instance = 'ghost'
        ghost.source = Playerctl.Source.DBUS_SESSION
        ghost_player = Playerctl.Player.new_from_name(ghost)

        def ghost_calls():
            for call in (ghost_player.play, ghost_player.get_position,
                         ghost_player.get_title):
                try:
                    call()
                except GLib.Error:
                    pass

        original = Playerctl.list_players()[0]
        name_copy = original.copy
        """,
            f"""
        out(leak_kb(500, {case}))
        """,
        )
    )

    assert_clean(result, allow=['could not get metadata'])
    assert int(result.stdout) < LEAK_LIMIT_KB, result.stdout


async def test_many_player_name_copies_do_not_leak(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            LEAK,
            """
        original = Playerctl.list_players()[0]
        out(leak_kb(20000, original.copy, warmup=1000))
        """,
        )
    )

    assert_clean(result)
    assert int(result.stdout) < LEAK_LIMIT_KB


async def test_signal_handlers_do_not_pile_up_per_property_change(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(
        compose(
            LEAK,
            """
        player = Playerctl.Player.new('lib')
        seen = []
        player.connect('volume', lambda p, v: seen.append(v))
        loop = GLib.MainLoop()
        state = {}
        GLib.timeout_add(300, lambda: state.update(first=rss()) or False)
        GLib.timeout_add(
            2500,
            lambda: out('growth', rss() - state['first'], len(seen)) or loop.quit())
        out('ready')
        loop.run()
        """,
        )
    )
    await asyncio.sleep(0.4)
    for i in range(600):
        mpris.emit_properties_changed({'Volume': (i % 100) / 100})
        if i % 20 == 19:
            await mpris.ping()
            await asyncio.sleep(0.002)

    line = await asyncio.wait_for(proc.queue.get(), 4)
    _, growth, seen = line.split()
    assert int(growth) < LEAK_LIMIT_KB
    assert int(seen) > 100


# --- scale --------------------------------------------------------------


async def test_list_players_with_200_players(gi_run, mpris_factory):
    names = [f'p{i:03}' for i in range(200)]
    await mpris_factory(*names)

    result = await gi_run("""
        names = Playerctl.list_players()
        out(len(names), len({n.name for n in names}))
        out(len(Playerctl.PlayerManager().props.player_names))
    """)

    assert_clean(result)
    assert result.stdout.splitlines() == ['200 200', '200']


async def test_manager_manages_200_players(gi_run, mpris_factory):
    await mpris_factory(*[f'p{i:03}' for i in range(200)])

    result = await gi_run("""
        manager = Playerctl.PlayerManager()
        for name in manager.props.player_names:
            manager.manage_player(Playerctl.Player.new_from_name(name))
        out(len(manager.props.players))
    """)

    assert_clean(result)
    assert result.stdout == '200'


async def request_bus_names(bus_address, *names):
    bus = await MessageBus(bus_address=bus_address).connect()
    for name in names:
        await bus.request_name(name)
    return bus


HOSTILE_BUS_NAMES = [
    'org.mpris.MediaPlayer2.a.b.c.d',
    'org.mpris.MediaPlayer2.' + 'x' * 200,
    'org.mpris.MediaPlayer2.instance12345',
    'org.mpris.MediaPlayer2.a-b_c',
    'org.mpris.MediaPlayer2.z.instance1',
    'org.mpris.MediaPlayer2.z.instance2',
    'org.mpris.MediaPlayer2.UPPER',
    'org.mpris.MediaPlayer2.vlc.instance' + '9' * 50,
    'org.mpris.MediaPlayer2._',
    'org.mpris.MediaPlayer2.a.instance',
]
NOT_PLAYERS = [
    'org.mpris.MediaPlayer3.other',
    'org.mpris.MediaPlayer2',
    'org.mpris.Media.Player2.x',
    'org.example.org.mpris.MediaPlayer2.x',
    'org.mpris.mediaplayer2.lower',
    'org.mpris.MediaPlayer2x.nope',
]


async def test_list_players_with_hostile_bus_names(gi_run, bus_address):
    bus = await request_bus_names(
        bus_address, *HOSTILE_BUS_NAMES, *NOT_PLAYERS
    )
    try:
        result = await gi_run("""
            for n in Playerctl.list_players():
                out(repr(n.name), repr(n.instance))
        """)
    finally:
        bus.disconnect()

    assert_clean(result)
    shown = result.stdout.splitlines()
    assert len(shown) == len(HOSTILE_BUS_NAMES)
    assert not any('other' in line or 'lower' in line for line in shown)


async def test_manager_with_hostile_bus_names(gi_run, bus_address):
    bus = await request_bus_names(
        bus_address, *HOSTILE_BUS_NAMES, *NOT_PLAYERS
    )
    try:
        result = await gi_run(
            compose(
                ATTEMPT,
                """
            manager = Playerctl.PlayerManager()
            out('names', len(manager.props.player_names))
            for name in manager.props.player_names:
                attempt(name.instance[:20],
                        lambda: Playerctl.Player.new_from_name(name))
            """,
            )
        )
    finally:
        bus.disconnect()

    assert_clean(result, allow=['could not get metadata'])
    assert result.stdout.splitlines()[0] == f'names {len(HOSTILE_BUS_NAMES)}'


async def test_names_that_appear_and_vanish_while_listing(
    gi_run, mpris_factory, bus_address
):
    await mpris_factory('stable')
    stop = asyncio.Event()

    async def churn():
        i = 0
        while not stop.is_set():
            [mpris] = await mpris_factory(f'flap{i % 5}')
            await mpris.disconnect()
            i += 1

    task = asyncio.ensure_future(churn())
    try:
        result = await gi_run("""
            import time
            deadline = time.time() + 1.5
            rounds = 0
            while time.time() < deadline:
                names = [n.name for n in Playerctl.list_players()]
                assert 'stable' in names, names
                rounds += 1
            out('rounds', rounds > 5)
        """)
    finally:
        stop.set()
        await task

    assert_clean(result)
    assert result.stdout == 'rounds True'


# --- threads -----------------------------------------------------------------


async def test_calls_from_worker_threads(gi_run, mpris_factory):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/track/1')

    result = await gi_run("""
        import threading
        player = Playerctl.Player.new('lib')
        errors = []

        def work(n):
            try:
                for _ in range(25):
                    player.get_position()
                    player.get_title()
                    player.set_volume(0.5)
                    player.seek(n)
                    player.props.volume
            except Exception as e:
                errors.append(repr(e))

        threads = [threading.Thread(target=work, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out('errors', errors)
    """)

    assert_clean(result)
    assert result.stdout == 'errors []'


async def test_player_created_in_a_thread_used_in_the_main_thread(
    gi_run, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await gi_run("""
        import threading
        box = []
        t = threading.Thread(target=lambda: box.append(Playerctl.Player.new('lib')))
        t.start()
        t.join()
        box[0].play()
        out(box[0].props.player_name)
    """)

    assert_clean(result)
    assert result.stdout == 'lib'
    assert mpris.play_called


async def test_main_loop_running_while_threads_call_the_player(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(
        """
        import threading
        player = Playerctl.Player.new('lib')
        seen = []
        player.connect('volume', lambda p, v: seen.append(v))
        loop = GLib.MainLoop()
        done = []

        def work():
            for _ in range(60):
                player.get_position()
                player.props.volume
            done.append(1)

        threads = [threading.Thread(target=work) for _ in range(4)]
        for t in threads:
            t.start()
        GLib.timeout_add(1500, lambda: out('done', len(done), len(seen) > 0)
                         or loop.quit())
        out('ready')
        loop.run()
        """
    )
    for i in range(100):
        mpris.emit_properties_changed({'Volume': (i % 10) / 10})
        await asyncio.sleep(0.005)

    assert await asyncio.wait_for(proc.queue.get(), 4) == 'done 4 True'
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()


async def test_managers_created_in_threads(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        import threading
        counts = []

        def work():
            manager = Playerctl.PlayerManager()
            counts.append(len(manager.props.player_names))

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out(counts)
    """)

    assert_clean(result)
    assert result.stdout == '[1, 1, 1, 1, 1, 1]'


async def test_list_players_from_threads(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        import threading
        counts = []

        def work():
            for _ in range(20):
                counts.append(len(Playerctl.list_players()))

        threads = [threading.Thread(target=work) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        out(set(counts), len(counts))
    """)

    assert_clean(result)
    assert result.stdout == '{1} 120'

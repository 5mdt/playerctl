"""US-11.16: As a developer, I want every call and property read on a player
whose bus name vanished to fail with a `GLib.Error` (or read a stale value),
never to crash or log a GLib CRITICAL."""

import pytest

from ..helpers.gi import compose
from ..helpers.gi_abuse import (
    ATTEMPT,
    AWAIT_EXIT,
    assert_clean,
    parse_attempts,
    run_after_vanish,
)

# the property getters cannot return an error, so they log this instead
STALE_READ_WARNINGS = ['could not get metadata']

CALLS = {
    'play': 'player.play()',
    'pause': 'player.pause()',
    'play_pause': 'player.play_pause()',
    'stop': 'player.stop()',
    'next': 'player.next()',
    'previous': 'player.previous()',
    'seek': 'player.seek(1000)',
    'seek_negative': 'player.seek(-1000)',
    'seek_zero': 'player.seek(0)',
    'seek_max': 'player.seek(2**63 - 1)',
    'seek_min': 'player.seek(-2**63)',
    'set_position': 'player.set_position(5)',
    'set_position_negative': 'player.set_position(-5)',
    'set_position_max': 'player.set_position(2**63 - 1)',
    'open': "player.open('file:///tmp/a.mp3')",
    'open_empty': "player.open('')",
    'get_position': 'player.get_position()',
    'set_volume': 'player.set_volume(0.5)',
    'set_volume_nan': "player.set_volume(float('nan'))",
    'set_loop_status': 'player.set_loop_status(Playerctl.LoopStatus.TRACK)',
    'set_shuffle': 'player.set_shuffle(True)',
}

METADATA_CALLS = {
    'get_title': 'player.get_title()',
    'get_artist': 'player.get_artist()',
    'get_album': 'player.get_album()',
    'print_metadata_prop': "player.print_metadata_prop('xesam:title')",
    'print_metadata_prop_empty': "player.print_metadata_prop('')",
    'print_metadata_prop_none': 'player.print_metadata_prop(None)',
}

PROPERTIES = [
    'player_name',
    'source',
    'playback_status',
    'status',
    'loop_status',
    'volume',
    'shuffle',
    'metadata',
    'position',
    'can_play',
    'can_pause',
    'can_seek',
    'can_go_next',
    'can_go_previous',
    'can_control',
    'load_properties',
]


@pytest.mark.parametrize('call', CALLS.values(), ids=CALLS.keys())
async def test_call_after_vanish_is_a_glib_error(
    call, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(ATTEMPT, AWAIT_EXIT, f"attempt('call', lambda: {call})"),
    )

    assert_clean(result)
    kind, details = parse_attempts(result)['call']
    assert kind == 'gerror', (kind, details)


@pytest.mark.parametrize(
    'call', METADATA_CALLS.values(), ids=METADATA_CALLS.keys()
)
async def test_metadata_call_after_vanish_is_a_glib_error(
    call, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(ATTEMPT, AWAIT_EXIT, f"attempt('call', lambda: {call})"),
    )

    assert_clean(result)
    kind, details = parse_attempts(result)['call']
    assert kind == 'gerror', (kind, details)


@pytest.mark.parametrize('name', PROPERTIES)
async def test_property_read_after_vanish_does_not_crash(
    name, gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            ATTEMPT,
            AWAIT_EXIT,
            f"attempt('read', lambda: player.props.{name})",
        ),
    )

    assert_clean(result, allow=STALE_READ_WARNINGS)
    assert parse_attempts(result)['read'][0] == 'ok'


async def test_every_property_after_vanish_in_one_go(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')
    await mpris.set_artist_title('artist', 'title', '/t/1')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            AWAIT_EXIT,
            f"""
        for name in {PROPERTIES!r}:
            getattr(player.props, name)
        for _ in range(100):
            player.props.position
        out('survived')
        """,
        ),
    )

    assert_clean(result, allow=STALE_READ_WARNINGS)
    assert result.stdout == 'survived'


async def test_repeated_calls_after_vanish(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            ATTEMPT,
            AWAIT_EXIT,
            """
        for i in range(200):
            attempt('play%d' % i, player.play)
            attempt('pos%d' % i, player.get_position)
        """,
        ),
    )

    assert_clean(result)
    assert all(kind == 'gerror' for kind, _ in parse_attempts(result).values())


async def test_player_can_be_freed_after_vanish(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            AWAIT_EXIT,
            """
        import gc
        del player
        gc.collect()
        GLib.MainContext.default().iteration(False)
        out('freed')
        """,
        ),
    )

    assert_clean(result)
    assert result.stdout == 'freed'


async def test_exit_is_emitted_once(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        """
        player = Playerctl.Player.new('lib')
        player.connect('exit', lambda p: out('exit'))
        loop = GLib.MainLoop()
        GLib.timeout_add(1500, loop.quit)
        out('ready')
        loop.run()
        """,
    )

    assert_clean(result)
    assert result.stdout == 'exit'


async def test_player_is_unusable_but_alive_when_the_name_returns(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')
    proc = await gi_start(
        compose(
            ATTEMPT,
            """
        player = Playerctl.Player.new('lib')
        player.connect('exit', lambda p: out('exit'))
        loop = GLib.MainLoop()
        GLib.timeout_add(1200, lambda: out('probe') or attempt('play', player.play) or False)
        GLib.timeout_add(2500, loop.quit)
        out('ready')
        loop.run()
        """,
        )
    )
    await mpris.disconnect()
    assert await proc.queue.get() == 'exit'
    await mpris_factory('lib')

    assert await proc.queue.get() == 'probe'
    kind = (await proc.queue.get()).split()[1]
    assert kind in ('ok', 'gerror')
    assert await proc.proc.wait() == 0
    assert 'CRITICAL' not in (await proc.proc.stderr.read()).decode()


async def test_call_on_player_removed_by_the_manager(gi_start, mpris_factory):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            ATTEMPT,
            """
        manager = Playerctl.PlayerManager()
        kept = []
        manager.connect('name-appeared', lambda m, n: None)
        player = Playerctl.Player.new_from_name(manager.props.player_names[0])
        manager.manage_player(player)
        manager.connect('player-vanished', lambda m, p: kept.append(p))
        loop = GLib.MainLoop()
        manager.connect('player-vanished', lambda m, p: loop.quit())
        GLib.timeout_add(3000, loop.quit)
        out('ready')
        loop.run()
        out('players', len(manager.props.players), len(kept))
        attempt('play', player.play)
        attempt('position', player.get_position)
        attempt('title', player.get_title)
        attempt('kept', lambda: kept[0].props.player_name)
        del kept
        GLib.MainContext.default().iteration(False)
        attempt('after-drop', lambda: player.props.player_name)
        """,
        ),
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    assert parsed['play'][0] == 'gerror'
    assert parsed['position'][0] == 'gerror'
    assert parsed['title'][0] == 'gerror'
    assert parsed['after-drop'] == ('ok', "'lib'")
    assert result.stdout.splitlines()[0] == 'players 0 1'


async def test_managing_a_player_that_already_vanished(
    gi_start, mpris_factory
):
    [mpris] = await mpris_factory('lib')

    result = await run_after_vanish(
        gi_start,
        mpris,
        compose(
            ATTEMPT,
            AWAIT_EXIT,
            """
        manager = Playerctl.PlayerManager()
        manager.manage_player(player)
        out('players', len(manager.props.players))
        GLib.timeout_add(300, lambda: loop.quit())
        loop.run()
        out('players', len(manager.props.players))
        attempt('play', player.play)
        """,
        ),
    )

    assert_clean(result)
    assert result.stdout.splitlines()[-1].split()[1] == 'gerror'

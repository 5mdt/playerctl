"""US-11.13: As a developer, I want the library to handle instance-only
players, failing metadata fetches and wrongly typed property changes without
aborting my program."""

import asyncio

import pytest
from dbus_next import Variant

from ..helpers.gi import FATAL_CRITICALS
from ..helpers.mpris import PLAYER_INTERFACE, gated

WRONG_TYPES = [
    ('Volume', Variant('s', 'loud')),
    ('Shuffle', Variant('s', 'yes')),
    ('LoopStatus', Variant('i', 3)),
    ('PlaybackStatus', Variant('i', 1)),
]


async def test_player_new_matches_an_instance_only_player(
    gi_run, mpris_factory
):
    # audit: playerctl-player.c:1114 a PlayerctlPlayerName was read as a
    # gchar *, giving a garbage bus name for `new('vlc')` when only
    # vlc.instanceN is running
    [mpris] = await mpris_factory('vlc.instance123')

    result = await gi_run("""
        player = Playerctl.Player.new('vlc')
        player.play()
    """)

    assert result.returncode == 0, result.stderr
    assert mpris.play_called


async def test_failing_metadata_fetch_does_not_abort_the_client(
    gi_run, mpris_factory
):
    # audit: playerctl-player.c:597 g_error() on a failed Metadata fetch
    [mpris] = await mpris_factory(
        'fail',
        prepare=gated(
            lambda g: (
                g.strip_get_all(PLAYER_INTERFACE, 'Metadata'),
                g.fail('Get', arg=PLAYER_INTERFACE),
            )
        ),
    )

    result = await gi_run("""
        player = Playerctl.Player.new('fail')
        try:
            out('metadata', player.props.metadata)
        except GLib.Error as e:
            out('error', e.message)
        out('alive')
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == 'alive'


@pytest.mark.parametrize('getter', ['get_artist', 'get_title', 'get_album'])
async def test_metadata_getters_report_errors(getter, gi_run, mpris_factory):
    # audit: playerctl-player.c:1741,1766,1791 NULL was passed instead of err
    [mpris] = await mpris_factory(
        'fail',
        prepare=gated(
            lambda g: (
                g.strip_get_all(PLAYER_INTERFACE, 'Metadata'),
                g.fail('Get', arg=PLAYER_INTERFACE),
            )
        ),
    )

    result = await gi_run(f"""
        player = Playerctl.Player.new('fail')
        try:
            player.{getter}()
            out('no error')
        except GLib.Error as e:
            out('error')
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['error']


@pytest.mark.parametrize(('prop', 'value'), WRONG_TYPES)
async def test_wrongly_typed_property_change_is_ignored(
    prop, value, gi_start, mpris_factory
):
    # audit: playerctl-player.c:199-314 g_variant_lookup_value(..., NULL)
    # without a type: GLib criticals and garbage values
    [mpris] = await mpris_factory('typed')
    proc = await gi_start(
        """
        player = Playerctl.Player.new('typed')
        player.connect('volume', lambda p, v: out('volume', v))
        player.connect('shuffle', lambda p, s: out('shuffle', s))
        player.connect('loop-status', lambda p, s: out('loop-status'))
        player.connect('playback-status', lambda p, s: out('playback-status'))
        run_loop()
        """,
        env=FATAL_CRITICALS,
    )

    await mpris.send_properties_changed({prop: value})
    await mpris.emit_properties(volume=0.125)

    try:
        line = await asyncio.wait_for(proc.queue.get(), 2)
    except asyncio.TimeoutError:
        line = None
    assert line == 'volume 0.125', (
        f'no valid change seen, the library exited with {proc.proc.returncode}'
    )


@pytest.mark.timeout(60)
async def test_property_changes_do_not_leak(gi_start, mpris_factory):
    # audit: playerctl-player.c:192 g_debug("%s", g_variant_print(...)) leaks
    # the printed string on every PropertiesChanged (cf. 5mdt/playerctl#51)
    [mpris] = await mpris_factory('leak')
    proc = await gi_start(
        """
        count = 0
        base = 0

        def rss_kib():
            with open('/proc/self/statm') as f:
                return int(f.read().split()[1]) * 4

        def on_volume(player, volume):
            global count, base
            count += 1
            if count == 300:
                base = rss_kib()
            if count == 2300:
                out('grew', rss_kib() - base)

        player = Playerctl.Player.new('leak')
        player.connect('volume', on_volume)
        run_loop(30000)
        """,
        env={'G_MESSAGES_DEBUG': 'playerctl'},
    )

    for i in range(2300):
        await mpris.emit_properties(volume=(i + 1) / 4000)

    line = await asyncio.wait_for(proc.queue.get(), 20)
    assert line.startswith('grew'), line
    assert int(line.split()[1]) < 64, f'grew by {line.split()[1]} KiB'


async def test_manager_handles_new_names_while_managing_players(
    gi_start, mpris_factory
):
    # audit: playerctl-player-manager.c:357 the name-appeared path searched
    # the list of PlayerctlPlayer objects as if it held PlayerctlPlayerName
    await mpris_factory('mgr_a')
    proc = await gi_start(
        """
        manager = Playerctl.PlayerManager()
        for name in Playerctl.list_players():
            manager.manage_player(Playerctl.Player.new_from_name(name))
        manager.connect('name-appeared', lambda m, n: out('name-appeared', n.instance))
        run_loop()
        """,
        env=FATAL_CRITICALS,
    )

    await mpris_factory('mgr_b')

    assert await proc.queue.get() == 'name-appeared mgr_b'
    assert await proc.proc.wait() == 0

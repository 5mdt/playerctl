"""US-11.12: As a developer, I want to connect to a player without loading all
of its properties first, so that a slow player does not delay me (issue #10)."""

import asyncio

from ..helpers.mpris import PLAYER_INTERFACE, PROPERTIES_INTERFACE, gated

CAN_PROPERTIES = [
    'can_control',
    'can_play',
    'can_pause',
    'can_seek',
    'can_go_next',
    'can_go_previous',
]

LAZY = "Playerctl.Player(player_name='lib', load_properties=False)"


def _hold_get_all(gate):
    gate.hold_get_all(PLAYER_INTERFACE)


async def test_load_properties_is_on_by_default(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new('lib')
        out(player.props.load_properties)
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'True'


async def test_slow_get_all_does_not_delay_creation(gi_run, mpris_factory):
    await mpris_factory('lib', prepare=gated(_hold_get_all))

    result = await asyncio.wait_for(
        gi_run(f"""
            player = {LAZY}
            out(player.props.load_properties, player.props.player_name)
        """),
        3,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'False lib'


async def test_can_properties_are_read_from_the_player(gi_run, mpris_factory):
    gets = []

    def configure(gate):
        gate.hold_get_all(PLAYER_INTERFACE)

        def count(reply):
            gets.append(reply)
            return reply

        gate.rewrite('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE, count)

    [mpris] = await mpris_factory('lib', prepare=gated(configure))
    await mpris.emit_properties(can_play=False, can_go_next=False)

    result = await asyncio.wait_for(
        gi_run(f"""
            player = {LAZY}
            out(*[getattr(player.props, name) for name in {CAN_PROPERTIES}])
        """),
        3,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'True False True True False True'
    assert len(gets) == len(CAN_PROPERTIES)


async def test_can_properties_are_never_stale(gi_start, mpris_factory):
    # GDBus does not keep the cache of such a proxy up to date, so every read
    # asks the player
    [mpris] = await mpris_factory('lib', prepare=gated(_hold_get_all))
    proc = await gi_start(f"""
        player = {LAZY}
        GLib.idle_add(lambda: out('can_play', player.props.can_play))
        GLib.timeout_add(
            1000, lambda: out('can_play', player.props.can_play))
        run_loop()
    """)

    assert await proc.queue.get() == 'can_play True'
    await mpris.emit_properties(can_play=False)

    assert await proc.queue.get() == 'can_play False'


async def test_failed_get_reads_as_false(gi_run, mpris_factory):
    def configure(gate):
        gate.hold_get_all(PLAYER_INTERFACE)
        gate.fail('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE)

    await mpris_factory('lib', prepare=gated(configure))

    result = await asyncio.wait_for(
        gi_run(f"""
            player = {LAZY}
            out(player.props.can_play, player.props.can_go_next)
        """),
        3,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'False False'

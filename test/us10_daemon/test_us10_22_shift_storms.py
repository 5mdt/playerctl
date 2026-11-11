"""US-10.22: As a user with several clients (key bindings, status bars,
scripts), I want playerctld to stay consistent when many of them shift and
unshift at once: PlayerNames always lists exactly the live players, and the
ActivePlayerChange signals stay paired and agree with that order."""

import asyncio

import pytest
from dbus_next import MessageType

from ..helpers.daemon import (
    player_names,
    playerctld_cli,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    OPTIONAL_NOISE,
    PREFIX,
    PlayerCollector,
    assert_healthy,
    close_bus,
    new_bus,
    shift_names,
)


async def make_players(mpris_factory, daemon_bus, count):
    '''Start `count` players one after the other; returns the PlayerNames
    order the daemon settled on (newest first).'''
    names = [f'p{i:02d}' for i in range(count)]
    for name in names:
        [mpris] = await mpris_factory(name)
        await mpris.set_artist_title('artist', name)
    return await wait_for_players(daemon_bus, [PREFIX + n for n in names])


def rotate(order, steps):
    '''Reference model: Shift = head to the back, Unshift = back to the head.'''
    if not order:
        return []
    steps %= len(order)
    return order[steps:] + order[:steps]


async def test_shift_storm_of_20_clients_is_a_pure_rotation(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 5)
    collector = await PlayerCollector.start(bus_address)
    buses = [await new_bus(bus_address) for _ in range(20)]

    async def client(bus):
        for _ in range(10):
            reply = await shift_names(bus)
            assert reply.message_type == MessageType.METHOD_RETURN, reply.body
            assert reply.body[0] in initial

    await asyncio.gather(*(client(b) for b in buses))

    await collector.wait_quiet()
    assert await player_names(daemon_bus) == rotate(initial, 200)
    assert collector.pairing_errors() == []
    # every shift moved the active player (5 players), so it was announced
    assert len(collector.end_names()) == 200
    # the announced active players follow the rotation, in bus order
    assert collector.end_names() == [
        rotate(initial, i)[0] for i in range(1, 201)
    ]
    assert_healthy(playerctld)
    for bus in buses:
        await close_bus(bus)
    await collector.close()


async def test_mixed_shift_unshift_storm_matches_the_model(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 4)
    collector = await PlayerCollector.start(bus_address)
    buses = [await new_bus(bus_address) for _ in range(20)]

    async def client(index, bus):
        for step in range(8):
            reverse = (index + step) % 3 == 0
            reply = await shift_names(bus, reverse=reverse)
            assert reply.message_type == MessageType.METHOD_RETURN, reply.body
            # whatever interleaving, a permutation is what the clients see
            names = await player_names(bus)
            assert sorted(names) == sorted(initial)

    await asyncio.gather(*(client(i, b) for i, b in enumerate(buses)))

    net = sum(
        -1 if (i + s) % 3 == 0 else 1 for i in range(20) for s in range(8)
    )
    await collector.wait_quiet()
    assert await player_names(daemon_bus) == rotate(initial, net)
    assert collector.pairing_errors() == []
    assert_healthy(playerctld)
    for bus in buses:
        await close_bus(bus)
    await collector.close()


async def test_shift_returns_the_name_that_becomes_active(
    playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 3)

    for step in range(1, 7):
        reply = await shift_names(daemon_bus)
        assert reply.body == [rotate(initial, step)[0]]
    for step in range(5, -1, -1):
        reply = await shift_names(daemon_bus, reverse=True)
        assert reply.body == [rotate(initial, step)[0]]


async def test_shift_then_unshift_is_the_identity(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 6)

    for _ in range(25):
        await shift_names(daemon_bus)
    for _ in range(25):
        await shift_names(daemon_bus, reverse=True)

    assert await player_names(daemon_bus) == initial


@pytest.mark.parametrize('reverse', [False, True])
async def test_shift_with_no_player_is_a_noactiveplayer_error(
    bus_address, playerctld, daemon_bus, reverse
):
    collector = await PlayerCollector.start(bus_address)

    for _ in range(5):
        reply = await shift_names(daemon_bus, reverse=reverse)
        assert reply.message_type == MessageType.ERROR
        assert reply.error_name == 'org._5mdt.playerctld.NoActivePlayer'
    code, _, stderr = await playerctld_cli(
        bus_address, 'unshift' if reverse else 'shift'
    )

    assert code == 1
    assert 'No player is being controlled' in stderr
    assert collector.events == []
    assert await player_names(daemon_bus) == []
    assert_healthy(playerctld)
    await collector.close()


@pytest.mark.parametrize('reverse', [False, True])
async def test_shift_with_one_player_is_a_silent_success(
    bus_address, playerctld, daemon_bus, mpris_factory, reverse
):
    [mpris] = await mpris_factory('solo')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'solo'])
    collector = await PlayerCollector.start(bus_address)

    for _ in range(10):
        reply = await shift_names(daemon_bus, reverse=reverse)
        assert reply.message_type == MessageType.METHOD_RETURN
        assert reply.body == [PREFIX + 'solo']

    await collector.wait_quiet()
    # nothing changed, so nothing is announced
    assert collector.events == []
    assert await player_names(daemon_bus) == [PREFIX + 'solo']
    assert_healthy(playerctld)
    await collector.close()


async def test_unshift_past_the_ends_wraps_around(
    playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 3)

    # three unshifts walk once around the ring and are back at the start
    seen = []
    for _ in range(3):
        reply = await shift_names(daemon_bus, reverse=True)
        seen.append(reply.body[0])

    assert seen == [initial[2], initial[1], initial[0]]
    assert await player_names(daemon_bus) == initial


async def test_shift_from_the_cli_while_clients_shift_over_dbus(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 4)
    buses = [await new_bus(bus_address) for _ in range(4)]

    async def dbus_client(bus):
        for _ in range(10):
            await shift_names(bus)

    codes = await asyncio.gather(
        *(dbus_client(b) for b in buses),
        *(playerctld_cli(bus_address, 'shift') for _ in range(6)),
    )

    for result in codes[4:]:
        assert result[0] == 0, result
    assert await player_names(daemon_bus) == rotate(initial, 46)
    assert_healthy(playerctld)
    for bus in buses:
        await close_bus(bus)


async def test_active_player_signal_names_match_the_head_of_player_names(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    initial = await make_players(mpris_factory, daemon_bus, 4)
    collector = await PlayerCollector.start(bus_address)

    for _ in range(9):
        await shift_names(daemon_bus)
    await collector.wait_quiet()

    # in each change the PlayerNames announcement already has the new active
    # player first, and Begin/End carry that very name
    groups = []
    current = []
    for kind, value in collector.events:
        current.append((kind, value))
        if kind == 'End':
            groups.append(current)
            current = []
    assert len(groups) == 9
    for i, group in enumerate(groups, 1):
        order = rotate(initial, i)
        assert group[0] == ('Begin', order[0])
        assert ('Names', order) in group
        assert group[-1] == ('End', order[0])
    await collector.close()


async def test_players_dying_during_a_shift_storm_keep_a_permutation(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    players = []
    for i in range(6):
        [mpris] = await mpris_factory(f'p{i}')
        await mpris.set_artist_title('artist', f'p{i}')
        players.append(mpris)
    await wait_for_players(daemon_bus, [PREFIX + f'p{i}' for i in range(6)])
    collector = await PlayerCollector.start(bus_address)
    stop = False

    async def shifter():
        bus = await new_bus(bus_address)
        while not stop:
            reply = await shift_names(
                bus, reverse=bool(len(collector.events) % 2)
            )
            if reply.message_type == MessageType.ERROR:
                assert reply.error_name.endswith('NoActivePlayer')
                break
            names = await player_names(bus)
            assert len(names) == len(set(names))
        await close_bus(bus)

    tasks = [asyncio.ensure_future(shifter()) for _ in range(5)]
    for mpris in players[:5]:
        await asyncio.sleep(0.03)
        await mpris.disconnect()
    stop = True
    await asyncio.gather(*tasks)

    await wait_for_players(daemon_bus, [PREFIX + 'p5'])
    await collector.wait_quiet()
    assert collector.pairing_errors() == []
    # a shift can make a player active just after it died
    assert_healthy(
        playerctld,
        allow=OPTIONAL_NOISE + ('could not update player position',),
    )
    await collector.close()


async def test_shift_storm_does_not_disturb_proxying(
    bus_address, playerctld, daemon_bus, mpris_factory, playerctl
):
    initial = await make_players(mpris_factory, daemon_bus, 3)
    buses = [await new_bus(bus_address) for _ in range(6)]

    async def client(bus):
        for _ in range(10):
            await shift_names(bus)

    await asyncio.gather(*(client(b) for b in buses))
    result = await playerctl.run('-p playerctld status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'
    assert await player_names(daemon_bus) == rotate(initial, 60)
    for bus in buses:
        await close_bus(bus)

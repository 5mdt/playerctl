"""US-10.28: As a user, I want playerctld's idea of which player is active
and which players exist to always match what really happened on the bus,
whatever the order of players appearing, vanishing, changing and being
shifted (checked against a small reference model with seeded random
operation sequences)."""

import random

import pytest

from ..helpers.sanitizer import skip_rss_check_under_asan
from ..helpers.daemon import (
    player_names,
    wait_for_player_names,
)
from ..helpers.daemon_attack import (
    PREFIX,
    PlayerCollector,
    assert_healthy,
    shift_names,
    vm_rss_kb,
)

SEEDS = [1, 2, 3, 4, 5, 6, 7, 8]
STEPS = 30


class Model:
    '''Reference: list of bus names, most recently active first.'''

    def __init__(self):
        self.order = []

    @property
    def head(self):
        return self.order[0] if self.order else ''

    def activate(self, name):
        if name in self.order:
            self.order.remove(name)
        self.order.insert(0, name)

    def remove(self, name):
        self.order.remove(name)

    def shift(self, reverse):
        if self.order:
            if reverse:
                self.order.insert(0, self.order.pop())
            else:
                self.order.append(self.order.pop(0))


async def run_sequence(seed, steps, bus_address, daemon_bus, mpris_factory):
    rng = random.Random(seed)
    model = Model()
    live = {}  # short name -> mock player
    expected_ends = []
    expected_names = []
    collector = await PlayerCollector.start(bus_address)
    counter = 0

    async def settle_to_model():
        await wait_for_player_names(daemon_bus, model.order)

    for step in range(steps):
        head_before = model.head
        ops = ['add', 'change', 'shift', 'unshift', 'remove', 'change']
        op = rng.choice(ops)
        if op in ('remove', 'change') and not live:
            op = 'add'
        if op == 'add' and len(live) >= 6:
            op = 'remove'

        if op == 'add':
            name = f'p{rng.randrange(8)}'
            while name in live:
                name = f'p{rng.randrange(8)}'
            [mock] = await mpris_factory(name)
            counter += 1
            await mock.set_artist_title('artist', f'title{counter}')
            live[name] = mock
            model.activate(PREFIX + name)
            await settle_to_model()
        elif op == 'remove':
            name = rng.choice(sorted(live))
            await live.pop(name).disconnect()
            model.remove(PREFIX + name)
            await settle_to_model()
        elif op == 'change':
            name = rng.choice(sorted(live))
            counter += 1
            kind = rng.choice(['volume', 'status', 'title'])
            mock = live[name]
            if kind == 'volume':
                await mock.emit_properties(volume=counter / 1000)
            elif kind == 'status':
                status = (
                    'Paused'
                    if mock.playback_status == 'Playing'
                    else 'Playing'
                )
                await mock.emit_properties(playback_status=status)
            else:
                await mock.set_artist_title('artist', f'title{counter}')
            model.activate(PREFIX + name)
            await settle_to_model()
        else:
            reverse = op == 'unshift'
            reply = await shift_names(daemon_bus, reverse=reverse)
            model.shift(reverse)
            if model.order:
                assert reply.body == [model.head], (step, op)
            else:
                assert reply.message_type.name == 'ERROR'
            await settle_to_model()

        if model.head != head_before:
            expected_ends.append(model.head)
            expected_names.append(list(model.order))
        assert await player_names(daemon_bus) == model.order, (seed, step, op)

    await collector.wait_quiet()
    return collector, expected_ends, expected_names


@pytest.mark.parametrize('seed', SEEDS)
async def test_random_operations_match_the_reference_model(
    bus_address, playerctld, daemon_bus, mpris_factory, seed
):
    collector, expected_ends, expected_names = await run_sequence(
        seed, STEPS, bus_address, daemon_bus, mpris_factory
    )

    assert collector.pairing_errors() == []
    assert collector.end_names() == expected_ends
    # each announced PlayerNames is the model order at that moment
    assert [v for k, v in collector.events if k == 'Names'] == expected_names
    assert_healthy(
        playerctld,
        allow=(
            'could not update player position',
            'could not get properties',
            'could not get org.mpris',
        ),
    )
    await collector.close()


@pytest.mark.parametrize('seed', [11, 12, 13])
async def test_announced_properties_equal_those_of_the_active_player(
    bus_address, playerctld, daemon_bus, mpris_factory, seed
):
    rng = random.Random(seed)
    collector = await PlayerCollector.start(bus_address)
    mocks = {}
    for i in range(4):
        [mock] = await mpris_factory(f'q{i}')
        await mock.set_artist_title('artist', f'title{i}')
        mocks[PREFIX + f'q{i}'] = mock
    await wait_for_player_names(
        daemon_bus, [PREFIX + f'q{i}' for i in (3, 2, 1, 0)]
    )

    for step in range(25):
        name = rng.choice(sorted(mocks))
        mock = mocks[name]
        choice = rng.choice(['volume', 'status', 'loop', 'shuffle', 'title'])
        # every change is a real change: see BUG-D9 for what an unchanged
        # value does
        if choice == 'volume':
            await mock.emit_properties(volume=mock.volume + 0.001 + step / 1e4)
        elif choice == 'status':
            others = [
                x
                for x in ('Playing', 'Paused', 'Stopped')
                if x != mock.playback_status
            ]
            await mock.emit_properties(playback_status=rng.choice(others))
        elif choice == 'loop':
            others = [
                x
                for x in ('None', 'Track', 'Playlist')
                if x != mock.loop_status
            ]
            await mock.emit_properties(loop_status=rng.choice(others))
        elif choice == 'shuffle':
            await mock.emit_properties(shuffle=not mock.shuffle)
        else:
            await mock.set_artist_title('artist', f'title-{step}')
        if rng.random() < 0.3:
            await shift_names(daemon_bus, reverse=rng.random() < 0.5)
        await collector.wait_quiet(quiet=0.05)

        active = (await player_names(daemon_bus))[0]
        real = mocks[active]
        shown = {k: v.value for k, v in collector.player_props.items()}
        # properties changed while another player was active are what the
        # daemon announces when this one becomes active again
        assert shown['Volume'] == real.volume, (step, choice)
        assert shown['PlaybackStatus'] == real.playback_status
        assert shown['LoopStatus'] == real.loop_status
        assert shown['Shuffle'] == real.shuffle
        title = shown['Metadata']['xesam:title'].value
        assert title == real.metadata['xesam:title'].value
    await collector.close()


async def test_memory_stays_flat_over_a_long_shift_storm(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    skip_rss_check_under_asan()
    for i in range(5):
        [mock] = await mpris_factory(f'm{i}')
        await mock.set_artist_title('artist', f'title{i}')
    await wait_for_player_names(
        daemon_bus, [PREFIX + f'm{i}' for i in (4, 3, 2, 1, 0)]
    )
    for _ in range(300):
        await shift_names(daemon_bus)
    before = vm_rss_kb(playerctld.pid)

    for _ in range(1200):
        await shift_names(daemon_bus, reverse=bool(_ % 2 == 0 and _ % 3 == 0))

    grown = vm_rss_kb(playerctld.pid) - before
    assert grown < 1024, f'RSS grew by {grown} kB over 1200 shifts'

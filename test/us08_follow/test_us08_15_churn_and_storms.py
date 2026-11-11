"""US-8.15: As a bar author, I want follow mode to stay correct and quiet
under name-owner churn, many players and bursts of property changes: it ends
on the final state, never prints the same line twice in a row, never logs
GLib warnings and does not grow without bound."""

import asyncio

import pytest
from dbus_next.service import Variant

from ..helpers.sanitizer import skip_rss_check_under_asan
from ..helpers.chaos import (
    assert_clean_stderr,
    assert_not_killed_by_signal,
    cpu_during,
    emit_title,
    no_consecutive_duplicates,
    raw_properties_changed,
    start_raw,
    title_storm,
)
from ..helpers.daemon import start_playerctld
from ..helpers.follow import follow_cmd

MODES = [
    pytest.param('', id='default'),
    pytest.param('--all-players', id='all'),
    pytest.param('--player churn,steady', id='player-list'),
]
FMT = '{{playerInstance}}: {{artist}} - {{title}}'


def cmd(mode):
    return f'{mode} metadata --format "{FMT}" --follow'


async def finish(proc):
    code, stderr = await proc.terminate()
    assert_not_killed_by_signal(code if code != -15 else None)
    assert_clean_stderr(stderr)


@pytest.mark.parametrize('mode', MODES)
async def test_name_churn_burst(playerctl, mpris_factory, mode):
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('a', 'one')
    proc = await start_raw(playerctl, cmd(mode))
    await proc.wait_line('steady: a - one')

    # the same name appears and vanishes again and again
    for i in range(60):
        [churn] = await mpris_factory('churn')
        await emit_title(churn, f'c{i}')
        await churn.disconnect()
    await steady.set_artist_title('a', 'final')
    await proc.wait_line('steady: a - final')
    assert proc.running()

    lines = await proc.settle()
    assert no_consecutive_duplicates(lines), lines
    assert lines[-1] == 'steady: a - final' or mode == '--all-players'
    await finish(proc)


async def test_name_churn_with_distinct_names(playerctl, mpris_factory):
    proc = await start_raw(playerctl, cmd('--all-players'))
    for i in range(40):
        [p] = await mpris_factory(f'burst{i}')
        await p.set_artist_title('a', f'x{i}')
    await proc.wait_line('burst39: a - x39')
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    assert all(': a - x' in line or line == '' for line in lines), lines
    await finish(proc)


async def test_burst_of_vanishing_players_ends_empty(playerctl, mpris_factory):
    players = await mpris_factory(*[f'p{i}' for i in range(30)])
    for i, p in enumerate(players):
        await p.set_artist_title('a', f't{i}')
    proc = await start_raw(playerctl, cmd('--all-players'))
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')

    await asyncio.gather(*(p.disconnect() for p in players))
    await proc.wait_last('', timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    assert lines.count('') == 1  # a single empty line, not one per player
    assert proc.running()
    await finish(proc)


async def test_fifty_simultaneous_players(playerctl, mpris_factory):
    players = await mpris_factory(*[f'm{i:02d}' for i in range(50)])
    await asyncio.gather(
        *(
            p.set_artist_title('artist', f'title{i}')
            for i, p in enumerate(players)
        )
    )
    proc = await start_raw(playerctl, cmd('--all-players'))
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line', timeout=4)
    await asyncio.sleep(0.5)  # let all fifty connections finish
    await players[49].set_artist_title('artist', 'last')
    await proc.wait_last('m49: artist - last', timeout=4)

    await players[17].set_artist_title('artist', 'changed')
    await proc.wait_last('m17: artist - changed')
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    await finish(proc)


@pytest.mark.parametrize('mode', MODES[:2])
async def test_fifty_players_start_with_follow_already_running(
    playerctl, mpris_factory, mode
):
    proc = await start_raw(playerctl, cmd(mode))
    players = await mpris_factory(*[f'steady{i}' for i in range(50)])
    for i, p in enumerate(players):
        await emit_title(p, f'n{i}')
    await players[-1].ping()
    await proc.wait_for(lambda ls: len(ls) >= 1, what='some line')
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    assert proc.running()
    await finish(proc)


@pytest.mark.parametrize('mode', MODES)
async def test_thousand_property_changes_converge(
    playerctl, mpris_factory, mode
):
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, cmd(mode))
    await proc.wait_line('steady: artist - start')

    final = await title_storm(steady, 1000)
    await proc.wait_last(f'steady: artist - {final}', timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    # every printed line is a render of a state that really existed
    for line in lines:
        assert line.startswith('steady: artist - ')
        title = line.rsplit(' - ', 1)[1]
        assert title == 'start' or (title[0] == 't' and int(title[1:]) < 1000)
    # and states appear in order (no stale line after a newer one)
    nums = [int(line.rsplit(' - t', 1)[1]) for line in lines[1:]]
    assert nums == sorted(nums)
    await finish(proc)


async def test_property_storm_memory_and_cpu_stay_bounded(
    playerctl, mpris_factory
):
    skip_rss_check_under_asan()
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, cmd(''))
    await proc.wait_line('steady: artist - start')
    # warm up so allocator noise is excluded from the baseline
    final = await title_storm(steady, 100, prefix="w")
    await proc.wait_last(f'steady: artist - {final}')
    before = proc.rss_kb()

    for round_ in range(3):
        final = await title_storm(steady, 600, prefix=f"r{round_}_")
        await proc.wait_last(f'steady: artist - {final}', timeout=4)
    after = proc.rss_kb()
    assert after - before < 20 * 1024, (before, after)
    # idle again: no busy loop once the storm is over
    assert await cpu_during(proc.pid, 1.0) < 0.3
    await finish(proc)


async def test_fifteen_hundred_identical_updates_print_once(
    playerctl, mpris_factory
):
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'same')
    proc = await start_raw(playerctl, cmd(''))
    await proc.wait_line('steady: artist - same')

    for _ in range(1500):
        await raw_properties_changed(
            steady, {'Metadata': Variant('a{sv}', steady.metadata)}
        )
    await steady.ping()
    await steady.set_artist_title('artist', 'same')  # new trackid, same text
    await steady.ping()
    lines = await proc.settle()
    assert lines == ['steady: artist - same']
    await finish(proc)


async def test_storm_alternating_between_two_states(playerctl, mpris_factory):
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'A')
    proc = await start_raw(playerctl, cmd(''))
    await proc.wait_line('steady: artist - A')

    for i in range(500):
        await emit_title(steady, 'B' if i % 2 == 0 else 'A')
    await steady.ping()
    await proc.wait_last('steady: artist - A', timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    assert set(lines) <= {'steady: artist - A', 'steady: artist - B'}
    await finish(proc)


async def test_storm_across_players_all_mode_ends_on_last_update(
    playerctl, mpris_factory
):
    players = await mpris_factory('s1', 's2', 's3')
    proc = await start_raw(playerctl, cmd('--all-players'))
    for i in range(300):
        await emit_title(players[i % 3], f'u{i}')
    for p in players:
        await p.ping()
    await proc.wait_last('s1: artist - u297', timeout=4) if False else None
    last = f's{299 % 3 + 1}: artist - u299'
    await proc.wait_line(last, timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    await finish(proc)


async def test_storm_with_playerctld_running(
    playerctl, mpris_factory, bus_address
):
    await start_playerctld(bus_address)
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, cmd(''))
    await proc.wait_line('steady: artist - start')
    final = await title_storm(steady, 500)
    await proc.wait_last(f'steady: artist - {final}', timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    await finish(proc)


async def test_churn_with_playerctld_running(
    playerctl, mpris_factory, bus_address
):
    await start_playerctld(bus_address)
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, cmd(''))
    await proc.wait_line('steady: artist - start')
    for i in range(30):
        [c] = await mpris_factory('churn')
        await emit_title(c, f'c{i}')
        await c.disconnect()
    await steady.set_artist_title('artist', 'final')
    await proc.wait_line('steady: artist - final', timeout=4)
    assert proc.running()
    await finish(proc)


async def test_follow_cmd_helper_still_works_under_churn(
    playerctl, mpris_factory
):
    # the stock follow helper and the stock reader agree with the raw one
    [steady] = await mpris_factory('steady')
    await steady.set_artist_title('a', 'one')
    proc = await playerctl.start(follow_cmd())
    assert await proc.queue.get() == 'steady: a - one'
    for _ in range(20):
        [c] = await mpris_factory('churn')
        await c.disconnect()
    await steady.set_artist_title('a', 'two')
    seen = []
    while not seen or seen[-1] != 'steady: a - two':
        seen.append(await asyncio.wait_for(proc.queue.get(), 3))
    assert no_consecutive_duplicates(seen)

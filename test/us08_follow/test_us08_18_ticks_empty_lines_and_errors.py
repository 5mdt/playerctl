"""US-8.18: As a bar author, I want `position` ticks to run only while they
can change the output, the empty line to be printed exactly once when the
last player leaves, and a template that fails after a property change to stop
follow mode, however the players come and go.

How ticks are produced: when the template (or the command) uses `position`,
`playerctl-cli.c` installs one `g_timeout_add (POSITION_TICK_MS)` of one
second that re-renders the current player. It is a monotonic GLib timer: a
wall-clock jump does not change it. Paused or stopped players render the same
position, so the duplicate suppression prints nothing."""

import asyncio

import pytest

from ..helpers.chaos import (
    assert_clean_stderr,
    cpu_during,
    no_consecutive_duplicates,
    start_raw,
)
from ..helpers.daemon import start_playerctld

POS = 'metadata --format "{{status}} {{duration(position)}}" --follow'


async def finish(proc):
    code, stderr = await proc.terminate()
    assert code in (-15, 0), (code, stderr)
    assert_clean_stderr(stderr)


async def test_playing_ticks_keep_coming(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Playing'
    p.position = 0
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Playing 0:00')
    await proc.wait_line('Playing 0:01', timeout=2.5)
    await proc.wait_line('Playing 0:02', timeout=2.5)
    assert no_consecutive_duplicates(proc.lines())
    await finish(proc)


async def test_no_ticks_while_paused(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    p.position = 7000000
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Paused 0:07')
    await asyncio.sleep(2.2)  # at least two timer expirations
    assert proc.lines() == ['Paused 0:07']
    await finish(proc)


async def test_no_ticks_while_stopped(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Stopped'
    p.position = 7000000
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line(
        'Stopped 0:00'
    )  # a stopped player reports no position
    await asyncio.sleep(2.2)
    assert proc.lines() == ['Stopped 0:00']
    await finish(proc)


async def test_pause_play_cycle_ticks_resume_only_when_playing(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Playing'
    p.position = 0
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Playing 0:00')
    await p.emit_properties(playback_status='Paused', position=0)
    await proc.wait_line('Paused 0:00')
    n = len(proc.lines())
    await asyncio.sleep(2.2)
    assert len(proc.lines()) == n
    await p.emit_properties(playback_status='Playing')
    await proc.wait_for(
        lambda ls: any(line.startswith('Playing 0:0') for line in ls[n:]),
        timeout=2.5,
        what='playing line',
    )
    await finish(proc)


async def test_tick_cpu_is_low_while_paused(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Paused 0:00')
    assert await cpu_during(proc.pid, 1.5) < 0.2
    await finish(proc)


async def test_tick_when_player_vanishes_prints_one_empty_line(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Playing'
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Playing 0:00')
    await p.disconnect()
    await proc.wait_last('')
    await asyncio.sleep(2.3)  # ticks with no player must not print again
    assert proc.lines().count('') == 1
    assert proc.running()
    await finish(proc)


async def test_tick_with_many_players_all_mode_does_not_flood(
    playerctl, mpris_factory
):
    players = await mpris_factory(*[f'p{i}' for i in range(10)])
    for p in players:
        p.playback_status = 'Paused'
        await p.set_artist_title('a', 't')
    proc = await start_raw(
        playerctl,
        '--all-players metadata --format "{{playerName}} {{duration(position)}}" --follow',
    )
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    await asyncio.sleep(0.3)
    n = len(proc.lines())
    await asyncio.sleep(2.3)
    assert len(proc.lines()) == n
    await finish(proc)


async def test_position_far_in_the_future_and_negative_render(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    p.position = 2**62
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    await p.emit_properties(position=-5)
    await p.set_artist_title('a', 'u')
    await asyncio.sleep(0.3)
    assert proc.running()
    await finish(proc)


# --- empty line / no players -----------------------------------------------


async def test_last_player_leaving_prints_one_empty_line_then_nothing(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, 'status --follow')
    await proc.wait_line('Playing')
    await p.disconnect()
    await proc.wait_last('')
    await asyncio.sleep(0.6)
    assert proc.lines() == ['Playing', '']
    assert await cpu_during(proc.pid, 1.0) < 0.2
    await finish(proc)


async def test_players_come_and_go_empty_line_each_time_only_once(
    playerctl, mpris_factory
):
    proc = await start_raw(playerctl, 'status --follow')
    await asyncio.sleep(0.3)
    expected = []
    for i in range(5):
        [p] = await mpris_factory('test1')
        expected.append('Playing')
        await proc.wait_for(
            lambda ls: len(ls) >= len(expected), what=f'gen {i}'
        )
        await p.disconnect()
        expected.append('')
        await proc.wait_for(lambda ls: len(ls) >= len(expected), what='empty')
    await asyncio.sleep(0.3)
    assert proc.lines() == expected
    await finish(proc)


async def test_empty_line_also_for_format_with_all_players(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 't')
    proc = await start_raw(
        playerctl, '--all-players metadata --format "{{title}}" --follow'
    )
    await proc.wait_line('t')
    await p.disconnect()
    await proc.wait_last('')
    assert proc.lines() == ['t', '']
    await finish(proc)


async def test_follow_nothing_running_exits_on_signal_only(playerctl):
    proc = await start_raw(playerctl, 'status --follow')
    await asyncio.sleep(1.2)
    assert proc.running()
    assert proc.lines() == []
    assert await cpu_during(proc.pid, 1.0) < 0.2
    await finish(proc)


@pytest.mark.parametrize(
    'sel', ['--player test1', '--ignore-player test1', '--player %any', '-a']
)
async def test_one_player_appears_after_start_with_selection(
    playerctl, mpris_factory, sel
):
    proc = await start_raw(playerctl, f'{sel} status --follow')
    await asyncio.sleep(0.3)
    [p] = await mpris_factory('test1')
    [q] = await mpris_factory('other')
    await q.emit_properties(playback_status='Paused')
    if sel == '--ignore-player test1':
        await proc.wait_line('Paused')
        assert proc.lines()[-1] == 'Paused'
        assert no_consecutive_duplicates(proc.lines())
    elif sel == '--player test1':
        await proc.wait_line('Playing')
        assert 'Paused' not in proc.lines()
    else:
        await proc.wait_for(lambda ls: len(ls) >= 1, what='a line')
    await finish(proc)


async def test_ignored_player_churn_prints_nothing(playerctl, mpris_factory):
    proc = await start_raw(playerctl, '--ignore-player noisy status --follow')
    await asyncio.sleep(0.3)
    for _ in range(20):
        [n] = await mpris_factory('noisy')
        await n.emit_properties(playback_status='Paused')
        await n.disconnect()
    assert proc.lines() == []
    assert proc.running()
    await finish(proc)


async def test_instances_come_and_go_with_player_list(
    playerctl, mpris_factory
):
    [a] = await mpris_factory('app.instance1')
    await a.set_artist_title('a', 'one')
    proc = await start_raw(
        playerctl,
        '--player app metadata --format "{{playerInstance}} {{title}}" --follow',
    )
    await proc.wait_line('app.instance1 one')
    for i in range(10):
        [b] = await mpris_factory('app.instance2')
        await b.set_artist_title('a', f'b{i}')
        await b.disconnect()
    await a.set_artist_title('a', 'final')
    await proc.wait_line('app.instance1 final', timeout=4)
    assert no_consecutive_duplicates(await proc.settle())
    await finish(proc)


# --- errors after a property change (story 8.8) ---------------------------------

ERR = 'status --format "{{ 10 / volume }}" --follow'


async def test_render_error_after_change_all_players_exits_1(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    proc = await start_raw(playerctl, '--all-players ' + ERR)
    await proc.wait_line('10.0')
    await p.emit_properties(volume=0.0)
    code, stderr = await proc.exit(timeout=2)
    assert code == 1, (code, stderr)
    assert 'Divide by zero' in stderr


async def test_render_error_for_player_present_at_start(
    playerctl, mpris_factory
):
    # exits 1 straight away: the error happens during the initial render
    [p] = await mpris_factory('test1')
    p.volume = 0.0
    proc = await start_raw(playerctl, ERR)
    code, stderr = await proc.exit(timeout=3)
    assert code == 1
    assert 'Divide by zero' in stderr
    assert 'CRITICAL' not in stderr


async def test_render_error_output_not_printed_before_error_line(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    proc = await start_raw(playerctl, ERR)
    await proc.wait_line('10.0')
    p.volume = 0.0
    await p.emit_properties(volume=0.0, loop_status='Track')
    await asyncio.sleep(0.5)
    assert proc.lines() == ['10.0']  # the failed render prints nothing
    await proc.terminate()  # exit code is 1 or the signal, see story 8.8


# --- playerctld in the mix --------------------------------------------------


async def test_follow_with_playerctld_empty_line_once(
    playerctl, mpris_factory, bus_address
):
    await start_playerctld(bus_address)
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, 'metadata --format "{{title}}" --follow')
    await proc.wait_line('t')
    await p.disconnect()
    await proc.wait_last('', timeout=4)
    await asyncio.sleep(0.5)
    assert proc.lines() == ['t', '']
    await finish(proc)


async def test_follow_with_playerctld_ticks_stop_when_paused(
    playerctl, mpris_factory, bus_address
):
    await start_playerctld(bus_address)
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    await p.set_artist_title('a', 't')
    proc = await start_raw(playerctl, POS)
    await proc.wait_line('Paused 0:00')
    await asyncio.sleep(2.3)
    assert proc.lines() == ['Paused 0:00']
    await finish(proc)


async def test_follow_survives_playerctld_restart(
    playerctl, mpris_factory, bus_address
):
    from ..helpers.daemon import stop_playerctld

    daemon = await start_playerctld(bus_address)
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 'one')
    proc = await start_raw(playerctl, 'metadata --format "{{title}}" --follow')
    await proc.wait_line('one')
    await stop_playerctld(daemon)
    await p.set_artist_title('a', 'two')
    await proc.wait_line('two', timeout=4)
    assert proc.running()
    await finish(proc)

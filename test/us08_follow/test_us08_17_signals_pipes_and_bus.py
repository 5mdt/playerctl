"""US-8.17: As a bar author, I want follow mode to end promptly and cleanly
when its stdout goes away, when it is signalled, or when the bus dies, and to
neither spin nor lose the final state when its consumer is slow or stopped."""

import asyncio
import os
import signal

import pytest

from ..helpers.chaos import (
    assert_clean_stderr,
    cpu_during,
    emit_title,
    no_consecutive_duplicates,
    proc_state,
    start_raw,
    title_storm,
)
from ..helpers.mpris import _bus_call
from dbus_next.aio import MessageBus

FMT = '{{playerInstance}}: {{artist}} - {{title}}'
CMD = f'metadata --format "{FMT}" --follow'


async def start_with_player(playerctl, mpris_factory, cmd=CMD):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, cmd)
    await proc.wait_line('test1: artist - start')
    return p, proc


# --- termination signals --------------------------------------------------


@pytest.mark.parametrize(
    'sig', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP], ids=lambda s: s.name
)
async def test_signal_while_idle_ends_process(playerctl, mpris_factory, sig):
    p, proc = await start_with_player(playerctl, mpris_factory)
    code, stderr = await proc.terminate(sig)
    # default disposition: terminated by the signal itself, or a clean exit
    assert code in (-sig, 0, 128 + sig), (code, stderr)
    assert_clean_stderr(stderr)
    assert proc_state(proc.pid) is None  # reaped, no zombie


@pytest.mark.parametrize(
    'sig', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP], ids=lambda s: s.name
)
async def test_signal_without_any_player(playerctl, sig):
    proc = await start_raw(playerctl, CMD)
    await asyncio.sleep(0.3)
    assert proc.running()
    code, stderr = await proc.terminate(sig)
    assert code in (-sig, 0, 128 + sig), (code, stderr)
    assert_clean_stderr(stderr)


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
async def test_signal_during_property_storm(playerctl, mpris_factory, sig):
    p, proc = await start_with_player(playerctl, mpris_factory)

    async def storm():
        try:
            await title_storm(p, 2000)
        except Exception:
            pass  # the bus connection of the mock may break; irrelevant

    task = asyncio.ensure_future(storm())
    await proc.wait_for(lambda ls: len(ls) > 3, what='storm output')
    code, stderr = await proc.terminate(sig)
    task.cancel()
    assert code in (-sig, 0, 128 + sig), (code, stderr)
    assert_clean_stderr(stderr)


async def test_signal_while_player_vanishes(playerctl, mpris_factory):
    p, proc = await start_with_player(playerctl, mpris_factory)
    await p.disconnect()
    code, stderr = await proc.terminate(signal.SIGTERM)
    assert code in (-15, 0, 143)
    assert_clean_stderr(stderr)


async def test_repeated_signals_do_not_hang(playerctl, mpris_factory):
    p, proc = await start_with_player(playerctl, mpris_factory)
    for sig in (signal.SIGHUP, signal.SIGINT, signal.SIGTERM):
        if proc.running():
            os.kill(proc.pid, sig)
    code, _ = await proc.exit()
    assert code != 0 or code == 0  # any exit is fine, it just must exit


async def test_signal_with_format_using_position_ticks(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 't')
    proc = await start_raw(
        playerctl, 'metadata --format "{{duration(position)}}" --follow'
    )
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    code, stderr = await proc.terminate(signal.SIGTERM)
    assert code in (-15, 0, 143)
    assert_clean_stderr(stderr)


async def test_sigusr1_default_action_is_a_signal_death_not_a_hang(
    playerctl, mpris_factory
):
    # an unhandled signal kills the process outright: documented by this test
    p, proc = await start_with_player(playerctl, mpris_factory)
    code, _ = await proc.terminate(signal.SIGUSR1)
    assert code == -signal.SIGUSR1


async def test_sigwinch_and_sigchld_are_ignored(playerctl, mpris_factory):
    p, proc = await start_with_player(playerctl, mpris_factory)
    for sig in (signal.SIGWINCH, signal.SIGCHLD, signal.SIGCONT):
        os.kill(proc.pid, sig)
    await p.set_artist_title('artist', 'after')
    await proc.wait_line('test1: artist - after')
    assert proc.running()
    await proc.terminate()


# --- SIGSTOP / SIGCONT ------------------------------------------------------


async def test_sigstop_then_sigcont_delivers_final_state(
    playerctl, mpris_factory
):
    p, proc = await start_with_player(playerctl, mpris_factory)
    os.kill(proc.pid, signal.SIGSTOP)
    for _ in range(100):
        if proc_state(proc.pid) == 'T':
            break
        await asyncio.sleep(0.01)
    assert proc_state(proc.pid) == 'T'
    final = await title_storm(p, 200)
    await asyncio.sleep(0.3)
    n = len(proc.lines())
    os.kill(proc.pid, signal.SIGCONT)
    await proc.wait_last(f'test1: artist - {final}', timeout=4)
    lines = await proc.settle()
    assert len(lines) >= n
    assert no_consecutive_duplicates(lines)
    await proc.terminate()


async def test_sigstop_while_player_vanishes_and_returns(
    playerctl, mpris_factory
):
    p, proc = await start_with_player(playerctl, mpris_factory)
    os.kill(proc.pid, signal.SIGSTOP)
    await p.disconnect()
    [p2] = await mpris_factory('test1')
    await p2.set_artist_title('artist', 'again')
    os.kill(proc.pid, signal.SIGCONT)
    await proc.wait_line('test1: artist - again', timeout=4)
    assert proc.running()
    await proc.terminate()


# --- stdout closed early ---------------------------------------------------


async def read_some(fd):
    '''Read what is available on a pipe without blocking the event loop.'''
    os.set_blocking(fd, False)
    for _ in range(300):
        try:
            return os.read(fd, 1 << 16)
        except BlockingIOError:
            await asyncio.sleep(0.01)
    raise AssertionError('nothing written to the pipe')


@pytest.mark.xfail(
    strict=True,
    reason='BUG-W1: write errors (EPIPE) on stdout are ignored, so '
    'follow mode keeps running after its consumer closed the pipe',
)
@pytest.mark.parametrize(
    'wait_first', [True, False], ids=['after-1st', 'at-once']
)
async def test_stdout_closed_early_exits_instead_of_spinning(
    playerctl, mpris_factory, wait_first
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    r, w = os.pipe()
    proc = await start_raw(playerctl, CMD, stdout=w)
    os.close(w)
    if wait_first:
        await read_some(r)  # the initial line
    os.close(r)  # the consumer goes away (head -1, a crashed bar, ...)
    # the next line playerctl prints hits a broken pipe
    for i in range(5):
        if proc.returncode is not None:
            break
        await p.set_artist_title('artist', f'more{i}')
        await asyncio.sleep(0.1)
    try:
        await asyncio.wait_for(proc.wait(), 1.5)
    except asyncio.TimeoutError:
        pytest.fail(
            'playerctl keeps running (state '
            f'{proc_state(proc.pid)}) after its stdout was closed'
        )
    stderr = (await proc.stderr.read()).decode()
    # SIGPIPE death or a clean/error exit, but not a crash
    assert proc.returncode in (-signal.SIGPIPE, 0, 1), (
        proc.returncode,
        stderr,
    )
    assert 'CRITICAL' not in stderr
    assert 'Segmentation' not in stderr


async def test_stdout_closed_with_no_further_output_keeps_idle_cpu_low(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    r, w = os.pipe()
    proc = await start_raw(playerctl, CMD, stdout=w)
    os.close(w)
    await read_some(r)
    os.close(r)
    # nothing prints, so it has no reason to notice yet: it must be idle
    assert await cpu_during(proc.pid, 1.0) < 0.3
    proc.terminate()
    await proc.wait()


@pytest.mark.xfail(
    strict=True,
    reason='BUG-W1: write errors (EPIPE) on stdout are ignored, so '
    'follow mode keeps running after its consumer closed the pipe',
)
async def test_stdout_closed_with_position_tick_exits(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Playing'
    p.position = 0
    await p.set_artist_title('a', 't')
    r, w = os.pipe()
    proc = await start_raw(
        playerctl,
        'metadata --format "{{duration(position)}}" --follow',
        stdout=w,
    )
    os.close(w)
    await read_some(r)
    os.close(r)
    # the next tick prints a new line into the broken pipe
    try:
        await asyncio.wait_for(proc.wait(), 2.5)
    except asyncio.TimeoutError:
        pytest.fail('still running after the tick wrote into a closed pipe')
    assert proc.returncode in (-signal.SIGPIPE, 0, 1)


async def test_stdout_dev_full_does_not_spin(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    fd = os.open('/dev/full', os.O_WRONLY)
    proc = await start_raw(playerctl, CMD, stdout=fd)
    os.close(fd)
    await asyncio.sleep(0.3)
    await p.set_artist_title('artist', 'two')
    try:
        await asyncio.wait_for(proc.wait(), 1.5)
    except asyncio.TimeoutError:
        # still alive: must at least be idle, not spinning on ENOSPC
        assert await cpu_during(proc.pid, 1.0) < 0.5
        proc.terminate()
        await proc.wait()
    else:
        assert proc.returncode in (-signal.SIGPIPE, 0, 1)


# --- slow consumer -----------------------------------------------------------


async def test_slow_consumer_gets_final_state_and_no_busy_loop(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    r, w = os.pipe()
    proc = await start_raw(playerctl, CMD, stdout=w)
    os.close(w)
    await asyncio.sleep(0.5)  # nobody reads: the pipe fills up
    big = 'y' * 4000
    for i in range(60):  # ~240 kB, well over the 64 kB pipe buffer
        await emit_title(p, f'{big}{i}')
    await p.ping()
    await asyncio.sleep(0.5)
    # blocked on a full pipe: must be asleep, not burning CPU
    assert await cpu_during(proc.pid, 1.0) < 0.3
    assert proc.returncode is None

    os.set_blocking(r, False)
    data = b''
    deadline = asyncio.get_running_loop().time() + 4
    final = f'test1: artist - {big}59\n'.encode()
    while not data.endswith(final):
        assert asyncio.get_running_loop().time() < deadline, data[-50:]
        try:
            chunk = os.read(r, 1 << 16)
            data += chunk
        except BlockingIOError:
            await asyncio.sleep(0.01)
    lines = data.decode().splitlines()
    assert lines[-1] == f'test1: artist - {big}59'
    assert no_consecutive_duplicates(lines)
    os.close(r)
    proc.terminate()
    await proc.wait()


async def test_slow_consumer_sigterm_while_blocked(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    r, w = os.pipe()
    proc = await start_raw(playerctl, CMD, stdout=w)
    os.close(w)
    await asyncio.sleep(0.3)
    big = 'z' * 70000
    await p.set_artist_title(
        'artist', big
    )  # a single line bigger than the pipe
    await asyncio.sleep(0.3)
    os.kill(proc.pid, signal.SIGTERM)
    await asyncio.wait_for(proc.wait(), 3)
    os.close(r)
    assert proc.returncode in (-15, 0, 143)


# --- bus dies -------------------------------------------------------------------


async def kill_bus(bus_address):
    bus = await MessageBus(bus_address=bus_address).connect()
    pid = await _bus_call(
        bus, 'GetConnectionUnixProcessID', 's', ['org.freedesktop.DBus']
    )
    bus.disconnect()
    os.kill(pid, signal.SIGKILL)


async def test_bus_daemon_killed_mid_follow_exits(
    playerctl, mpris_factory, bus_address
):
    p, proc = await start_with_player(playerctl, mpris_factory)
    p.disconnected = True  # the mock cannot disconnect from a dead bus
    await kill_bus(bus_address)
    try:
        code, stderr = await proc.exit(timeout=3)
    except asyncio.TimeoutError:
        pytest.fail(
            f'playerctl hangs after the bus died (state {proc_state(proc.pid)})'
        )
    # GDBus raises SIGTERM on itself when its bus connection closes
    assert code in (-signal.SIGTERM, 0, 1), code
    assert 'CRITICAL' not in stderr


async def test_bus_daemon_killed_without_players_exits(playerctl, bus_address):
    proc = await start_raw(playerctl, CMD)
    await asyncio.sleep(0.3)
    await kill_bus(bus_address)
    try:
        code, stderr = await proc.exit(timeout=3)
    except asyncio.TimeoutError:
        pytest.fail('playerctl hangs after the bus died with no players')
    assert code in (-signal.SIGTERM, 0, 1), code

"""Helpers for the follow-mode chaos stories (US-8.15 and up).

They start `playerctl` with full control over its stdio (the regular
`PlayerctlProcess` line-limits and strips everything), sample /proc, and fire
bursts of D-Bus signals without waiting between them.
"""

import asyncio
import os
import signal
import time

from dbus_next import Message
from dbus_next.service import Variant

from .mpris import PLAYER_INTERFACE, PROPERTIES_INTERFACE
from .playerctl import register

TICK = os.sysconf('SC_CLK_TCK')


class RawFollow:
    '''A playerctl process whose stdout is read in raw chunks.

    `limit` is large so a 1 MB line does not trip asyncio's line limit.'''

    def __init__(self, proc):
        self.proc = proc
        self.pid = proc.pid
        self.buf = b''
        self.eof = False
        self._reader = asyncio.get_event_loop().create_task(self._read())
        register(proc, self._reader)

    async def _read(self):
        while True:
            chunk = await self.proc.stdout.read(65536)
            if not chunk:
                self.eof = True
                return
            self.buf += chunk

    def lines(self):
        '''Complete lines printed so far (decoded, newline stripped).'''
        parts = self.buf.split(b'\n')
        return [p.decode() for p in parts[:-1]]

    async def wait_for(self, predicate, timeout=3.0, what='condition'):
        deadline = time.monotonic() + timeout
        while not predicate(self.lines()):
            assert time.monotonic() < deadline, (
                f'timed out waiting for {what}; lines={self.lines()[-5:]!r}'
            )
            await asyncio.sleep(0.01)

    async def wait_line(self, line, timeout=3.0):
        await self.wait_for(
            lambda ls: line in ls, timeout, f'line {line[:60]!r}'
        )

    async def wait_last(self, line, timeout=3.0):
        await self.wait_for(
            lambda ls: bool(ls) and ls[-1] == line,
            timeout,
            f'last line {line[:60]!r}',
        )

    async def settle(self, quiet=0.3, timeout=3.0):
        '''Wait until no new output has arrived for `quiet` seconds.'''
        deadline = time.monotonic() + timeout
        last = -1
        while True:
            size = len(self.buf)
            if size == last:
                return self.lines()
            last = size
            assert time.monotonic() < deadline, 'output never settled'
            await asyncio.sleep(quiet)

    def running(self):
        return self.proc.returncode is None

    async def exit(self, timeout=3.0):
        '''Wait for the process to end; return (returncode, stderr text).'''
        await asyncio.wait_for(self.proc.wait(), timeout)
        stderr = (await self.proc.stderr.read()).decode(errors='replace')
        return self.proc.returncode, stderr

    async def terminate(self, sig=signal.SIGTERM, timeout=3.0):
        if self.running():
            os.kill(self.pid, sig)
        return await self.exit(timeout)

    def alive_state(self):
        return proc_state(self.pid)

    def rss_kb(self):
        return proc_rss_kb(self.pid)

    def cpu_seconds(self):
        return proc_cpu_seconds(self.pid)


async def start_raw(
    playerctl, cmd, stdout=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024
):
    '''Start `playerctl <cmd>` on the test bus.

    With stdout=PIPE the output is collected in a `RawFollow`; otherwise
    (a file object or descriptor) the raw `asyncio` process is returned.'''
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = playerctl.bus_address
    proc = await asyncio.create_subprocess_shell(
        f'exec playerctl {cmd}',
        env=env,
        stdout=stdout,
        stderr=asyncio.subprocess.PIPE,
        limit=limit,
    )
    if stdout == asyncio.subprocess.PIPE:
        return RawFollow(proc)
    register(proc)
    return proc


def proc_state(pid):
    '''Scheduler state letter from /proc (R, S, T, Z, ...) or None.'''
    try:
        with open(f'/proc/{pid}/stat') as f:
            return f.read().rsplit(')', 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


def proc_rss_kb(pid):
    with open(f'/proc/{pid}/status') as f:
        for line in f:
            if line.startswith('VmRSS:'):
                return int(line.split()[1])
    raise AssertionError('no VmRSS')


def proc_cpu_seconds(pid):
    with open(f'/proc/{pid}/stat') as f:
        fields = f.read().rsplit(')', 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / TICK


async def cpu_during(pid, seconds):
    '''CPU seconds the process burns while we sleep `seconds` (idle check).'''
    before = proc_cpu_seconds(pid)
    await asyncio.sleep(seconds)
    return proc_cpu_seconds(pid) - before


def metadata_variant(player, title, artist='artist'):
    player.counter += 1
    player.metadata = {
        'xesam:title': Variant('s', title),
        'xesam:artist': Variant('as', [artist]),
        'mpris:trackid': Variant('o', '/' + str(player.counter)),
    }
    return player.metadata


async def emit_title(player, title, artist='artist'):
    '''Set metadata and send a PropertiesChanged for it.

    The send is awaited: dbus_next raises BlockingIOError when a burst of
    un-awaited signals fills the socket buffer, so the writer is paced.'''
    await raw_properties_changed(
        player,
        {
            'Metadata': Variant(
                'a{sv}', metadata_variant(player, title, artist)
            )
        },
    )


async def title_storm(player, count, prefix='t', artist='artist'):
    '''`count` metadata changes in one burst; returns the final title.'''
    for i in range(count):
        await emit_title(player, f'{prefix}{i}', artist)
    await player.ping()
    return f'{prefix}{count - 1}'


async def raw_properties_changed(
    player, changed, invalidated=(), interface=PLAYER_INTERFACE
):
    '''Like `send_properties_changed` but without the ping round trip.'''
    await player.bus.send(
        Message.new_signal(
            '/org/mpris/MediaPlayer2',
            PROPERTIES_INTERFACE,
            'PropertiesChanged',
            'sa{sv}as',
            [interface, dict(changed), list(invalidated)],
        )
    )


def no_consecutive_duplicates(lines):
    return all(a != b for a, b in zip(lines, lines[1:]))


def assert_clean_stderr(text):
    for bad in ('CRITICAL', 'WARNING', 'Segmentation', 'assertion'):
        assert bad not in text, text


def assert_not_killed_by_signal(returncode):
    assert returncode is None or returncode >= 0, (
        f'killed by signal {-returncode}'
    )

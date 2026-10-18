import asyncio
import os
import sys
import textwrap

from .playerctl import CommandResult, PlayerctlProcess

# libplayerctl makes blocking D-Bus calls, so scripts using it run in a child
# process: in the pytest process they would block the event loop serving the
# mock players and deadlock.
PRELUDE = '''
import gi
gi.require_version('Playerctl', '2.0')
from gi.repository import Playerctl, GLib


def out(*args):
    print(*args, flush=True)


def run_loop(timeout_ms=4000):
    out('ready')
    loop = GLib.MainLoop()
    GLib.timeout_add(timeout_ms, loop.quit)
    loop.run()
'''


def _script(body):
    return PRELUDE + textwrap.dedent(body)


async def _spawn(bus_address, body):
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    return await asyncio.create_subprocess_exec(
        sys.executable,
        '-c',
        _script(body),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def run_gi(bus_address, body):
    '''Run a PyGObject snippet to completion and return its CommandResult.'''
    proc = await _spawn(bus_address, body)
    stdout, stderr = await proc.communicate()
    return CommandResult(stdout, stderr, proc.returncode)


async def start_gi(bus_address, body):
    '''Start a long-running snippet; wait until it prints `ready`.

    Stdout lines are available from the returned process's `queue`.
    '''
    proc = PlayerctlProcess(await _spawn(bus_address, body))
    line = await asyncio.wait_for(proc.queue.get(), 4)
    assert line == 'ready', line
    return proc

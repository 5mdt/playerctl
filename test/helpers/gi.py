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


def compose(*parts):
    '''Join script fragments written with their own indentation.'''
    return '\n'.join(textwrap.dedent(part) for part in parts)


def _script(body):
    return PRELUDE + textwrap.dedent(body)


async def _spawn(bus_address, body, env=None):
    env = {**os.environ, **(env or {})}
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    return await asyncio.create_subprocess_exec(
        sys.executable,
        '-c',
        _script(body),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )


async def run_gi(bus_address, body, env=None):
    '''Run a PyGObject snippet to completion and return its CommandResult.'''
    proc = await _spawn(bus_address, body, env)
    stdout, stderr = await proc.communicate()
    return CommandResult(stdout, stderr, proc.returncode)


async def start_gi(bus_address, body, env=None):
    '''Start a long-running snippet; wait until it prints `ready`.

    Stdout lines are available from the returned process's `queue`.
    '''
    proc = PlayerctlProcess(await _spawn(bus_address, body, env))
    line = await asyncio.wait_for(proc.queue.get(), 4)
    assert line == 'ready', line
    return proc


# set_sort_func() takes a C callback, which the introspection bindings cannot
# pass, so scripts call it through ctypes. `set_sort_func(manager, key)` keeps
# the manager's players ordered by `key(player_instance)`.
SORT_FUNC = '''
import ctypes

_pctl = ctypes.CDLL('libplayerctl.so.2')
_gobject = ctypes.CDLL('libgobject-2.0.so.0')
_compare_type = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_callbacks = []


def _instance(pointer):
    value = ctypes.c_char_p()
    _gobject.g_object_get(
        ctypes.c_void_p(pointer), b'player-instance', ctypes.byref(value), None)
    return value.value.decode()


def set_sort_func(manager, key):
    def compare(a, b, data):
        ka, kb = key(_instance(a)), key(_instance(b))
        return (ka > kb) - (ka < kb)

    callback = _compare_type(compare)
    _callbacks.append(callback)
    ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
    ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [
        ctypes.py_object, ctypes.c_char_p]
    pointer = ctypes.pythonapi.PyCapsule_GetPointer(manager.__gpointer__, None)
    _pctl.playerctl_player_manager_set_sort_func(
        ctypes.c_void_p(pointer), callback, None, None)
'''


# Makes a g_critical abort the process, so a wrongly typed D-Bus value that
# reaches GLib unchecked fails a test instead of only logging.
FATAL_CRITICALS = {'G_DEBUG': 'fatal-criticals'}

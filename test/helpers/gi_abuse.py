'''Helpers for the library-abuse tests (US-11.15 and up).

Scripts run in a child process (see `gi.py`); the helpers here add the
invariants every abusive call must keep: the child never dies by a signal and
GLib never logs a CRITICAL or warning, and every failure is a `GLib.Error`
with the documented `playerctl-player-error-quark` domain.
'''

import re

PLAYER_ERROR_DOMAIN = 'playerctl-player-error-quark'
NOT_FOUND = 1

# GLib messages that mean the library was called with a bad pointer or broke
# an internal invariant.
BAD_STDERR = re.compile(
    r'CRITICAL|-WARNING|-ERROR|\*\* \(|assertion .* failed|Segmentation'
    r'|Aborted|Traceback|core dumped'
)

# `attempt(label, fn)` prints one line per call: `label ok <repr>`,
# `label gerror <domain> <code>` or `label pyexc <ExceptionName>`.
ATTEMPT = '''
def attempt(label, fn):
    try:
        out(label, 'ok', repr(fn()))
    except GLib.Error as e:
        out(label, 'gerror', e.domain, e.code)
    except Exception as e:
        out(label, 'pyexc', type(e).__name__)
'''


def assert_clean(result, allow=()):
    '''The child exited normally and logged no GLib CRITICAL or warning.

    allow: substrings of stderr lines that are the library's documented,
    intentional log output (e.g. a deprecation notice) and so not a failure.
    '''
    assert result.returncode == 0, (
        f'child died with {result.returncode}\n{result.stderr}'
    )
    bad = [
        line
        for line in result.stderr.splitlines()
        if BAD_STDERR.search(line) and not any(text in line for text in allow)
    ]
    assert not bad, '\n'.join(bad)


def parse_attempts(result):
    '''Map label -> (kind, details) from `attempt` output lines.'''
    parsed = {}
    for line in result.stdout.splitlines():
        label, kind, *rest = line.split(' ', 2)
        parsed[label] = (kind, rest[0] if rest else '')
    return parsed


def assert_not_found(parsed, label):
    kind, details = parsed[label]
    assert (kind, details) == (
        'gerror',
        f'{PLAYER_ERROR_DOMAIN} {NOT_FOUND}',
    ), f'{label}: {kind} {details}'


# A player that is waiting for its bus name to vanish: runs the main loop
# until `exit` is emitted (or 3s), then falls through to the test body.
AWAIT_EXIT = '''
player = Playerctl.Player.new('lib')
loop = GLib.MainLoop()
player.connect('exit', lambda p: loop.quit())
GLib.timeout_add(3000, loop.quit)
out('ready')
loop.run()
'''


async def run_after_vanish(gi_start, mpris, body, timeout=6):
    '''Start `body` (which prints `ready` once it waits for something to
    vanish), disconnect `mpris`, let the child finish and return its
    CommandResult.'''
    import asyncio

    from .playerctl import CommandResult

    proc = await gi_start(body)
    await mpris.disconnect()
    returncode = await asyncio.wait_for(proc.proc.wait(), timeout)
    await proc._reader
    lines = []
    while not proc.queue.empty():
        lines.append(proc.queue.get_nowait())
    stderr = await proc.proc.stderr.read()
    return CommandResult('\n'.join(lines).encode(), stderr, returncode)


# Calls into libplayerctl with arguments the introspection bindings refuse to
# pass (out-of-range enum values). `raw_set_loop_status(player, value)` returns
# whether the library reported an error.
RAW = '''
import ctypes

_pctl = ctypes.CDLL('libplayerctl.so.2')
ctypes.pythonapi.PyCapsule_GetPointer.restype = ctypes.c_void_p
ctypes.pythonapi.PyCapsule_GetPointer.argtypes = [
    ctypes.py_object, ctypes.c_char_p]


def pointer(obj):
    return ctypes.c_void_p(
        ctypes.pythonapi.PyCapsule_GetPointer(obj.__gpointer__, None))


def raw_set_loop_status(player, value):
    err = ctypes.c_void_p()
    _pctl.playerctl_player_set_loop_status(
        pointer(player), ctypes.c_int(value), ctypes.byref(err))
    return bool(err.value)
'''


# Prints one line per signal the player emits, so a test can see what a
# hostile PropertiesChanged or Seeked made the library do.
LISTEN_ALL = '''
player = Playerctl.Player.new('lib')


def show(value):
    if isinstance(value, GLib.Variant):
        return value.get_type_string()
    return getattr(value, 'value_nick', value)


for signal in ('playback-status', 'play', 'pause', 'stop', 'metadata',
               'seeked', 'volume', 'shuffle', 'loop-status', 'exit'):
    player.connect(
        signal, lambda p, *a, s=signal: out(s, *[show(x) for x in a]))
out('ready')
GLib.MainLoop().run()
'''


async def settle_and_stop(proc, mpris, timeout=4):
    '''Prove the child survived whatever was sent before: make `mpris` send a
    valid volume change, wait until the child reports it, then stop the child.

    Returns (lines seen before the valid change, stderr, returncode).'''
    import asyncio
    import signal

    await mpris.emit_properties(volume=0.125)
    lines = []
    while True:
        line = await asyncio.wait_for(proc.queue.get(), timeout)
        if line == 'volume 0.125':
            break
        lines.append(line)
    proc.proc.send_signal(signal.SIGTERM)
    returncode = await asyncio.wait_for(proc.proc.wait(), timeout)
    stderr = (await proc.proc.stderr.read()).decode()
    return lines, stderr, returncode


def assert_survived(stderr, returncode, allow=()):
    '''`settle_and_stop` found the child alive (stopped by our SIGTERM only)
    and its stderr free of GLib CRITICALs.'''
    import signal

    assert returncode == -signal.SIGTERM, returncode
    bad = [
        line
        for line in stderr.splitlines()
        if BAD_STDERR.search(line) and not any(a in line for a in allow)
    ]
    assert not bad, '\n'.join(bad)


# set_sort_func() with a raw compare callback over the players' instance names
# (`set_sort_raw(manager, compare, notify=None)`; compare(a, b) may raise,
# re-enter the manager or answer inconsistently), plus the NULL sort function
# the bindings cannot express.
SORT_RAW = (
    RAW
    + '''
_gobject = ctypes.CDLL('libgobject-2.0.so.0')
_compare_type = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
_notify_type = ctypes.CFUNCTYPE(None, ctypes.c_void_p)
_keep = []


def instance_of(pointer):
    value = ctypes.c_char_p()
    _gobject.g_object_get(
        ctypes.c_void_p(pointer), b'player-name', ctypes.byref(value), None)
    return value.value.decode()


def set_sort_raw(manager, compare, notify=None):
    callback = _compare_type(
        lambda a, b, data: compare(instance_of(a), instance_of(b)))
    _keep.append(callback)
    notify_cb = ctypes.cast(None, _notify_type)
    if notify is not None:
        notify_cb = _notify_type(lambda data: notify())
        _keep.append(notify_cb)
    _pctl.playerctl_player_manager_set_sort_func(
        pointer(manager), callback, None, notify_cb)


def set_sort_null(manager):
    _pctl.playerctl_player_manager_set_sort_func(
        pointer(manager), None, None, None)
'''
)

# A manager that manages every player that is on the bus when it is created.
MANAGE_ALL = '''
manager = Playerctl.PlayerManager()
for name in manager.props.player_names:
    manager.manage_player(Playerctl.Player.new_from_name(name))


def listing():
    return ' '.join(p.props.player_name for p in manager.props.players)
'''


# `leak_kb(rounds, fn)` runs `fn` `rounds` times (after a warm-up) and returns
# the growth of the process's VmRSS in KiB.
LEAK = '''
import gc


def rss():
    with open('/proc/self/status') as status:
        for line in status:
            if line.startswith('VmRSS'):
                return int(line.split()[1])


def leak_kb(rounds, fn, warmup=50):
    for _ in range(warmup):
        fn()
    gc.collect()
    GLib.MainContext.default().iteration(False)
    before = rss()
    for _ in range(rounds):
        fn()
    gc.collect()
    GLib.MainContext.default().iteration(False)
    return rss() - before
'''

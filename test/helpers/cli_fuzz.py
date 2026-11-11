"""Shared helpers for the CLI argv fuzz tests (US-2.6, 3.5, 4.4, 6.10, 9.6)."""

import asyncio
import shlex

# Largest single argv string the kernel accepts is 128 KiB (MAX_ARG_STRLEN),
# so "huge" means just under that.
HUGE = 'x' * 100_000

# Values a user or a script could hand a numeric argument.
HOSTILE_NUMBERS = {
    'empty': '',
    'space': ' ',
    'tab': '\t',
    'newline': '\n',
    'unicode': 'é漢字🎵',
    'arabic-digits': '١٢٣',
    'huge': HUGE,
    'huge-digits': '9' * 100_000,
    'dashdash': '--',
    'neg-zero': '-0',
    'pos-zero': '+0',
    'big-float': '1e308',
    'overflow': '1e999',
    'underflow': '1e-400',
    'nan': 'nan',
    'inf': 'inf',
    'neg-inf': '-inf',
    'hex': '0x10',
    'comma-decimal': '1,5',
    'trailing-sign-twice': '5+-',
    'double-plus': '++5',
    'leading-space': ' 5',
    'trailing-space': '5 ',
    'nul-escape': '5\\x00',
    'percent-nul': '%00',
    'shell-subst': '$(touch /tmp/pwned)',
    'shell-backtick': '`id`',
    'shell-semicolon': '5; rm -rf /',
    'glob': '*',
    'format-spec': '%s%n',
    'int64-max': '9223372036854775807',
    'int64-overflow': '9223372036854775808',
    'neg-int64-min': '-9223372036854775808',
}

# Chars that are never valid in a decimal number; used to check rejection.
STATE_KEYS = (
    'next_called',
    'previous_called',
    'pause_called',
    'play_pause_called',
    'stop_called',
    'play_called',
    'seek_called_with',
    'set_position_called_with',
    'open_uri_called_with',
    'playback_status',
    'loop_status',
    'shuffle',
    'volume',
    'position',
)

BAD_STDERR = (
    'CRITICAL',
    'WARNING',
    'Segmentation',
    'Assertion',
    'runtime error',
)


def q(arg):
    """Quote one argument for the shell the test harness runs playerctl in."""
    return shlex.quote(arg)


def snapshot(mpris):
    """The mock player state that a rejected command must leave alone."""
    return {key: getattr(mpris, key) for key in STATE_KEYS}


async def run(playerctl, cmd, timeout=4.0):
    """Run `playerctl <cmd>`; a hang fails with a clear message."""
    try:
        return await asyncio.wait_for(playerctl.run(cmd), timeout)
    except asyncio.TimeoutError:  # pragma: no cover
        raise AssertionError(f'playerctl {cmd[:80]!r} hung') from None


def assert_sane(result, what=''):
    """Invariants every argv, however hostile, must satisfy."""
    assert result.returncode >= 0, (
        f'{what}: killed by signal {-result.returncode}'
    )
    assert result.returncode in (0, 1), f'{what}: exit {result.returncode}'
    for bad in BAD_STDERR:
        assert bad not in result.stderr, (
            f'{what}: {bad} on stderr: {result.stderr[:300]}'
        )


async def run_raw(playerctl, *argv, timeout=4.0):
    """Run playerctl with exact argv (str or bytes, no shell); returns
    (returncode, stdout bytes, stderr bytes). For invalid UTF-8 arguments."""
    import os

    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = playerctl.bus_address
    proc = await asyncio.create_subprocess_exec(
        'playerctl',
        *argv,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:  # pragma: no cover
        proc.kill()
        await proc.wait()
        raise AssertionError(f'playerctl {argv!r} hung') from None
    return proc.returncode, out, err


async def prepared(mpris_factory, *names):
    """Mock players with a track (so `position` works) and known state."""
    players = await mpris_factory(*names)
    for player in players:
        player.volume = 0.5
        player.position = 10_000_000
        await player.set_artist_title('Artist', 'Title')
    return players


# Names that must be rejected by a numeric argument (parse error).
NOT_A_NUMBER = (
    'empty space tab newline unicode arabic-digits huge huge-digits dashdash '
    'overflow nan inf neg-inf comma-decimal trailing-sign-twice double-plus '
    'trailing-space nul-escape percent-nul shell-subst shell-backtick '
    'shell-semicolon glob format-spec'
).split()

CONTROL_COMMANDS = ('play', 'pause', 'play-pause', 'stop', 'next', 'previous')
ALL_COMMANDS = CONTROL_COMMANDS + (
    'position',
    'volume',
    'status',
    'metadata',
    'open',
    'loop',
    'shuffle',
)

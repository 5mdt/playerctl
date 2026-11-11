"""Hostile MPRIS players (QA "evil player").

These mocks intentionally break the MPRIS spec, so they are exempt from the
rule (helpers test 11.14) that the normal mocks follow it. They are built on
the regular mocks in `mpris.py`: a normal `MprisPlayer` is exported and a
`Tamper` message handler rewrites, drops or fails what it answers.

Use with `mpris_factory(name, prepare=tamper(...))`, combine behaviours with
`combine(...)`.
"""

import asyncio
import math

from dbus_next import Message, MessageType, Variant

from .mpris import (
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    ROOT_INTERFACE,
    MessageGate,
)

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)

UNKNOWN_PROPERTY = 'org.freedesktop.DBus.Error.UnknownProperty'


class Tamper:
    """Rewrite what a mock answers to Properties.Get / GetAll.

    overrides: {(interface, property): Variant} replaces the value.
    drop: {(interface, property)} makes the property unknown (absent from
    GetAll, UnknownProperty for Get).
    die_after: member name; the bus connection is closed right after this
    call is answered (a player that disappears just after `Get`).
    die_on: members; the connection is closed on the call, unanswered.
    """

    def __init__(self, bus, overrides=None, drop=(), die_after=(), die_on=()):
        self.bus = bus
        self.overrides = dict(overrides or {})
        self.drop = set(drop)
        self.die_after = set(die_after)
        self.die_on = set(die_on)
        bus.add_message_handler(self._handle)

    def _handle(self, msg):
        if msg.message_type != MessageType.METHOD_CALL:
            return None
        if msg.member in self.die_on:
            asyncio.get_event_loop().call_soon(self.bus.disconnect)
            return True
        if msg.interface != PROPERTIES_INTERFACE:
            return None
        if msg.member not in ('Get', 'GetAll') or not msg.body:
            return None
        interface = msg.body[0]
        if msg.member == 'Get':
            key = (interface, msg.body[1])
            if key in self.drop:
                return Message.new_error(msg, UNKNOWN_PROPERTY, 'gone')
            if key not in self.overrides:
                return self._maybe_die(msg, None)
            value = self.overrides[key]

            def transform(reply):
                reply.body[0] = value
                reply.signature = 'v'
                return reply

        else:

            def transform(reply):
                body = dict(reply.body[0])
                for (i, name), value in self.overrides.items():
                    if i == interface:
                        body[name] = value
                for i, name in self.drop:
                    if i == interface:
                        body.pop(name, None)
                reply.body[0] = body
                return reply

        return self._maybe_die(msg, transform)

    def _maybe_die(self, msg, transform):
        handler = self.bus._find_message_handler(msg)
        send_reply = self.bus._send_reply(msg)

        def send(reply):
            send_reply(transform(reply) if transform else reply)
            if msg.member in self.die_after:
                asyncio.get_event_loop().call_soon(self.bus.disconnect)

        with send_reply:
            handler(msg, send)
        return True


def tamper(overrides=None, drop=(), die_after=(), die_on=(), root=False):
    """`setup_mpris(prepare=...)` hook installing a `Tamper` as
    `player.tamper`. Plain string keys mean the Player interface (or the Root
    interface with root=True)."""
    default = ROOT_INTERFACE if root else PLAYER_INTERFACE

    def norm(key):
        return key if isinstance(key, tuple) else (default, key)

    def prepare(player):
        player.tamper = Tamper(
            player.bus,
            {norm(k): v for k, v in (overrides or {}).items()},
            {norm(k) for k in drop},
            die_after,
            die_on,
        )

    return prepare


def failing(*rules, **kwargs):
    """`prepare` hook: `rules` are (member, interface-or-None, error, text)
    answered with a D-Bus error. Installs a `MessageGate` as `player.gate`."""

    def prepare(player):
        player.gate = MessageGate(player.bus)
        for member, interface, error, text in rules:
            player.gate.fail(member, interface, None, error, text)

    return prepare


def holding(*members):
    """`prepare` hook: never answer these method calls (until
    `player.gate.release()`)."""

    def prepare(player):
        player.gate = MessageGate(player.bus)
        for member in members:
            player.gate.hold(member, PLAYER_INTERFACE)

    return prepare


def combine(*prepares):
    def prepare(player):
        for p in prepares:
            p(player)

    return prepare


async def send_signal(player, member, signature, body, interface):
    """Emit any signal with any body from the mock's connection."""
    await player.bus.send(
        Message.new_signal(
            '/org/mpris/MediaPlayer2', interface, member, signature, body
        )
    )
    await player.ping()


def v(sig, value):
    return Variant(sig, value)


# --- hostile property values --------------------------------------------

# (id, property, Variant) wrong or out-of-range Player property values
PLAYER_LIES = [
    ('status-int', 'PlaybackStatus', v('i', 5)),
    ('status-banana', 'PlaybackStatus', v('s', 'Banana')),
    ('status-empty', 'PlaybackStatus', v('s', '')),
    ('status-array', 'PlaybackStatus', v('as', ['Playing'])),
    ('status-lower', 'PlaybackStatus', v('s', 'playing')),
    ('status-newline', 'PlaybackStatus', v('s', 'Play\ning\x1b[31m')),
    ('status-huge', 'PlaybackStatus', v('s', 'P' * 100000)),
    ('loop-garbage', 'LoopStatus', v('s', 'garbage')),
    ('loop-int', 'LoopStatus', v('i', 3)),
    ('loop-empty', 'LoopStatus', v('s', '')),
    ('loop-huge', 'LoopStatus', v('s', 'T' * 100000)),
    ('shuffle-string', 'Shuffle', v('s', 'yes')),
    ('shuffle-int', 'Shuffle', v('i', 1)),
    ('shuffle-double', 'Shuffle', v('d', 1.0)),
    ('volume-string', 'Volume', v('s', 'loud')),
    ('volume-int', 'Volume', v('x', 5)),
    ('volume-bool', 'Volume', v('b', True)),
    ('volume-negative', 'Volume', v('d', -1.0)),
    ('volume-big', 'Volume', v('d', 1e308)),
    ('volume-over-one', 'Volume', v('d', 2.5)),
    ('volume-nan', 'Volume', v('d', math.nan)),
    ('volume-inf', 'Volume', v('d', math.inf)),
    ('volume-neginf', 'Volume', v('d', -math.inf)),
    ('position-double', 'Position', v('d', 1.5)),
    ('position-uint', 'Position', v('t', 5)),
    ('position-int32', 'Position', v('i', 5)),
    ('position-string', 'Position', v('s', 'now')),
    ('position-negative', 'Position', v('x', -5)),
    ('position-max', 'Position', v('x', INT64_MAX)),
    ('position-min', 'Position', v('x', INT64_MIN)),
    ('position-uint-max', 'Position', v('t', 2**64 - 1)),
    ('metadata-string', 'Metadata', v('s', 'nope')),
    ('metadata-a-ss', 'Metadata', v('a{ss}', {'xesam:title': 'x'})),
    ('metadata-ai', 'Metadata', v('ai', [1, 2, 3])),
    ('metadata-int', 'Metadata', v('i', 0)),
    ('can-play-string', 'CanPlay', v('s', 'yes')),
    ('can-pause-string', 'CanPause', v('s', 'yes')),
    ('can-next-string', 'CanGoNext', v('s', 'yes')),
    ('can-prev-string', 'CanGoPrevious', v('s', 'yes')),
    ('can-seek-string', 'CanSeek', v('s', 'yes')),
    ('can-control-string', 'CanControl', v('s', 'yes')),
    ('can-play-int', 'CanPlay', v('i', 1)),
    ('rate-string', 'Rate', v('s', 'fast')),
]

# nasty-but-valid UTF-8 strings (a D-Bus string can never hold NUL or
# invalid UTF-8, so these are the closest a player can get)
NASTY_STRINGS = {
    'ansi': 'a\x1b[31mred\x1b[0m\x1b]0;pwn\x07z',
    'newlines': 'line1\nline2\r\nline3',
    'tabs': 'a\tb\tc',
    'controls': ''.join(chr(c) for c in range(1, 32)),
    'del': 'a\x7fb',
    'c1': '\x80\x85\x9f',
    'rtl': '‮abc‬‏',
    'bom': '﻿bom',
    'zwj': 'a‍​b',
    'emoji4': '\U0001f600\U0001f468‍\U0001f469‍\U0001f467',
    'maxcp': '\U0010fffd',
    'nonchar': '﷐�',
    'surrogate-adjacent': '퟿',
    'combining': 'e' + '́' * 200,
    'quotes': '"\'\\/<>&`$(){}%',
    'braces': '{{title}} {{',
    'markup': '<b>bold</b> &amp; <![CDATA[x]]>',
    'jsonish': '"}, "evil": {"a":"',
    'percent': '%41%00%zz',
    'wide': 'ｗｉｄｅ',
}

HUGE = 1024 * 1024


def metadata_with(**extra):
    """Normal-looking metadata plus the given `key=Variant` entries (colons
    in keys are written with `__`: xesam__title -> xesam:title)."""
    meta = {
        'mpris:trackid': Variant('o', '/track/1'),
        'xesam:title': Variant('s', 'T'),
        'xesam:artist': Variant('as', ['A']),
    }
    for key, value in extra.items():
        meta[key.replace('__', ':')] = value
    return meta


# --- running playerctl and checking the invariants -----------------------


async def run(playerctl, cmd, timeout=4):
    return await asyncio.wait_for(playerctl.run(cmd), timeout)


# BUG-E1: GDBus warns on stderr about a property or signal whose type differs
# from the interface's; tracked by dedicated xfail tests, so tolerated
# everywhere else.
GIO_TYPE_WARNING = 'GLib-GIO-WARNING'


def assert_sane(result, allowed=(0, 1), tolerate_gio_type_warning=True):
    """The invariants for every hostile input: no death by signal, an exit
    code from `allowed`, and no GLib CRITICAL/WARNING noise."""
    if tolerate_gio_type_warning:
        lines = [
            line
            for line in result.stderr.splitlines()
            if GIO_TYPE_WARNING not in line
        ]
        result.stderr = '\n'.join(lines)
    assert result.returncode in allowed, (
        result.returncode,
        result.stdout[:200],
        result.stderr[:500],
    )
    for noise in ('CRITICAL', 'WARNING', 'Segmentation', 'assertion'):
        assert noise not in result.stderr, result.stderr[:500]

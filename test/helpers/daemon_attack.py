'''Helpers for the playerctld attack stories (test/us10_daemon, US-10.22+).

Everything here is new; the existing helpers are used as they are.
'''

import asyncio
import os
import re
import signal

from dbus_next import Message, MessageType, NameFlag, RequestNameReply, Variant
from dbus_next.aio import MessageBus

from .daemon import (
    MPRIS_PATH,
    PLAYERCTLD_NAME,
    player_names,
    playerctld_call,
)
from .mpris import (
    PLAYER_INTERFACE,
    PLAYERCTLD_INTERFACE,
    PROPERTIES_INTERFACE,
    ROOT_INTERFACE,
    MprisPlayer,
    MprisRoot,
)

PREFIX = 'org.mpris.MediaPlayer2.'
PLAYERCTLD_LEGACY = 'com.github.altdesktop.playerctld'
DBUS = 'org.freedesktop.DBus'

# GLib log domains lines of the daemon look like
# "(process:12): playerctl-WARNING **: 12:00:00.000: text"
PROBLEM = re.compile(
    r'-(CRITICAL|WARNING|ERROR)\b|\bGLib-.*(CRITICAL|WARNING)'
)


# BUG-D1: a player without the optional TrackList/Playlists interfaces makes
# the daemon log a WARNING for each of them every time it appears; the
# invariant checks ignore exactly these lines so that they can still catch
# anything else.
OPTIONAL_NOISE = (
    'could not get properties for active player: GDBus.Error:org.freedesktop.'
    'DBus.Error.UnknownInterface: could not find an interface "org.mpris.'
    'MediaPlayer2.',
    'could not get org.mpris.MediaPlayer2.TrackList properties',
    'could not get org.mpris.MediaPlayer2.Playlists properties',
)


def problems(proc, allow=OPTIONAL_NOISE):
    '''Log lines of the daemon that are a GLib WARNING/CRITICAL/ERROR,
    minus those containing one of the `allow` fragments.'''
    return [
        line
        for line in proc.log
        if PROBLEM.search(line) and not any(a in line for a in allow)
    ]


def assert_healthy(proc, allow=OPTIONAL_NOISE):
    '''The daemon still runs and logged no CRITICAL/WARNING (except allowed).'''
    assert proc.returncode is None, proc.log
    found = problems(proc, allow)
    assert not found, found


async def raw_call(
    bus,
    interface,
    member,
    signature='',
    body=None,
    destination=PLAYERCTLD_NAME,
    path=MPRIS_PATH,
    timeout=3.0,
):
    '''Method call with any signature/body; returns the reply (METHOD_RETURN
    or ERROR) or fails the test when no reply arrives in `timeout`.'''
    msg = Message(
        destination=destination,
        path=path,
        interface=interface,
        member=member,
        signature=signature,
        body=body or [],
    )
    return await asyncio.wait_for(bus.call(msg), timeout)


async def dbus_call(bus, member, signature='', body=None):
    reply = await raw_call(
        bus,
        DBUS,
        member,
        signature,
        body,
        destination=DBUS,
        path='/org/freedesktop/DBus',
    )
    return reply


async def request_name(bus, name, flags=NameFlag.NONE):
    return await bus.request_name(name, flags)


async def new_bus(bus_address):
    return await MessageBus(bus_address=bus_address).connect()


async def close_bus(bus):
    bus.disconnect()
    await bus.wait_for_disconnect()


async def shift_names(bus, reverse=False):
    '''Shift/Unshift over D-Bus; returns the reply.'''
    return await playerctld_call(
        bus, PLAYERCTLD_INTERFACE, 'Unshift' if reverse else 'Shift'
    )


class PlayerCollector:
    '''Records every ActivePlayerChangeBegin/End signal and PlayerNames
    property change of the daemon, in bus order.'''

    def __init__(self, bus, owner):
        self.bus = bus
        self.owner = owner
        self.events = []  # ('Begin'|'End', name) / ('Names', [..])
        self.player_props = {}  # latest Player properties the daemon sent
        bus.add_message_handler(self._handle)

    @classmethod
    async def start(cls, bus_address):
        bus = await new_bus(bus_address)
        reply = await dbus_call(bus, 'GetNameOwner', 's', [PLAYERCTLD_NAME])
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body
        self = cls(bus, reply.body[0])
        reply = await dbus_call(
            bus,
            'AddMatch',
            's',
            [f"type='signal',path='{MPRIS_PATH}',sender='{PLAYERCTLD_NAME}'"],
        )
        assert reply.message_type == MessageType.METHOD_RETURN
        return self

    def _handle(self, msg):
        if msg.message_type != MessageType.SIGNAL or msg.sender != self.owner:
            return
        if msg.interface == PLAYERCTLD_INTERFACE:
            if msg.member == 'ActivePlayerChangeBegin':
                self.events.append(('Begin', msg.body[0]))
            elif msg.member == 'ActivePlayerChangeEnd':
                self.events.append(('End', msg.body[0]))
        elif (
            msg.interface == PROPERTIES_INTERFACE
            and msg.member == 'PropertiesChanged'
            and msg.body[0] == PLAYER_INTERFACE
        ):
            self.player_props.update(msg.body[1])
        elif (
            msg.interface == PROPERTIES_INTERFACE
            and msg.member == 'PropertiesChanged'
            and msg.body[0] == PLAYERCTLD_INTERFACE
            and 'PlayerNames' in msg.body[1]
        ):
            self.events.append(('Names', msg.body[1]['PlayerNames'].value))

    def pairing_errors(self):
        '''Begin/End must strictly alternate, with the same name, and the
        PlayerNames announcement must sit between them.'''
        errors = []
        state = None
        for kind, value in self.events:
            if kind == 'Begin':
                if state is not None:
                    errors.append(f'Begin inside a change: {value}')
                state = value
            elif kind == 'End':
                if state is None:
                    errors.append(f'End without Begin: {value}')
                elif state != value:
                    errors.append(f'Begin {state!r} but End {value!r}')
                state = None
        if state is not None:
            errors.append(f'unterminated change {state!r}')
        return errors

    def end_names(self):
        return [v for k, v in self.events if k == 'End']

    async def wait_quiet(self, quiet=0.15, timeout=3.0):
        '''Wait until no new event arrived for `quiet` seconds.'''
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last = len(self.events)
        stable_since = loop.time()
        while loop.time() < deadline:
            await asyncio.sleep(0.02)
            if len(self.events) != last:
                last = len(self.events)
                stable_since = loop.time()
            elif loop.time() - stable_since >= quiet:
                return
        raise AssertionError('daemon signals never went quiet')

    async def close(self):
        await close_bus(self.bus)


class RawPlayer:
    '''A hand-driven MPRIS player: exports the mock Player and Root
    interfaces on its own connection and can emit anything.'''

    def __init__(self, bus, name):
        self.bus = bus
        self.name = name
        self.player = MprisPlayer(bus)
        self.root = MprisRoot()

    @classmethod
    async def create(cls, bus_address, name, flags=NameFlag.NONE, full=False):
        '''`name` is the part after org.mpris.MediaPlayer2. unless `full`.'''
        bus = await new_bus(bus_address)
        self = cls(bus, name if full else PREFIX + name)
        bus.export(MPRIS_PATH, self.player)
        bus.export(MPRIS_PATH, self.root)
        reply = await bus.request_name(self.name, flags)
        assert reply == RequestNameReply.PRIMARY_OWNER, reply
        await self.player.ping()
        return self

    async def emit(self, interface, member, signature, body):
        await self.bus.send(
            Message.new_signal(MPRIS_PATH, interface, member, signature, body)
        )
        await self.player.ping()

    async def flood(self, count, make=None, interface=PLAYER_INTERFACE):
        '''Send `count` PropertiesChanged signals back to back (the socket
        write is awaited so the client side cannot overflow).'''
        for i in range(count):
            body = make(i) if make else {'Volume': Variant('d', i / count)}
            await self.bus.send(
                Message.new_signal(
                    MPRIS_PATH,
                    PROPERTIES_INTERFACE,
                    'PropertiesChanged',
                    'sa{sv}as',
                    [interface, body, []],
                )
            )
        await self.player.ping()

    async def changed(self, **props):
        await self.player.send_properties_changed(
            {k: Variant(*v) for k, v in props.items()}
        )

    async def disconnect(self):
        await self.player.disconnect()


def vm_rss_kb(pid):
    with open(f'/proc/{pid}/status') as status:
        for line in status:
            if line.startswith('VmRSS:'):
                return int(line.split()[1])
    raise AssertionError('no VmRSS')


def process_state(pid):
    '''One letter state from /proc, or None when the process is gone.'''
    try:
        with open(f'/proc/{pid}/stat') as stat:
            return stat.read().rsplit(')', 1)[1].split()[0]
    except (FileNotFoundError, ProcessLookupError):
        return None


async def wait_exit(proc, timeout=3.0):
    await asyncio.wait_for(proc.wait(), timeout)
    return proc.returncode


def send_signal(proc, sig):
    os.kill(proc.pid, sig)


SIGNALS = {
    'TERM': signal.SIGTERM,
    'INT': signal.SIGINT,
    'HUP': signal.SIGHUP,
    'PIPE': signal.SIGPIPE,
}


async def names_and_active(bus):
    names = await player_names(bus)
    return names, (names[0] if names else None)


__all__ = [
    'PLAYER_INTERFACE',
    'ROOT_INTERFACE',
]

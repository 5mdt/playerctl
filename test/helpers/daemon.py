import asyncio
import os
import signal

from dbus_next import Message, MessageType
from dbus_next.aio import MessageBus

from .mpris import PLAYERCTLD_INTERFACE, name_owner_pid, wait_for_name
from .playerctl import register

PLAYERCTLD_NAME = 'org.mpris.MediaPlayer2.playerctld'
MPRIS_PATH = '/org/mpris/MediaPlayer2'


async def start_playerctld(bus_address, debug=False, env=None):
    # stop a playerctld that is already on this test bus (e.g. one started by
    # dbus activation), without touching any other playerctld on the system
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)
    if pid is not None:
        os.kill(pid, signal.SIGTERM)
        await wait_for_name(bus_address, PLAYERCTLD_NAME, present=False)
    env = {**os.environ, **(env or {})}
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    env['G_MESSAGES_DEBUG'] = 'playerctl'
    proc = await asyncio.create_subprocess_shell(
        'exec playerctld',
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    proc.log = []

    async def reader(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            proc.log.append(line.decode().strip())
            if debug:
                print(line)

    task = asyncio.get_event_loop().create_task(reader(proc.stdout))
    register(proc, task)

    # playerctld only emits signals once it owns its name and has subscribed
    # to NameOwnerChanged, so players created earlier would go unnoticed
    await wait_for_name(bus_address, PLAYERCTLD_NAME)

    return proc


async def stop_playerctld(proc):
    if proc.returncode is None:
        proc.terminate()
    await proc.wait()


async def playerctld_shift(bus_address, reverse=False):
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    env['G_MESSAGES_DEBUG'] = 'playerctl'
    cmd = 'playerctld unshift' if reverse else 'playerctld shift'
    shift = await asyncio.create_subprocess_shell(
        cmd,
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    return await shift.wait()


async def playerctld_cli(bus_address, args):
    '''Run `playerctld <args>`; returns (returncode, stdout, stderr).'''
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    proc = await asyncio.create_subprocess_shell(
        f'playerctld {args}'.strip(),
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def settle(delay=0.2):
    '''Give playerctld time to handle signals sent just before.'''
    await asyncio.sleep(delay)


class SignalListener:
    '''Collects the signals playerctld emits, as (interface, member, body).'''

    def __init__(self, bus, owner):
        self.bus = bus
        self.owner = owner
        self.queue = asyncio.Queue()

    @classmethod
    async def start(cls, bus_address):
        bus = await MessageBus(bus_address=bus_address).connect()
        reply = await bus.call(
            Message(
                destination='org.freedesktop.DBus',
                path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus',
                member='GetNameOwner',
                signature='s',
                body=[PLAYERCTLD_NAME],
            )
        )
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body
        self = cls(bus, reply.body[0])
        bus.add_message_handler(self._handle)
        await bus.call(
            Message(
                destination='org.freedesktop.DBus',
                path='/org/freedesktop/DBus',
                interface='org.freedesktop.DBus',
                member='AddMatch',
                signature='s',
                body=[f"type='signal',path='{MPRIS_PATH}'"],
            )
        )
        return self

    def _handle(self, msg):
        if msg.message_type == MessageType.SIGNAL and msg.sender == self.owner:
            self.queue.put_nowait((msg.interface, msg.member, msg.body))

    async def next(self, interface, member, timeout=2.0):
        '''Wait for the next signal with this interface and member.'''
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            assert remaining > 0, f'no {interface}.{member} signal'
            got = await asyncio.wait_for(self.queue.get(), remaining)
            if got[:2] == (interface, member):
                return got[2]

    async def until_end(self, timeout=2.0):
        '''Everything emitted up to and including ActivePlayerChangeEnd.'''
        seen = []
        while True:
            signal = await asyncio.wait_for(self.queue.get(), timeout)
            seen.append(signal)
            if signal[:2] == (PLAYERCTLD_INTERFACE, 'ActivePlayerChangeEnd'):
                return seen

    async def close(self):
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()


async def playerctld_call(bus, interface, member, signature='', body=None):
    '''Call a method on the running playerctld over the given dbus_next bus.'''
    return await bus.call(
        Message(
            destination=PLAYERCTLD_NAME,
            interface=interface,
            path=MPRIS_PATH,
            member=member,
            signature=signature,
            body=body or [],
        )
    )


async def player_names(bus):
    '''PlayerNames of the running playerctld, most recently active first.'''
    reply = await playerctld_call(
        bus,
        'org.freedesktop.DBus.Properties',
        'Get',
        'ss',
        ['org._5mdt.playerctld', 'PlayerNames'],
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    return reply.body[0].value


async def wait_for_player_names(bus, expected, timeout=2.0):
    """Wait until PlayerNames equals `expected`; returns it."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        names = await player_names(bus)
        if names == expected:
            return names
        assert asyncio.get_running_loop().time() < deadline, (
            f'PlayerNames is {names}, expected {expected}'
        )
        await asyncio.sleep(0.02)

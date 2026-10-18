import asyncio
import os
import signal

from dbus_next import Message

from .mpris import name_owner_pid, wait_for_name
from .playerctl import register

PLAYERCTLD_NAME = 'org.mpris.MediaPlayer2.playerctld'
MPRIS_PATH = '/org/mpris/MediaPlayer2'


async def start_playerctld(bus_address, debug=False):
    # stop a playerctld that is already on this test bus (e.g. one started by
    # dbus activation), without touching any other playerctld on the system
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)
    if pid is not None:
        os.kill(pid, signal.SIGTERM)
        await wait_for_name(bus_address, PLAYERCTLD_NAME, present=False)
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    env['G_MESSAGES_DEBUG'] = 'playerctl'
    proc = await asyncio.create_subprocess_shell(
        'exec playerctld',
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )

    async def reader(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
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

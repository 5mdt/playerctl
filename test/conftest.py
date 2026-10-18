import asyncio

import pytest

from .helpers.mpris import setup_mpris
from .helpers.playerctl import PlayerctlCli, stop_all


@pytest.fixture(autouse=True)
async def cleanup_processes():
    yield
    await stop_all()


@pytest.fixture()
async def bus_address():
    proc = await asyncio.create_subprocess_exec(
        'dbus-daemon',
        '--session',
        '--nofork',
        '--print-address=1',
        stdout=asyncio.subprocess.PIPE,
    )
    address = (await proc.stdout.readline()).decode().strip()
    assert address

    yield address

    if proc.returncode is None:
        proc.terminate()
    await proc.wait()


@pytest.fixture()
def playerctl(bus_address):
    return PlayerctlCli(bus_address)


@pytest.fixture()
async def mpris_factory(bus_address):
    '''Create mock MPRIS players that are disconnected on teardown.'''
    created = []

    async def make(*names, system=False):
        players = await setup_mpris(
            *names,
            bus_address=None if system else bus_address,
            system=system,
        )
        created.extend(players)
        return players

    yield make

    await asyncio.gather(*(p.disconnect() for p in created))

import pytest
from dbus_next.aio import MessageBus

from ..helpers.daemon import start_playerctld, stop_playerctld


@pytest.fixture()
async def playerctld(bus_address):
    '''A playerctld running on the test bus.'''
    proc = await start_playerctld(bus_address)
    yield proc
    await stop_playerctld(proc)


@pytest.fixture()
async def daemon_bus(bus_address):
    '''A dbus_next connection for talking to playerctld directly.'''
    bus = await MessageBus(bus_address=bus_address).connect()
    yield bus
    bus.disconnect()
    await bus.wait_for_disconnect()

"""US-10.7: As an existing user, I want a one-time warning when the legacy
interface is used, and a fallback to it in `shift`/`unshift` for older
daemons."""

import asyncio

import pytest
from dbus_next import MessageType

from ..helpers.daemon import playerctld_call, playerctld_shift
from ..helpers.mpris import (
    PLAYERCTLD_INTERFACE,
    PLAYERCTLD_INTERFACE_LEGACY,
    setup_playerctld,
)

WARNING = 'deprecated D-Bus interface'


async def warnings(playerctld):
    # let the daemon's stderr reader catch up
    await asyncio.sleep(0.2)
    return [line for line in playerctld.log if WARNING in line]


async def test_legacy_interface_warns_exactly_once(
    playerctld, daemon_bus, mpris_factory
):
    await mpris_factory('player1')

    for _ in range(3):
        reply = await playerctld_call(
            daemon_bus, PLAYERCTLD_INTERFACE_LEGACY, 'Shift'
        )
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body

    found = await warnings(playerctld)
    assert len(found) == 1, playerctld.log
    assert PLAYERCTLD_INTERFACE_LEGACY in found[0]
    assert PLAYERCTLD_INTERFACE in found[0]


async def test_current_interface_does_not_warn(
    playerctld, daemon_bus, mpris_factory
):
    await mpris_factory('player1')

    reply = await playerctld_call(daemon_bus, PLAYERCTLD_INTERFACE, 'Shift')

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert await warnings(playerctld) == []


async def test_cli_shift_does_not_use_the_legacy_interface(
    bus_address, playerctld, mpris_factory
):
    await mpris_factory('player1')

    assert await playerctld_shift(bus_address) == 0

    assert await warnings(playerctld) == []


@pytest.mark.parametrize('reverse', [False, True])
async def test_shift_falls_back_to_legacy_interface(reverse, bus_address):
    daemon = await setup_playerctld(
        bus_address, interface=PLAYERCTLD_INTERFACE_LEGACY
    )

    code = await playerctld_shift(bus_address, reverse=reverse)

    assert code == 0
    assert daemon.unshift_called == reverse
    assert daemon.shift_called == (not reverse)
    await daemon.disconnect()


async def test_shift_prefers_the_current_interface(bus_address):
    daemon = await setup_playerctld(bus_address)

    code = await playerctld_shift(bus_address)

    assert code == 0
    assert daemon.shift_called
    await daemon.disconnect()

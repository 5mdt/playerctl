"""US-10.6: As an existing user, I want the legacy
`com.github.altdesktop.playerctld` interface to keep working and be marked
deprecated."""

from xml.etree import ElementTree

import pytest
from dbus_next import MessageType

from ..helpers.daemon import playerctld_call
from ..helpers.mpris import PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY

INTERFACES = [PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY]


@pytest.mark.parametrize('interface', INTERFACES)
async def test_only_the_legacy_interface_is_deprecated(
    interface, playerctld, daemon_bus
):
    reply = await playerctld_call(
        daemon_bus, 'org.freedesktop.DBus.Introspectable', 'Introspect'
    )

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    node = ElementTree.fromstring(reply.body[0])
    iface = node.find(f"interface[@name='{interface}']")
    deprecated = iface.find(
        "annotation[@name='org.freedesktop.DBus.Deprecated']"
    )
    assert (deprecated is not None) == (
        interface == PLAYERCTLD_INTERFACE_LEGACY
    )


@pytest.mark.parametrize('interface', INTERFACES)
async def test_shift_on_both_interfaces(
    interface, playerctld, daemon_bus, mpris_factory
):
    await mpris_factory('player1')

    reply = await playerctld_call(daemon_bus, interface, 'Shift')

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body == ['org.mpris.MediaPlayer2.player1']

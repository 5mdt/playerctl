"""US-10.4: As an integrator, I want a `PlayerNames` property on
`org._5mdt.playerctld`."""

import pytest
from dbus_next import MessageType

from ..helpers.daemon import playerctld_call
from ..helpers.mpris import PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY


@pytest.mark.parametrize(
    'interface', [PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY]
)
async def test_player_names_property(
    interface, playerctld, daemon_bus, mpris_factory
):
    await mpris_factory('player1')

    reply = await playerctld_call(
        daemon_bus,
        'org.freedesktop.DBus.Properties',
        'Get',
        'ss',
        [interface, 'PlayerNames'],
    )

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body[0].value == ['org.mpris.MediaPlayer2.player1']

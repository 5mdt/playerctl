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


async def test_named_player_is_not_replaced_by_its_instance(
    playerctl, playerctld, mpris_factory
):
    # 5mdt/playerctl#63: `-p mpv` selected `mpv.instanceN` when that instance
    # was the most recently active one
    [mpv, instance] = await mpris_factory('mpv', 'mpv.instance123')
    await mpv.set_artist_title('artist', 'one')
    await instance.set_artist_title('artist', 'two')

    result = await playerctl.run(
        "-p mpv metadata --format '{{playerInstance}} {{title}}'"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'mpv one'

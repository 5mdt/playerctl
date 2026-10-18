"""US-10.11: As a scripter, I want the error message of a player to reach me
through playerctld, not a generic one."""

from dbus_next import MessageType

from ..helpers.daemon import playerctld_call

PLAYER = 'org.mpris.MediaPlayer2.Player'


async def test_error_name_and_message_are_forwarded(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    mpris.error = 'the player broke'

    reply = await playerctld_call(daemon_bus, PLAYER, 'Play')

    assert reply.message_type == MessageType.ERROR
    assert reply.error_name == 'org.example.Error'
    assert reply.body == ['the player broke']


async def test_error_message_reaches_the_cli(
    playerctl, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    mpris.error = 'the player broke'

    result = await playerctl.run('-p playerctld play')

    assert result.returncode == 1
    assert 'the player broke' in result.stderr, result.stderr
    assert 'Failed to call method' not in result.stderr


async def test_property_write_error_message_is_forwarded(
    playerctl, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    mpris.error = 'volume is locked'

    result = await playerctl.run('-p playerctld volume 0.5')

    assert result.returncode == 1
    assert 'volume is locked' in result.stderr, result.stderr

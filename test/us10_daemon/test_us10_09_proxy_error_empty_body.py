"""US-10.9: As a user, I want playerctld to survive a player returning an
error with an empty body."""

from dbus_next import Message, MessageType


async def test_proxy_error_empty_body(playerctl, playerctld, mpris_factory):
    [mpris] = await mpris_factory('emptyerror')
    await mpris.set_artist_title('artist', 'title')

    # reply to Play with an error that has no body
    def empty_error_handler(msg):
        if (
            msg.message_type == MessageType.METHOD_CALL
            and msg.member == 'Play'
        ):
            return Message(
                message_type=MessageType.ERROR,
                error_name='org.freedesktop.DBus.Error.Failed',
                reply_serial=msg.serial,
                destination=msg.sender,
            )

    mpris.bus.add_message_handler(empty_error_handler)

    cmd = await playerctl.run('-p playerctld play')
    assert cmd.returncode == 1, cmd.stdout
    assert 'Failed to call method' in cmd.stderr, cmd.stderr
    assert playerctld.returncode is None, 'playerctld crashed'

    # the daemon should still be able to proxy calls
    mpris.bus.remove_message_handler(empty_error_handler)
    cmd = await playerctl.run('-p playerctld play')
    assert cmd.returncode == 0, cmd.stderr
    assert mpris.play_called

"""US-10.1: As a user, I want playerctld to make the player with the most
recent property change the active one."""

from asyncio import Queue

from dbus_next import Message, MessageType

from ..helpers.mpris import PLAYERCTLD_INTERFACE


async def test_play_goes_to_most_recently_active_player(
    playerctl, playerctld, mpris_factory
):
    async def run(cmd):
        return await playerctl.run('-p playerctld ' + cmd)

    [mpris1, mpris2, mpris3] = await mpris_factory(
        'daemon1', 'daemon2', 'daemon3'
    )
    await mpris2.set_artist_title('artist', 'title')
    cmd = await run('play')
    assert cmd.returncode == 0, cmd.stdout
    assert mpris2.play_called, cmd.stdout
    mpris2.reset()

    await mpris1.set_artist_title('artist', 'title')
    cmd = await run('play')
    assert cmd.returncode == 0, cmd.stderr
    assert mpris1.play_called
    mpris1.reset()

    await mpris3.set_artist_title('artist', 'title')
    cmd = await run('play')
    assert cmd.returncode == 0, cmd.stderr
    assert mpris3.play_called
    mpris3.reset()

    await mpris3.disconnect()
    cmd = await run('play')
    assert cmd.returncode == 0, cmd.stderr
    assert mpris1.play_called
    mpris1.reset()


async def test_player_names_follow_activity(
    playerctld, daemon_bus, mpris_factory
):
    queue = Queue()

    reply = await daemon_bus.call(
        Message(
            destination='org.freedesktop.DBus',
            interface='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            member='AddMatch',
            signature='s',
            body=["sender='org.mpris.MediaPlayer2.playerctld'"],
        )
    )

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body

    def message_handler(message):
        if (
            message.member == 'PropertiesChanged'
            and message.body[0] == PLAYERCTLD_INTERFACE
            and 'PlayerNames' in message.body[1]
        ):
            queue.put_nowait(message.body[1]['PlayerNames'].value)

    def player_list(*args):
        return [f'org.mpris.MediaPlayer2.{name}' for name in args]

    daemon_bus.add_message_handler(message_handler)

    [mpris1] = await mpris_factory('player1')

    assert player_list('player1') == await queue.get()

    [mpris2] = await mpris_factory('player2')

    assert player_list('player2', 'player1') == await queue.get()

    # changing artist/title should bump the player up
    await mpris1.set_artist_title('artist1', 'title1', '/1')

    assert player_list('player1', 'player2') == await queue.get()

    # if properties are not actually different, it shouldn't update
    await mpris2.set_artist_title('artist2', 'title2', '/2')
    assert player_list('player2', 'player1') == await queue.get()

    await mpris1.set_artist_title('artist1', 'title1', '/1')
    await mpris1.ping()
    assert queue.empty()

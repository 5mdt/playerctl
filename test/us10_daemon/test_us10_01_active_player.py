"""US-10.1: As a user, I want playerctld to make the player with the most
recent property change the active one."""

from asyncio import Queue

from dbus_next import Message, MessageType, NameFlag, RequestNameReply
from dbus_next.aio import MessageBus

from ..helpers.daemon import SignalListener, player_names, settle
from ..helpers.mpris import PLAYERCTLD_INTERFACE, MprisPlayer, MprisRoot

PREFIX = 'org.mpris.MediaPlayer2.'


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


async def test_position_change_does_not_make_player_active(
    playerctld, daemon_bus, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')

    # Position is cached separately and never counts as a change
    await mpris1.emit_properties(position=5000000)
    await settle()

    assert await player_names(daemon_bus) == [
        PREFIX + 'player2',
        PREFIX + 'player1',
    ]


async def test_seeked_from_inactive_player_makes_it_active(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    listener = await SignalListener.start(bus_address)

    mpris1.seeked_value = 7000000
    mpris1.Seeked()
    await mpris1.ping()

    assert await listener.next(
        PLAYERCTLD_INTERFACE, 'ActivePlayerChangeEnd'
    ) == [PREFIX + 'player1']
    assert await player_names(daemon_bus) == [
        PREFIX + 'player1',
        PREFIX + 'player2',
    ]
    await listener.close()


async def test_inactive_player_vanishing_changes_nothing_else(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris1, mpris2, mpris3] = await mpris_factory(
        'player1', 'player2', 'player3'
    )
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    await mpris3.set_artist_title('artist3', 'title3')
    listener = await SignalListener.start(bus_address)

    await mpris2.disconnect()
    await settle()

    assert await player_names(daemon_bus) == [
        PREFIX + 'player3',
        PREFIX + 'player1',
    ]
    assert listener.queue.empty(), listener.queue.get_nowait()
    await listener.close()


async def test_player_whose_name_owner_is_replaced_stays_managed(
    bus_address, playerctl, playerctld, daemon_bus
):
    name = PREFIX + 'replaced'

    async def own(flags):
        bus = await MessageBus(bus_address=bus_address).connect()
        player = MprisPlayer(bus)
        bus.export('/org/mpris/MediaPlayer2', player)
        bus.export('/org/mpris/MediaPlayer2', MprisRoot())
        assert await bus.request_name(name, flags) == (
            RequestNameReply.PRIMARY_OWNER
        )
        return bus, player

    old_bus, old = await own(NameFlag.ALLOW_REPLACEMENT)
    await old.set_artist_title('artist1', 'title1')

    # the name changes hands directly, there is no moment without an owner
    new_bus, new = await own(NameFlag.REPLACE_EXISTING)
    await settle()

    assert await player_names(daemon_bus) == [name]
    result = await playerctl.run('-p playerctld play')
    assert result.returncode == 0, result.stderr
    assert new.play_called
    assert not old.play_called

    for bus in (old_bus, new_bus):
        bus.disconnect()
        await bus.wait_for_disconnect()

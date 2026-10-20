"""US-10.2: As a user, I want playerctld to appear as an MPRIS player that
forwards calls, properties and signals to the active player."""

import pytest
from dbus_next import MessageType, Variant

from ..helpers.daemon import SignalListener, playerctld_call
from ..helpers.follow import follow_cmd

PLAYER = 'org.mpris.MediaPlayer2.Player'
TRACKLIST = 'org.mpris.MediaPlayer2.TrackList'
PLAYLISTS = 'org.mpris.MediaPlayer2.Playlists'
ROOT = 'org.mpris.MediaPlayer2'
PROPERTIES = 'org.freedesktop.DBus.Properties'
PLAYERCTLD = 'org._5mdt.playerctld'


async def test_proxies_metadata_of_the_active_player(
    playerctl, playerctld, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    proc = await playerctl.start(follow_cmd('playerctld'))

    await mpris1.set_artist_title('artist1', 'title1')
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    [mpris3] = await mpris_factory('player3')
    await mpris3.set_artist_title('artist3', 'title3')
    line = await proc.queue.get()

    if line == '':
        # the line might be blank here because of the test setup
        line = await proc.queue.get()

    assert line == 'playerctld: artist3 - title3', proc.queue

    await mpris1.set_artist_title('artist4', 'title4')
    line = await proc.queue.get()
    assert line == 'playerctld: artist4 - title4', proc.queue

    await mpris1.set_artist_title('artist5', 'title5')
    line = await proc.queue.get()
    assert line == 'playerctld: artist5 - title5', proc.queue

    await mpris1.disconnect()
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue


async def test_forwards_seeked_signal_of_the_active_player(
    bus_address, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    mpris.seeked_value = 5000000
    mpris.Seeked()
    await mpris.ping()

    body = await listener.next(PLAYER, 'Seeked')
    assert body == [5000000]
    await listener.close()


async def test_forwards_tracklist_calls_and_properties(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1', tracklist=True)
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(
        daemon_bus, PROPERTIES, 'Get', 'ss', [TRACKLIST, 'Tracks']
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body[0].value == ['/track/1', '/track/2']

    reply = await playerctld_call(
        daemon_bus, TRACKLIST, 'GoTo', 'o', ['/track/2']
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert mpris.tracklist.go_to_called_with == '/track/2'


async def test_forwards_tracklist_property_changes(
    bus_address, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1', tracklist=True)
    await mpris.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    mpris.tracklist.tracks = ['/track/3']
    mpris.tracklist.emit_properties_changed({'Tracks': ['/track/3']})
    await mpris.ping()

    body = await listener.next(PROPERTIES, 'PropertiesChanged')
    while body[0] != TRACKLIST:
        body = await listener.next(PROPERTIES, 'PropertiesChanged')
    assert body[1]['Tracks'].value == ['/track/3']
    await listener.close()


async def test_forwards_tracklist_signals(
    bus_address, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1', tracklist=True)
    await mpris.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    mpris.tracklist.TrackAdded()
    await mpris.ping()

    body = await listener.next(TRACKLIST, 'TrackAdded')
    assert body[1] == '/track/1'
    await listener.close()


async def test_forwards_playlists_calls_and_properties(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1', playlists=True)
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(
        daemon_bus, PROPERTIES, 'Get', 'ss', [PLAYLISTS, 'PlaylistCount']
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body[0].value == 3

    reply = await playerctld_call(
        daemon_bus, PLAYLISTS, 'ActivatePlaylist', 'o', ['/playlist/1']
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert mpris.playlists.activate_playlist_called_with == '/playlist/1'


async def test_forwards_playlists_signals(
    bus_address, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1', playlists=True)
    await mpris.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    mpris.playlists.PlaylistChanged()
    await mpris.ping()

    body = await listener.next(PLAYLISTS, 'PlaylistChanged')
    assert body[0][0] == '/playlist/1'
    await listener.close()


async def get_property(bus, interface, name):
    reply = await playerctld_call(
        bus, PROPERTIES, 'Get', 'ss', [interface, name]
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    return reply.body[0].value


async def set_property(bus, interface, name, signature, value):
    return await playerctld_call(
        bus,
        PROPERTIES,
        'Set',
        'ssv',
        [interface, name, Variant(signature, value)],
    )


async def test_root_methods_go_to_the_active_player(
    playerctld, daemon_bus, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')

    for member in ('Raise', 'Quit'):
        reply = await playerctld_call(daemon_bus, ROOT, member)
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body

    assert mpris2.root.raise_called
    assert mpris2.root.quit_called
    assert not mpris1.root.raise_called
    assert not mpris1.root.quit_called


async def test_gets_player_and_root_properties(
    playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    mpris.volume = 0.25
    mpris.rate = 1.0
    mpris.loop_status = 'Playlist'
    mpris.shuffle = True

    assert await get_property(daemon_bus, PLAYER, 'Volume') == 0.25
    assert await get_property(daemon_bus, PLAYER, 'Rate') == 1.0
    assert await get_property(daemon_bus, PLAYER, 'LoopStatus') == 'Playlist'
    assert await get_property(daemon_bus, PLAYER, 'Shuffle') is True
    assert await get_property(daemon_bus, ROOT, 'Identity') == (
        'playerctl test client'
    )
    assert await get_property(daemon_bus, ROOT, 'CanRaise') is False


@pytest.mark.parametrize(
    'interface, keys',
    [
        (PLAYER, {'Volume', 'Rate', 'LoopStatus', 'Shuffle', 'Metadata'}),
        (ROOT, {'Identity', 'CanRaise', 'HasTrackList'}),
    ],
)
async def test_get_all_properties(
    interface, keys, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    reply = await playerctld_call(
        daemon_bus, PROPERTIES, 'GetAll', 's', [interface]
    )

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert keys <= set(reply.body[0])


async def test_sets_writable_properties(playerctld, daemon_bus, mpris_factory):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    for name, signature, value in [
        ('Volume', 'd', 0.5),
        ('Rate', 'd', 1.0),
        ('LoopStatus', 's', 'Track'),
        ('Shuffle', 'b', True),
    ]:
        reply = await set_property(daemon_bus, PLAYER, name, signature, value)
        assert reply.message_type == MessageType.METHOD_RETURN, reply.body

    assert mpris.volume == 0.5
    assert mpris.rate == 1.0
    assert mpris.loop_status == 'Track'
    assert mpris.shuffle is True


async def test_get_all_playerctld_properties(
    playerctld, daemon_bus, mpris_factory
):
    await mpris_factory('player1')

    reply = await playerctld_call(
        daemon_bus, PROPERTIES, 'GetAll', 's', [PLAYERCTLD]
    )

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body[0]['PlayerNames'].value == [
        'org.mpris.MediaPlayer2.player1'
    ]


async def test_cli_commands_through_the_daemon(
    playerctl, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1', '/1')
    mpris.position = 42000000

    async def run(cmd):
        result = await playerctl.run('-p playerctld ' + cmd)
        assert result.returncode == 0, result.stderr
        return result.stdout

    await run('volume 0.5')
    assert mpris.volume == 0.5
    assert await run('volume') == '0.500000'

    await run('loop Track')
    assert mpris.loop_status == 'Track'
    assert await run('loop') == 'Track'

    await run('shuffle on')
    assert mpris.shuffle is True
    assert await run('shuffle') == 'On'

    assert float(await run('position')) == pytest.approx(42.0, abs=0.01)
    await run('position 30')
    assert mpris.set_position_called_with == ('/1', 30000000)

    await run('open https://example.com/a.mp3')
    assert mpris.open_uri_called_with == 'https://example.com/a.mp3'

    assert await run('metadata xesam:title') == 'title1'


async def test_can_control_is_true_with_an_active_player(
    playerctld, daemon_bus, mpris_factory
):
    # 5mdt/playerctl#30: rygel ignores MPRIS services that are not controllable
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')

    assert await get_property(daemon_bus, PLAYER, 'CanControl') is True

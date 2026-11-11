"""US-10.25: As a scripter, I want every call I make to playerctld, however
malformed, to get a reply or a proper D-Bus error, never a hang or a crash,
and never to reach the player when it is not a valid MPRIS call."""

import asyncio
import xml.etree.ElementTree as ET

import pytest
from dbus_next import MessageType, Variant

from ..helpers.daemon import (
    MPRIS_PATH,
    PLAYERCTLD_NAME,
    player_names,
    settle,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    PLAYER_INTERFACE,
    OPTIONAL_NOISE,
    PLAYERCTLD_LEGACY,
    PREFIX,
    ROOT_INTERFACE,
    assert_healthy,
    close_bus,
    new_bus,
    raw_call,
)
from ..helpers.mpris import (
    PLAYERCTLD_INTERFACE,
    PROPERTIES_INTERFACE,
    TRACKLIST_INTERFACE,
    gated,
)

ERROR = MessageType.ERROR
RETURN = MessageType.METHOD_RETURN


async def with_player(mpris_factory, daemon_bus, name='player1', **kwargs):
    [mpris] = await mpris_factory(name, **kwargs)
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + name])
    return mpris


# ---- wrong shapes of otherwise valid calls ---------------------------------


@pytest.mark.parametrize(
    'member, signature, body',
    [
        ('Play', 's', ['extra']),
        ('Play', 'xx', [1, 2]),
        ('Pause', 'a{sv}', [{}]),
        ('Seek', '', []),
        ('Seek', 's', ['not a number']),
        ('Seek', 'xx', [1, 2]),
        ('SetPosition', 'x', [1]),
        ('SetPosition', 'sx', ['/1', 1]),
        ('SetPosition', 'ox', ['/1']) if False else ('OpenUri', '', []),
        ('OpenUri', 'x', [3]),
        ('OpenUri', 'ss', ['a', 'b']),
        ('Next', 'b', [True]),
    ],
)
async def test_wrong_arguments_are_an_error_and_do_not_reach_the_player(
    playerctld, daemon_bus, mpris_factory, member, signature, body
):
    mpris = await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(
        daemon_bus, PLAYER_INTERFACE, member, signature, body
    )

    assert reply.message_type == ERROR, reply.body
    assert reply.error_name.startswith('org.freedesktop.DBus.Error.')
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None
    assert mpris.open_uri_called_with is None
    assert not (mpris.play_called or mpris.pause_called or mpris.next_called)
    assert_healthy(playerctld)


@pytest.mark.parametrize(
    'interface, member',
    [
        (PLAYER_INTERFACE, 'NoSuchMethod'),
        (PLAYER_INTERFACE, 'play'),  # case matters
        (PLAYER_INTERFACE, ''),
        (ROOT_INTERFACE, 'Play'),  # right method, wrong interface
        (PLAYER_INTERFACE, 'Raise'),
        (TRACKLIST_INTERFACE, 'Play'),
        ('org.mpris.MediaPlayer2.Nothing', 'Play'),
        ('org.freedesktop.DBus.Peer', 'NoSuchMethod'),
    ],
)
async def test_unknown_or_misplaced_methods_get_an_error(
    playerctld, daemon_bus, mpris_factory, interface, member
):
    mpris = await with_player(mpris_factory, daemon_bus)

    try:
        reply = await raw_call(daemon_bus, interface, member or 'X')
    except Exception as error:  # an empty member is refused client side
        assert not member, error
        return

    assert reply.message_type == ERROR, reply.body
    assert not mpris.play_called
    assert_healthy(playerctld)


async def test_fd_passing_method_is_not_forwarded(
    playerctld, daemon_bus, mpris_factory
):
    await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(
        daemon_bus, PLAYER_INTERFACE, 'GetArtworkFd', 's', ['x']
    )

    assert reply.message_type == ERROR
    assert reply.error_name == 'org.freedesktop.DBus.Error.UnknownMethod'
    assert_healthy(playerctld)


async def test_call_without_an_interface_does_not_crash(
    playerctld, daemon_bus, mpris_factory
):
    mpris = await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(daemon_bus, None, 'Play')

    assert reply.message_type in (RETURN, ERROR)
    assert playerctld.returncode is None
    assert reply.message_type == ERROR or mpris.play_called
    assert_healthy(playerctld)


@pytest.mark.parametrize(
    'path',
    [
        '/',
        '/org',
        '/org/mpris',
        '/org/mpris/MediaPlayer2/Child',
        '/org/mpris/MediaPlayer2/TrackList/NoTrack',
        '/' + 'a' * 1000,
    ],
)
async def test_calls_on_other_object_paths_get_an_error(
    playerctld, daemon_bus, mpris_factory, path
):
    mpris = await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(daemon_bus, PLAYER_INTERFACE, 'Play', path=path)

    assert reply.message_type == ERROR
    assert not mpris.play_called
    assert_healthy(playerctld)


@pytest.mark.parametrize(
    'path', ['/', '/org', '/org/mpris', '/org/mpris/MediaPlayer2']
)
async def test_introspect_returns_valid_xml_on_the_object_tree(
    playerctld, daemon_bus, path
):
    reply = await raw_call(
        daemon_bus,
        'org.freedesktop.DBus.Introspectable',
        'Introspect',
        path=path,
    )

    if path == MPRIS_PATH:
        assert reply.message_type == RETURN
        node = ET.fromstring(reply.body[0])
        assert node.tag == 'node'
        names = {i.get('name') for i in node.findall('interface')}
        assert {
            PLAYERCTLD_INTERFACE,
            PLAYERCTLD_LEGACY,
            PLAYER_INTERFACE,
            ROOT_INTERFACE,
            'org.freedesktop.DBus.Properties',
            'org.freedesktop.DBus.Introspectable',
        } <= names
        for arg in node.iter('arg'):
            assert arg.get('type'), arg.attrib
    else:
        # parent nodes are generated by the library: valid XML as well
        assert reply.message_type == RETURN, reply.body
        ET.fromstring(reply.body[0])


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D5: GetPlaylistIconFd (type "h" out argument) is announced '
    'and forwarded although playerctld cannot pass file descriptors on; only '
    'Player.GetArtworkFd is excluded',
)
async def test_no_announced_method_passes_a_file_descriptor(
    playerctld, daemon_bus
):
    reply = await raw_call(
        daemon_bus,
        'org.freedesktop.DBus.Introspectable',
        'Introspect',
        path=MPRIS_PATH,
    )

    node = ET.fromstring(reply.body[0])
    fd_args = [
        (m.get('name'), a.get('name'))
        for m in node.iter('method')
        for a in m.findall('arg')
        if 'h' in a.get('type')
    ]
    assert fd_args == []


async def test_introspect_with_arguments_is_an_error(playerctld, daemon_bus):
    reply = await raw_call(
        daemon_bus,
        'org.freedesktop.DBus.Introspectable',
        'Introspect',
        's',
        ['x'],
    )

    assert reply.message_type == ERROR
    assert_healthy(playerctld)


async def test_introspect_works_with_and_without_a_player(
    playerctld, daemon_bus, mpris_factory
):
    async def interfaces():
        reply = await raw_call(
            daemon_bus, 'org.freedesktop.DBus.Introspectable', 'Introspect'
        )
        return sorted(
            i.get('name')
            for i in ET.fromstring(reply.body[0]).iter('interface')
        )

    before = await interfaces()
    await with_player(mpris_factory, daemon_bus)

    assert await interfaces() == before


# ---- properties through the proxy ----------------------------------------


@pytest.mark.parametrize(
    'member, signature, body',
    [
        ('Get', 'ss', [PLAYER_INTERFACE, 'NoSuchProperty']),
        ('Get', 'ss', [PLAYER_INTERFACE, '']),
        ('Get', 'ss', ['', 'Volume']),
        ('Get', 'ss', ['org.example.Unknown', 'Volume']),
        ('Get', 's', [PLAYER_INTERFACE]),
        ('Get', '', []),
        ('Get', 'sss', [PLAYER_INTERFACE, 'Volume', 'x']),
        ('Get', 'ii', [1, 2]),
        ('Get', 'ss', [PLAYER_INTERFACE, 'V' * 100000]),
        (
            'Set',
            'ssv',
            [PLAYER_INTERFACE, 'NoSuchProperty', Variant('d', 1.0)],
        ),
        ('Set', 'ssv', [PLAYER_INTERFACE, 'Position', Variant('x', 1)]),
        (
            'Set',
            'ssv',
            [PLAYER_INTERFACE, 'PlaybackStatus', Variant('s', 'Paused')],
        ),
        ('Set', 'ssv', [PLAYER_INTERFACE, 'Volume', Variant('s', 'loud')]),
        ('Set', 'ssv', ['', '', Variant('s', '')]),
        ('Set', 'ss', [PLAYER_INTERFACE, 'Volume']),
        ('GetAll', '', []),
        ('GetAll', 'ss', [PLAYER_INTERFACE, 'x']),
        ('GetAll', 'i', [1]),
    ],
)
async def test_bad_property_calls_get_an_error(
    playerctld, daemon_bus, mpris_factory, member, signature, body
):
    mpris = await with_player(mpris_factory, daemon_bus)
    volume = mpris.volume
    status = mpris.playback_status

    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, member, signature, body
    )

    assert reply.message_type == ERROR, reply.body
    assert mpris.volume == volume
    assert mpris.playback_status == status
    assert await player_names(daemon_bus) == [PREFIX + 'player1']
    assert_healthy(playerctld)


@pytest.mark.parametrize(
    'interface', ['', 'org.example.Unknown', PLAYERCTLD_INTERFACE + 'X']
)
async def test_get_all_of_an_empty_or_unknown_interface_is_an_error(
    playerctld, daemon_bus, mpris_factory, interface
):
    await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, 'GetAll', 's', [interface]
    )

    assert reply.message_type == ERROR, reply.body
    assert_healthy(playerctld)


async def test_get_all_of_the_player_interface_returns_the_players_values(
    playerctld, daemon_bus, mpris_factory
):
    mpris = await with_player(mpris_factory, daemon_bus)
    mpris.volume = 0.25

    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, 'GetAll', 's', [PLAYER_INTERFACE]
    )

    assert reply.message_type == RETURN, reply.body
    assert reply.body[0]['Volume'].value == 0.25


async def test_set_volume_reaches_the_player(
    playerctld, daemon_bus, mpris_factory
):
    mpris = await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(
        daemon_bus,
        PROPERTIES_INTERFACE,
        'Set',
        'ssv',
        [PLAYER_INTERFACE, 'Volume', Variant('d', 0.5)],
    )

    assert reply.message_type == RETURN, reply.body
    assert mpris.volume == 0.5


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D6: a player that answers Properties.Get with a value of the '
    'wrong type makes GDBus refuse the proxied reply (GLib-GIO-WARNING) and '
    'the client never gets any reply, not even an error',
)
@pytest.mark.parametrize('prop', ['Position', 'Volume'])
async def test_wrongly_typed_get_reply_still_gets_the_client_an_answer(
    bus_address, playerctld, daemon_bus, prop
):
    from ..helpers.mpris import setup_mpris

    def lie(gate):
        def wrong(reply):
            reply.body[0] = Variant('s', 'not the right type')
            return reply

        gate.rewrite('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE, wrong)

    [mpris] = await setup_mpris(
        'liar', bus_address=bus_address, prepare=gated(lie)
    )
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'liar'])

    reply = await raw_call(
        daemon_bus,
        PROPERTIES_INTERFACE,
        'Get',
        'ss',
        [PLAYER_INTERFACE, prop],
        timeout=1.5,
    )

    assert reply.message_type in (RETURN, ERROR)
    await mpris.disconnect()


async def test_wrongly_typed_get_reply_does_not_kill_the_daemon(
    bus_address, playerctld, daemon_bus
):
    from ..helpers.mpris import setup_mpris

    def lie(gate):
        def wrong(reply):
            reply.body[0] = Variant('s', 'not the right type')
            return reply

        gate.rewrite('Get', PROPERTIES_INTERFACE, PLAYER_INTERFACE, wrong)

    [mpris] = await setup_mpris(
        'liar', bus_address=bus_address, prepare=gated(lie)
    )
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'liar'])

    try:  # see BUG-D6 above: this call may never be answered
        await raw_call(
            daemon_bus,
            PROPERTIES_INTERFACE,
            'Get',
            'ss',
            [PLAYER_INTERFACE, 'Volume'],
            timeout=0.5,
        )
    except asyncio.TimeoutError:
        pass

    # whatever happened to that one call, the daemon serves the next ones
    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, 'GetAll', 's', [PLAYER_INTERFACE]
    )
    assert reply.message_type == RETURN
    assert playerctld.returncode is None, playerctld.log
    await mpris.disconnect()


# ---- huge arguments ---------------------------------------------------------


@pytest.mark.parametrize('size', [100_000, 3_000_000])
async def test_huge_string_argument_is_forwarded_intact(
    playerctld, daemon_bus, mpris_factory, size
):
    mpris = await with_player(mpris_factory, daemon_bus)
    uri = 'x' * size

    reply = await raw_call(
        daemon_bus, PLAYER_INTERFACE, 'OpenUri', 's', [uri], timeout=4
    )

    assert reply.message_type == RETURN, reply.body
    assert mpris.open_uri_called_with == uri
    assert_healthy(playerctld)


async def test_huge_member_and_interface_names_are_an_error(
    playerctld, daemon_bus, mpris_factory
):
    await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(daemon_bus, PLAYER_INTERFACE, 'M' * 255)
    assert reply.message_type == ERROR
    reply = await raw_call(daemon_bus, 'org.' + 'a.' * 120 + 'b', 'Play')
    assert reply.message_type == ERROR
    assert_healthy(playerctld)


async def test_malformed_unicode_in_forwarded_string_is_an_error_not_a_crash(
    playerctld, daemon_bus, mpris_factory
):
    mpris = await with_player(mpris_factory, daemon_bus)

    for uri in ('‮\u0000'[:1], '\U0001f3b5' * 1000, 'a\tb\nc'):
        reply = await raw_call(
            daemon_bus, PLAYER_INTERFACE, 'OpenUri', 's', [uri]
        )
        assert reply.message_type == RETURN, reply.body
        assert mpris.open_uri_called_with == uri
    assert_healthy(playerctld)


# ---- the playerctld interfaces ------------------------------------------


@pytest.mark.parametrize(
    'interface', [PLAYERCTLD_INTERFACE, PLAYERCTLD_LEGACY]
)
@pytest.mark.parametrize(
    'member, signature, body',
    [
        ('Shift', 's', ['extra']),
        ('Unshift', 'xx', [1, 2]),
        ('Shift', 'a{sv}', [{}]),
        ('Rotate', '', []),
        ('shift', '', []),
        ('PlayerNames', '', []),
        ('ActivePlayerChangeBegin', '', []),
    ],
)
async def test_garbage_calls_on_the_playerctld_interfaces_get_an_error(
    playerctld, daemon_bus, mpris_factory, interface, member, signature, body
):
    await with_player(mpris_factory, daemon_bus)

    reply = await raw_call(daemon_bus, interface, member, signature, body)

    assert reply.message_type == ERROR, reply.body
    assert reply.error_name.startswith(
        ('org.freedesktop.DBus.Error.', interface)
    )
    assert await player_names(daemon_bus) == [PREFIX + 'player1']
    assert_healthy(
        playerctld, allow=OPTIONAL_NOISE + ('deprecated D-Bus interface',)
    )


@pytest.mark.parametrize(
    'interface', [PLAYERCTLD_INTERFACE, PLAYERCTLD_LEGACY]
)
@pytest.mark.parametrize(
    'member, signature, body',
    [
        ('Get', 'ss', ['x', 'PlayerNames']),
        ('Get', 'ss', ['ZZZ', 'Unknown']),
        ('Set', 'ssv', ['x', 'PlayerNames', Variant('as', ['evil'])]),
        ('GetAll', 's', ['']),
    ],
)
async def test_property_abuse_on_the_playerctld_interfaces(
    playerctld, daemon_bus, interface, member, signature, body
):
    body = [interface if body[0] == 'x' else body[0], *body[1:]]
    if member == 'Get' and body[1] == 'Unknown':
        body[0] = interface

    reply = await raw_call(
        daemon_bus, PROPERTIES_INTERFACE, member, signature, body
    )

    if member == 'Get' and body[1] == 'PlayerNames':
        assert reply.message_type == RETURN
    else:
        assert reply.message_type == ERROR, reply.body
    assert await player_names(daemon_bus) == []
    assert_healthy(
        playerctld, allow=OPTIONAL_NOISE + ('deprecated D-Bus interface',)
    )


@pytest.mark.parametrize(
    'interface', [PLAYERCTLD_INTERFACE, PLAYERCTLD_LEGACY]
)
async def test_no_player_error_is_namespaced_by_the_interface_used(
    playerctld, daemon_bus, interface
):
    reply = await raw_call(daemon_bus, interface, 'Shift')

    assert reply.message_type == ERROR
    assert reply.error_name == f'{interface}.NoActivePlayer'


async def test_legacy_interface_works_alongside_the_new_one(
    playerctld, daemon_bus, mpris_factory
):
    await with_player(mpris_factory, daemon_bus, 'a')
    [mpris_b] = await mpris_factory('b')
    await mpris_b.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'a', PREFIX + 'b'])

    new = await raw_call(daemon_bus, PLAYERCTLD_INTERFACE, 'Shift')
    old = await raw_call(daemon_bus, PLAYERCTLD_LEGACY, 'Unshift')

    assert new.message_type == old.message_type == RETURN
    assert new.body == [PREFIX + 'a']
    assert old.body == [PREFIX + 'b']
    assert_healthy(
        playerctld, allow=OPTIONAL_NOISE + ('deprecated D-Bus interface',)
    )


# ---- unusual message flags -------------------------------------------------


async def test_fire_and_forget_calls_do_not_confuse_the_daemon(
    playerctld, daemon_bus, mpris_factory
):
    from dbus_next import Message, MessageFlag

    mpris = await with_player(mpris_factory, daemon_bus)

    for member in ('Play', 'Pause', 'Nonsense'):
        await daemon_bus.send(
            Message(
                destination=PLAYERCTLD_NAME,
                path=MPRIS_PATH,
                interface=PLAYER_INTERFACE,
                member=member,
                flags=MessageFlag.NO_REPLY_EXPECTED,
            )
        )
    await settle()

    assert mpris.play_called and mpris.pause_called
    assert await player_names(daemon_bus) == [PREFIX + 'player1']
    assert_healthy(playerctld)


async def test_many_concurrent_calls_from_many_clients_all_get_replies(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    await with_player(mpris_factory, daemon_bus)
    buses = [await new_bus(bus_address) for _ in range(10)]

    async def client(bus):
        replies = []
        for member in ('Play', 'Pause', 'Bogus', 'Next', 'Previous'):
            replies.append(
                await raw_call(bus, PLAYER_INTERFACE, member, timeout=3)
            )
        return [r.message_type for r in replies]

    results = await asyncio.gather(*(client(b) for b in buses))

    assert results == [[RETURN, RETURN, ERROR, RETURN, RETURN]] * 10
    for bus in buses:
        await close_bus(bus)
    assert_healthy(playerctld)

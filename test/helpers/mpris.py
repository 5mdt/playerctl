from dbus_next.service import (
    ServiceInterface,
    dbus_property,
    method,
    signal,
    Variant,
)
from dbus_next import (
    DBusError,
    Message,
    MessageType,
    NameFlag,
    PropertyAccess,
    RequestNameReply,
    BusType,
)
from dbus_next.aio import MessageBus

import asyncio

PROPERTIES_INTERFACE = 'org.freedesktop.DBus.Properties'
PLAYER_INTERFACE = 'org.mpris.MediaPlayer2.Player'
ROOT_INTERFACE = 'org.mpris.MediaPlayer2'
TRACKLIST_INTERFACE = 'org.mpris.MediaPlayer2.TrackList'
PLAYLISTS_INTERFACE = 'org.mpris.MediaPlayer2.Playlists'
PLAYERCTLD_INTERFACE = 'org._5mdt.playerctld'
# deprecated, still served for compatibility until the next major version
PLAYERCTLD_INTERFACE_LEGACY = 'com.github.altdesktop.playerctld'


async def _bus_call(bus, member, signature='', body=()):
    reply = await bus.call(
        Message(
            destination='org.freedesktop.DBus',
            path='/org/freedesktop/DBus',
            interface='org.freedesktop.DBus',
            member=member,
            signature=signature,
            body=list(body),
        )
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    return reply.body[0]


async def name_owner_pid(bus_address, name):
    """Return the pid owning name on the bus, or None if it has no owner."""
    bus = await MessageBus(bus_address=bus_address).connect()
    try:
        if not await _bus_call(bus, 'NameHasOwner', 's', [name]):
            return None
        return await _bus_call(bus, 'GetConnectionUnixProcessID', 's', [name])
    finally:
        bus.disconnect()


async def wait_for_name(bus_address, name, present=True, timeout=3.0):
    """Wait until name has (or, with present=False, loses) an owner."""
    bus = await MessageBus(bus_address=bus_address).connect()
    try:
        deadline = asyncio.get_running_loop().time() + timeout
        while await _bus_call(bus, 'NameHasOwner', 's', [name]) != present:
            assert asyncio.get_running_loop().time() < deadline, (
                f'timed out waiting for {name} '
                f'to {"appear" if present else "disappear"}'
            )
            await asyncio.sleep(0.01)
    finally:
        bus.disconnect()


async def setup_mpris(
    *names,
    bus_address=None,
    system=False,
    tracklist=False,
    playlists=False,
    hidden=(),
    prepare=None,
    name_flags=NameFlag.NONE,
    queued=False,
):
    '''Export one mock player per name.

    hidden: Player property names (e.g. `Volume`) the mock does not expose at
    all, so a client never has them in its property cache.
    prepare: callable(player) run once the interfaces are exported but before
    the well-known name is requested, so it can install a `MessageGate` that
    already sees the very first calls a client makes (see `gated`).
    queued: the name is already owned, so the mock only waits in the queue for
    it (use it to stand behind the current owner).
    '''
    player_class = MprisPlayer.without(*hidden) if hidden else MprisPlayer

    # TODO maybe they should all share a bus for speed
    async def setup(name):
        if system:
            bus_type = BusType.SYSTEM
        else:
            bus_type = BusType.SESSION
        bus = await MessageBus(
            bus_type=bus_type, bus_address=bus_address
        ).connect()
        player = player_class(bus)
        bus.export('/org/mpris/MediaPlayer2', player)
        player.root = MprisRoot()
        bus.export('/org/mpris/MediaPlayer2', player.root)
        if tracklist:
            player.tracklist = MprisTrackList()
            bus.export('/org/mpris/MediaPlayer2', player.tracklist)
        if playlists:
            player.playlists = MprisPlaylists()
            bus.export('/org/mpris/MediaPlayer2', player.playlists)
        if prepare is not None:
            prepare(player)
        reply = await bus.request_name(
            f'org.mpris.MediaPlayer2.{name}', name_flags
        )
        assert reply == (
            RequestNameReply.IN_QUEUE
            if queued
            else RequestNameReply.PRIMARY_OWNER
        )
        return player

    players = await asyncio.gather(*(setup(name) for name in names))
    await asyncio.gather(*(p.ping() for p in players))
    return players


class MessageGate:
    """Misbehaving-player facility: intercepts method calls made to a mock
    player's bus connection before dbus_next dispatches them.

    A call matching a `hold` rule is parked (the caller gets no reply) until
    `release()` answers it through the normal handlers; a call matching a
    `fail` rule is answered at once with a D-Bus error. Rules match on the
    member name, optionally the interface, and optionally the first argument
    (for `Properties.GetAll`, the interface being asked about).
    """

    def __init__(self, bus):
        self.bus = bus
        self.rules = []
        self.held = []
        self.bus.add_message_handler(self._handle)

    def hold(self, member, interface=None, arg=None):
        self.rules.append(('hold', member, interface, arg, None, None))

    def rewrite(self, member, interface=None, arg=None, fn=None):
        """Let the normal handler answer a matching call, but pass its reply
        through `fn(reply) -> reply` first."""
        self.rules.append(('rewrite', member, interface, arg, fn, None))

    def strip_get_all(self, interface, *properties):
        """Answer Properties.GetAll for `interface` without these properties
        (a player that does not put them in the property cache)."""

        def strip(reply):
            reply.body[0] = {
                k: v for k, v in reply.body[0].items() if k not in properties
            }
            return reply

        self.rewrite('GetAll', PROPERTIES_INTERFACE, interface, strip)

    def fail(
        self,
        member,
        interface=None,
        arg=None,
        error='org.example.Error',
        text='boom',
    ):
        self.rules.append(('fail', member, interface, arg, error, text))

    def hold_get_all(self, *interfaces):
        """Withhold the reply to Properties.GetAll for these interfaces."""
        for interface in interfaces:
            self.hold('GetAll', PROPERTIES_INTERFACE, interface)

    def fail_get_all(self, *interfaces):
        """Answer Properties.GetAll for these interfaces with an error."""
        for interface in interfaces:
            self.fail('GetAll', PROPERTIES_INTERFACE, interface)

    def _handle(self, msg):
        if msg.message_type != MessageType.METHOD_CALL:
            return None
        for action, member, interface, arg, error, text in self.rules:
            if msg.member != member:
                continue
            if interface is not None and msg.interface != interface:
                continue
            if arg is not None and (not msg.body or msg.body[0] != arg):
                continue
            if action == 'hold':
                self.held.append(msg)
                return True
            if action == 'rewrite':
                self._answer(msg, error)
                return True
            return Message.new_error(msg, error, text)
        return None

    def _answer(self, msg, transform):
        handler = self.bus._find_message_handler(msg)
        send_reply = self.bus._send_reply(msg)

        def send(reply):
            send_reply(transform(reply))

        with send_reply:
            handler(msg, send)

    async def wait_held(self, count=1, timeout=2.0):
        """Wait until `count` calls are parked."""
        deadline = asyncio.get_running_loop().time() + timeout
        while len(self.held) < count:
            assert asyncio.get_running_loop().time() < deadline, (
                f'only {len(self.held)} of {count} calls arrived'
            )
            await asyncio.sleep(0.01)

    def release(self):
        """Stop holding and answer every parked call normally."""
        self.rules = [r for r in self.rules if r[0] != 'hold']
        held, self.held = self.held, []
        for msg in held:
            handler = self.bus._find_message_handler(msg)
            send_reply = self.bus._send_reply(msg)
            with send_reply:
                handler(msg, send_reply)


def gated(configure):
    """`setup_mpris(prepare=...)` hook: give the player a `MessageGate`
    (as `player.gate`) and let `configure(gate)` add its rules."""

    def prepare(player):
        player.gate = MessageGate(player.bus)
        configure(player.gate)

    return prepare


async def setup_partial_player(name, bus_address, root=False, player=False):
    '''Own org.mpris.MediaPlayer2.<name> but export only some mandatory
    interfaces (none by default). Returns the bus; disconnect it when done.'''
    bus = await MessageBus(bus_address=bus_address).connect()
    if player:
        bus.export('/org/mpris/MediaPlayer2', MprisPlayer(bus))
    if root:
        bus.export('/org/mpris/MediaPlayer2', MprisRoot())
    reply = await bus.request_name(f'org.mpris.MediaPlayer2.{name}')
    assert reply == RequestNameReply.PRIMARY_OWNER
    return bus


async def setup_playerctld(bus_address=None, interface=PLAYERCTLD_INTERFACE):
    bus = await MessageBus(bus_address=bus_address).connect()
    playerctld = PlayerctldInterface(bus, interface)
    bus.export('/org/mpris/MediaPlayer2', playerctld)
    reply = await bus.request_name('org.mpris.MediaPlayer2.playerctld')
    assert reply == RequestNameReply.PRIMARY_OWNER
    return playerctld


# Player properties that `MprisPlayer.without` can hide: name -> signature
HIDEABLE_PROPERTIES = {
    'PlaybackStatus': 's',
    'LoopStatus': 's',
    'Shuffle': 'b',
    'Volume': 'd',
    'Position': 'x',
}


def _disabled_getter(signature):
    def getter(self):
        raise NotImplementedError

    getter.__annotations__ = {'return': signature}
    return getter


class MprisRoot(ServiceInterface):
    def __init__(self):
        super().__init__('org.mpris.MediaPlayer2')
        self.raise_called = False
        self.quit_called = False

    @method()
    def Raise(self):
        self.raise_called = True

    @method()
    def Quit(self):
        self.quit_called = True

    @dbus_property(access=PropertyAccess.READ)
    def CanRaise(self) -> 'b':
        return False

    @dbus_property(access=PropertyAccess.READ)
    def HasTrackList(self) -> 'b':
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Identity(self) -> 's':
        return 'playerctl test client'

    @dbus_property(access=PropertyAccess.READ)
    def SupportedUriSchemes(self) -> 'as':
        return ['file']

    @dbus_property(access=PropertyAccess.READ)
    def SupportedMimeTypes(self) -> 'as':
        return ['audio/mp3']


class MprisTrackList(ServiceInterface):
    '''Minimal org.mpris.MediaPlayer2.TrackList.'''

    def __init__(self):
        super().__init__('org.mpris.MediaPlayer2.TrackList')
        self.tracks = ['/track/1', '/track/2']
        self.go_to_called_with = None

    @method()
    def GoTo(self, track_id: 'o'):
        self.go_to_called_with = track_id

    @dbus_property(access=PropertyAccess.READ)
    def Tracks(self) -> 'ao':
        return self.tracks

    @dbus_property(access=PropertyAccess.READ)
    def CanEditTracks(self) -> 'b':
        return False

    @signal()
    def TrackAdded(self) -> 'a{sv}o':
        return [{}, '/track/1']


class MprisPlaylists(ServiceInterface):
    '''Minimal org.mpris.MediaPlayer2.Playlists.'''

    def __init__(self):
        super().__init__('org.mpris.MediaPlayer2.Playlists')
        self.playlist_count = 3
        self.activate_playlist_called_with = None

    @method()
    def ActivatePlaylist(self, playlist_id: 'o'):
        self.activate_playlist_called_with = playlist_id

    @dbus_property(access=PropertyAccess.READ)
    def PlaylistCount(self) -> 'u':
        return self.playlist_count

    @dbus_property(access=PropertyAccess.READ)
    def Orderings(self) -> 'as':
        return ['Alphabetical']

    @dbus_property(access=PropertyAccess.READ)
    def ActivePlaylist(self) -> '(b(oss))':
        return [False, ['/', '', '']]

    @signal()
    def PlaylistChanged(self) -> '(oss)':
        return [['/playlist/1', 'one', '']]


class MprisPlayer(ServiceInterface):
    def __init__(self, bus):
        super().__init__('org.mpris.MediaPlayer2.Player')
        self.counter = 0
        self.reset()
        self.bus = bus
        self.disconnected = False

    @classmethod
    def without(cls, *names):
        '''Subclass that does not expose the given Player properties.'''
        unknown = set(names) - set(HIDEABLE_PROPERTIES)
        assert not unknown, f'cannot hide {unknown}'
        members = {}
        for name in names:
            getter = _disabled_getter(HIDEABLE_PROPERTIES[name])
            members[name] = dbus_property(
                access=PropertyAccess.READ, name=name, disabled=True
            )(getter)
        return type(f'{cls.__name__}Without', (cls,), members)

    def fail(self):
        '''Raise the configured D-Bus error, if any (used by the handlers).'''
        if self.error is not None:
            raise DBusError('org.example.Error', self.error)

    def reset(self):
        # when set, every method call and property write fails with this text
        self.error = None

        # method calls
        self.next_called = False
        self.previous_called = False
        self.pause_called = False
        self.play_pause_called = False
        self.stop_called = False
        self.play_called = False
        self.seek_called_with = None
        self.set_position_called_with = None
        self.open_uri_called_with = None

        # properties
        self.playback_status = 'Playing'
        self.loop_status = 'None'
        self.rate = 1.0
        self.shuffle = False
        self.metadata = {}
        self.volume = 1.0
        self.position = 0
        self.minimum_rate = 1.0
        self.maximum_rate = 1.0
        self.can_go_next = True
        self.can_go_previous = True
        self.can_play = True
        self.can_pause = True
        self.can_seek = True
        self.can_control = True

        # signals
        self.seeked_value = 0

    async def ping(self):
        await self.bus.introspect(
            'org.freedesktop.DBus', '/org/freedesktop/DBus'
        )

    async def set_artist_title(self, artist, title, track_id=None):
        if track_id is None:
            self.counter += 1
            track_id = '/' + str(self.counter)

        self.metadata = {
            'xesam:title': Variant('s', title),
            'xesam:artist': Variant('as', [artist]),
            'mpris:trackid': Variant('o', track_id),
        }

        self.emit_properties_changed(
            {
                'Metadata': self.metadata,
            }
        )
        await self.ping()

    async def emit_properties(self, **props):
        '''Set player attributes (snake_case) and emit PropertiesChanged.'''
        changed = {}
        for attr, value in props.items():
            setattr(self, attr, value)
            name = ''.join(part.title() for part in attr.split('_'))
            changed[name] = value
        self.emit_properties_changed(changed)
        await self.ping()

    async def send_properties_changed(
        self, changed, invalidated=(), interface=PLAYER_INTERFACE
    ):
        '''Emit PropertiesChanged with exactly this body: `changed` maps
        property names to `Variant`s of any type (even a wrong one) and
        `invalidated` lists names the client must re-read.'''
        await self.bus.send(
            Message.new_signal(
                '/org/mpris/MediaPlayer2',
                PROPERTIES_INTERFACE,
                'PropertiesChanged',
                'sa{sv}as',
                [interface, dict(changed), list(invalidated)],
            )
        )
        await self.ping()

    async def clear_metadata(self):
        self.counter += 1
        self.metadata = {
            'mpris:trackid': Variant('o', '/' + str(self.counter)),
        }
        self.emit_properties_changed(
            {
                'Metadata': self.metadata,
            }
        )
        await self.ping()

    async def disconnect(self):
        if self.disconnected:
            return
        self.disconnected = True
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()

    @method()
    def Next(self):
        self.fail()
        self.next_called = True

    @method()
    def Previous(self):
        self.fail()
        self.previous_called = True

    @method()
    def Pause(self):
        self.fail()
        self.pause_called = True

    @method()
    def PlayPause(self):
        self.fail()
        self.play_pause_called = True

    @method()
    def Stop(self):
        self.fail()
        self.stop_called = True

    @method()
    def Play(self):
        self.fail()
        self.play_called = True

    @method()
    def Seek(self, offset: 'x'):
        self.fail()
        self.seek_called_with = offset

    @method()
    def SetPosition(self, track_id: 'o', position: 'x'):
        self.fail()
        self.set_position_called_with = (track_id, position)

    @method()
    def OpenUri(self, uri: 's'):
        self.fail()
        self.open_uri_called_with = uri

    @signal()
    def Seeked(self) -> 'x':
        return self.seeked_value

    @dbus_property(access=PropertyAccess.READ)
    def PlaybackStatus(self) -> 's':
        return self.playback_status

    @dbus_property()
    def LoopStatus(self) -> 's':
        return self.loop_status

    @LoopStatus.setter
    def LoopStatus(self, status: 's'):
        self.fail()
        self.loop_status = status

    @dbus_property()
    def Rate(self) -> 'd':
        return self.rate

    @Rate.setter
    def Rate(self, rate: 'd'):
        self.fail()
        self.rate = rate

    @dbus_property()
    def Shuffle(self) -> 'b':
        return self.shuffle

    @Shuffle.setter
    def Shuffle(self, shuffle: 'b'):
        self.fail()
        self.shuffle = shuffle

    @dbus_property(access=PropertyAccess.READ)
    def Metadata(self) -> 'a{sv}':
        return self.metadata

    @dbus_property()
    def Volume(self) -> 'd':
        return self.volume

    @Volume.setter
    def Volume(self, volume: 'd'):
        self.fail()
        self.volume = volume

    @dbus_property(access=PropertyAccess.READ)
    def Position(self) -> 'x':
        return self.position

    @dbus_property(access=PropertyAccess.READ)
    def MinimumRate(self) -> 'd':
        return self.minimum_rate

    @dbus_property(access=PropertyAccess.READ)
    def MaximumRate(self) -> 'd':
        return self.maximum_rate

    @dbus_property(access=PropertyAccess.READ)
    def CanGoNext(self) -> 'b':
        return self.can_go_next

    @dbus_property(access=PropertyAccess.READ)
    def CanGoPrevious(self) -> 'b':
        return self.can_go_previous

    @dbus_property(access=PropertyAccess.READ)
    def CanPlay(self) -> 'b':
        return self.can_play

    @dbus_property(access=PropertyAccess.READ)
    def CanPause(self) -> 'b':
        return self.can_pause

    @dbus_property(access=PropertyAccess.READ)
    def CanSeek(self) -> 'b':
        return self.can_seek

    @dbus_property(access=PropertyAccess.READ)
    def CanControl(self) -> 'b':
        return self.can_control


class PlayerctldInterface(ServiceInterface):
    '''just enough of playerctld for testing'''

    def __init__(self, bus, interface=PLAYERCTLD_INTERFACE):
        super().__init__(interface)
        self.bus = bus
        self.player_names = []
        self.shift_called = False
        self.unshift_called = False

    @method()
    def Shift(self) -> 's':
        self.shift_called = True
        return 'org.mpris.MediaPlayer2.player1'

    @method()
    def Unshift(self) -> 's':
        self.unshift_called = True
        return 'org.mpris.MediaPlayer2.player1'

    @dbus_property(access=PropertyAccess.READ)
    def PlayerNames(self) -> 'as':
        return self.player_names

    async def disconnect(self):
        self.bus.disconnect()
        await self.bus.wait_for_disconnect()


def was_called(mpris, command):
    '''Whether the mock saw the CLI command, e.g. `play-pause`.'''
    return getattr(mpris, f'{command.replace("-", "_")}_called')

"""US-11.14: As a maintainer, I want the mock players the tests use to follow
the MPRIS specification, so that no test passes against behaviour a real
player cannot have, and none misses a member every real player has."""

import pytest
from xml.etree import ElementTree
from dbus_next import Message
from dbus_next.aio import MessageBus

from ..helpers.daemon import MPRIS_PATH
from ..helpers.introspection import (
    MPRIS_XML,
    OPTIONAL,
    PLAYERCTLD_XML,
    describe,
    spec_interface,
)
from ..helpers.mpris import PLAYERCTLD_INTERFACE, setup_playerctld

MOCK_NAME = 'org.mpris.MediaPlayer2.spec'
PLAYERCTLD_NAME = 'org.mpris.MediaPlayer2.playerctld'

MPRIS_INTERFACES = [
    'org.mpris.MediaPlayer2',
    'org.mpris.MediaPlayer2.Player',
    'org.mpris.MediaPlayer2.TrackList',
    'org.mpris.MediaPlayer2.Playlists',
]


async def introspect(bus_address, name):
    '''The interfaces a service announces on the MPRIS object, by name.'''
    bus = await MessageBus(bus_address=bus_address).connect()
    try:
        reply = await bus.call(
            Message(
                destination=name,
                path=MPRIS_PATH,
                interface='org.freedesktop.DBus.Introspectable',
                member='Introspect',
            )
        )
    finally:
        bus.disconnect()
    node = ElementTree.fromstring(reply.body[0])
    return {i.get('name'): i for i in node.findall('interface')}


def structure(interface):
    '''What a mock has to share with the specification: the shape of every
    member. Argument names are not compared (dbus_next takes them from the
    Python parameters) and neither are annotations (it cannot emit them).'''
    desc = describe(interface, arg_names=False)
    return {
        'methods': {n: args for n, (args, _) in desc['methods'].items()},
        'signals': {n: args for n, (args, _) in desc['signals'].items()},
        'properties': {
            n: (kind, access)
            for n, (kind, access, _) in desc['properties'].items()
        },
    }


def required_members(spec):
    '''Members of an interface element a real player must have.'''
    return {
        kind: {
            e.get('name')
            for e in spec.findall(kind)
            if not any(
                a.get('name') == OPTIONAL for a in e.findall('annotation')
            )
        }
        for kind in ('method', 'signal', 'property')
    }


def check_follows(mock, spec):
    mock_shape = structure(mock)
    spec_shape = structure(spec)
    required = required_members(spec)

    for kind, key in (
        ('method', 'methods'),
        ('signal', 'signals'),
        ('property', 'properties'),
    ):
        for name, shape in mock_shape[key].items():
            assert name in spec_shape[key], (
                f'mock {kind} {name} is not in the spec'
            )
            assert shape == spec_shape[key][name], f'{kind} {name} differs'
        missing = required[kind] - set(mock_shape[key])
        assert not missing, f'mock lacks required {key}: {sorted(missing)}'


@pytest.fixture()
async def mock_player(bus_address, mpris_factory):
    await mpris_factory('spec', tracklist=True, playlists=True)
    return await introspect(bus_address, MOCK_NAME)


@pytest.fixture()
async def mock_playerctld(bus_address):
    playerctld = await setup_playerctld(bus_address)
    yield await introspect(bus_address, PLAYERCTLD_NAME)
    await playerctld.disconnect()


@pytest.mark.parametrize('name', MPRIS_INTERFACES)
async def test_mock_mpris_interface_follows_the_specification(
    name, mock_player
):
    assert name in mock_player, f'the mock player lacks {name}'

    check_follows(mock_player[name], spec_interface(MPRIS_XML, name))


async def test_mock_playerctld_follows_its_interface_file(mock_playerctld):
    check_follows(
        mock_playerctld[PLAYERCTLD_INTERFACE],
        spec_interface(PLAYERCTLD_XML, PLAYERCTLD_INTERFACE),
    )

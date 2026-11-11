'''Compare D-Bus introspection data with the interface XML files in data/.'''

from pathlib import Path
from xml.etree import ElementTree

from dbus_next import MessageType

from .daemon import playerctld_call

DATA = Path(__file__).resolve().parents[2] / 'data'
MPRIS_XML = DATA / 'mpris-dbus-interface.xml'
PLAYERCTLD_XML = DATA / 'org._5mdt.playerctld.xml'

OPTIONAL = 'org.mpris.MediaPlayer2.property.optional'


def annotations(element):
    return {
        a.get('name'): a.get('value') for a in element.findall('annotation')
    }


def arguments(element, default_direction, names=True):
    return [
        (
            a.get('name') if names else None,
            a.get('type'),
            a.get('direction', default_direction),
        )
        for a in element.findall('arg')
    ]


def describe(interface, arg_names=True):
    '''Everything a client can learn from the introspection of an interface.

    arg_names=False leaves argument names out, for services that take them
    from their code (dbus_next names them after Python parameters).'''
    return {
        'annotations': annotations(interface),
        'methods': {
            m.get('name'): (arguments(m, 'in', arg_names), annotations(m))
            for m in interface.findall('method')
        },
        'signals': {
            s.get('name'): (arguments(s, 'out', arg_names), annotations(s))
            for s in interface.findall('signal')
        },
        'properties': {
            p.get('name'): (p.get('type'), p.get('access'), annotations(p))
            for p in interface.findall('property')
        },
    }


def spec_interface(path, name, without=()):
    '''Interface `name` of the XML file `path`, minus (interface, member) pairs
    in `without`.'''
    node = ElementTree.parse(path).getroot()
    interface = node.find(f"interface[@name='{name}']")
    for iface, member in without:
        if iface == name:
            for kind in ('method', 'signal', 'property'):
                for element in interface.findall(f"{kind}[@name='{member}']"):
                    interface.remove(element)
    return interface


async def introspect(bus):
    '''The introspection of the running playerctld as an XML element.'''
    reply = await playerctld_call(
        bus, 'org.freedesktop.DBus.Introspectable', 'Introspect'
    )
    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    return ElementTree.fromstring(reply.body[0])

"""US-10.21: As an integrator, I want playerctld's D-Bus interface shipped as
an XML file, and playerctld to announce exactly that interface, under the
legacy name too, marked as deprecated there."""

from ..helpers.mpris import PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY
from ..helpers.introspection import (
    PLAYERCTLD_XML,
    describe,
    introspect,
    spec_interface,
)

DEPRECATED = 'org.freedesktop.DBus.Deprecated'


def test_the_interface_file_describes_the_documented_members():
    spec = describe(spec_interface(PLAYERCTLD_XML, PLAYERCTLD_INTERFACE))

    assert sorted(spec['methods']) == ['Shift', 'Unshift']
    assert sorted(spec['signals']) == [
        'ActivePlayerChangeBegin',
        'ActivePlayerChangeEnd',
    ]
    assert spec['properties'] == {'PlayerNames': ('as', 'read', {})}


async def test_the_interface_is_announced_as_the_file_defines_it(
    playerctld, daemon_bus
):
    node = await introspect(daemon_bus)

    announced = node.find(f"interface[@name='{PLAYERCTLD_INTERFACE}']")
    spec = spec_interface(PLAYERCTLD_XML, PLAYERCTLD_INTERFACE)
    assert describe(announced) == describe(spec)


async def test_the_legacy_interface_is_the_same_one_marked_deprecated(
    playerctld, daemon_bus
):
    node = await introspect(daemon_bus)

    announced = node.find(f"interface[@name='{PLAYERCTLD_INTERFACE_LEGACY}']")
    expected = describe(spec_interface(PLAYERCTLD_XML, PLAYERCTLD_INTERFACE))
    expected['annotations'] = {DEPRECATED: 'true'}
    assert describe(announced) == expected

"""US-10.19: As an integrator, I want playerctld to announce the MPRIS
interfaces exactly as the specification defines them, so that clients
introspecting it see the same methods, signals, properties and annotations as
on a real player."""

from ..helpers.introspection import (
    MPRIS_XML,
    describe,
    introspect,
    spec_interface,
)

MPRIS_INTERFACES = [
    'org.mpris.MediaPlayer2',
    'org.mpris.MediaPlayer2.Player',
    'org.mpris.MediaPlayer2.TrackList',
    'org.mpris.MediaPlayer2.Playlists',
]
# playerctld does not forward methods that pass file descriptors
NOT_FORWARDED = {('org.mpris.MediaPlayer2.Player', 'GetArtworkFd')}


async def test_mpris_interfaces_match_the_specification(
    playerctld, daemon_bus
):
    node = await introspect(daemon_bus)

    for name in MPRIS_INTERFACES:
        announced = node.find(f"interface[@name='{name}']")
        assert announced is not None, f'{name} is not announced'
        spec = spec_interface(MPRIS_XML, name, without=NOT_FORWARDED)
        assert describe(announced) == describe(spec), name


async def test_methods_that_pass_file_descriptors_are_not_announced(
    playerctld, daemon_bus
):
    node = await introspect(daemon_bus)

    for iface, member in NOT_FORWARDED:
        announced = node.find(f"interface[@name='{iface}']")
        assert announced.find(f"method[@name='{member}']") is None

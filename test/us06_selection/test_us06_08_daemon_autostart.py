"""US-6.8: As a user, I want `-p playerctld` to start the daemon through D-Bus
activation if it isn't running.

The test bus is a plain `dbus-daemon --session`, which picks up the installed
`org.mpris.MediaPlayer2.playerctld.service` activation file (Exec=playerctld).
"""

from ..helpers.daemon import PLAYERCTLD_NAME
from ..helpers.mpris import name_owner_pid, wait_for_name


async def test_playerctld_is_started_on_demand(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None

    result = await playerctl.run('-p playerctld status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is not None


async def test_started_daemon_proxies_players(
    bus_address, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('player1')

    result = await playerctl.run('-p playerctld play')

    assert result.returncode == 0, result.stderr
    assert mpris.play_called
    await wait_for_name(bus_address, PLAYERCTLD_NAME)


async def test_daemon_not_started_without_selecting_it(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')

    result = await playerctl.run('status')

    assert result.returncode == 0, result.stderr
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


async def test_daemon_not_started_when_ignored(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')

    result = await playerctl.run('-p playerctld -i playerctld status')

    assert result.returncode == 1
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


async def test_daemon_not_started_for_playerctld_instance_name(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')

    result = await playerctl.run('-p playerctld.x status')

    assert result.returncode == 1
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


async def test_daemon_not_started_for_any_placeholder(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')

    result = await playerctl.run('-p %any status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


async def test_daemon_not_started_for_list_all(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')

    result = await playerctl.run('-p playerctld --list-all')

    assert result.returncode == 0, result.stderr
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None

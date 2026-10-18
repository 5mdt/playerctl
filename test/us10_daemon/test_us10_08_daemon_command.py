"""US-10.8: As a user, I want `playerctld daemon` to start the service through
D-Bus activation.

The test bus is a plain `dbus-daemon --session`, which picks up the installed
`org.mpris.MediaPlayer2.playerctld.service` activation file (Exec=playerctld).
"""

import asyncio
import os

from ..helpers.daemon import PLAYERCTLD_NAME
from ..helpers.mpris import name_owner_pid, wait_for_name


async def run_daemon_command(bus_address):
    env = os.environ.copy()
    env['DBUS_SESSION_BUS_ADDRESS'] = bus_address
    proc = await asyncio.create_subprocess_shell(
        'playerctld daemon',
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    return proc.returncode, stdout.decode(), stderr.decode()


async def test_daemon_command_starts_service(bus_address):
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None

    code, _, stderr = await run_daemon_command(bus_address)

    assert code == 0, stderr
    await wait_for_name(bus_address, PLAYERCTLD_NAME)
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)
    assert pid is not None
    assert pid != os.getpid()
    os.kill(pid, 15)


async def test_daemon_command_exits_while_service_keeps_running(bus_address):
    code, _, stderr = await run_daemon_command(bus_address)
    assert code == 0, stderr
    await wait_for_name(bus_address, PLAYERCTLD_NAME)
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)

    # the service is the activated process, not the finished command
    assert os.path.exists(f'/proc/{pid}')
    os.kill(pid, 15)


async def test_daemon_command_when_already_running(bus_address, playerctld):
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)

    code, _, stderr = await run_daemon_command(bus_address)

    assert code == 0, stderr
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == pid


async def test_activated_daemon_serves_requests(
    bus_address, playerctl, mpris_factory
):
    await mpris_factory('player1')
    code, _, stderr = await run_daemon_command(bus_address)
    assert code == 0, stderr
    await wait_for_name(bus_address, PLAYERCTLD_NAME)
    await asyncio.sleep(0.2)

    result = await playerctl.run('-p playerctld status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'
    os.kill(await name_owner_pid(bus_address, PLAYERCTLD_NAME), 15)


async def test_daemon_command_without_activation_support(tmp_path):
    # a bus that has no service directory cannot activate playerctld
    config = tmp_path / 'bus.conf'
    config.write_text(
        '<busconfig><type>session</type>'
        '<listen>unix:tmpdir=/tmp</listen><auth>EXTERNAL</auth>'
        '<policy context="default"><allow send_destination="*"/>'
        '<allow receive_type="method_call"/><allow receive_type="method_return"/>'
        '<allow receive_type="error"/><allow receive_type="signal"/>'
        '<allow own="*"/></policy></busconfig>'
    )
    bus = await asyncio.create_subprocess_exec(
        'dbus-daemon',
        f'--config-file={config}',
        '--nofork',
        '--print-address=1',
        stdout=asyncio.subprocess.PIPE,
    )
    try:
        address = (await bus.stdout.readline()).decode().strip()

        code, _, stderr = await run_daemon_command(address)

        assert code == 1
        assert 'org.freedesktop.DBus.Error.ServiceUnknown' in stderr, stderr
        assert 'not supported' in stderr
    finally:
        bus.terminate()
        await bus.wait()

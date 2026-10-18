"""US-10.12: As a user, I want playerctld to refuse unknown commands and a
second instance with a clear message and exit code 1."""

from ..helpers.daemon import playerctld_cli


async def test_unknown_command_prints_help(bus_address):
    code, stdout, _ = await playerctld_cli(bus_address, 'bogus')

    assert code == 1
    assert 'Usage:' in stdout
    for command in ('daemon', 'shift', 'unshift'):
        assert command in stdout


async def test_second_instance_refuses_to_start(bus_address, playerctld):
    code, _, stderr = await playerctld_cli(bus_address, '')

    assert code == 1
    assert 'playerctld is already running' in stderr, stderr
    assert playerctld.returncode is None, (
        'the first instance must keep running'
    )

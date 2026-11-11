"""US-10.23: As a user, I want nobody (a second daemon, a rogue client, a
player with a look-alike name) to take over or confuse playerctld's bus
name and its list of players."""

import asyncio
import os

import pytest
from dbus_next import MessageType, NameFlag, RequestNameReply

from ..helpers.daemon import (
    PLAYERCTLD_NAME,
    player_names,
    playerctld_cli,
    start_playerctld,
    wait_for_player_names,
    wait_for_players,
)
from ..helpers.daemon_attack import (
    PREFIX,
    RawPlayer,
    assert_healthy,
    close_bus,
    dbus_call,
    new_bus,
    wait_exit,
)
from ..helpers.mpris import name_owner_pid, wait_for_name
from ..helpers.playerctl import register


async def spawn_playerctld(bus_address):
    '''A playerctld that is not stopped when the name is taken (the shared
    start_playerctld helper would kill whoever owns the name).'''
    env = {**os.environ, 'DBUS_SESSION_BUS_ADDRESS': bus_address}
    env['G_MESSAGES_DEBUG'] = 'playerctl'
    proc = await asyncio.create_subprocess_shell(
        'exec playerctld',
        env=env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    proc.log = []

    async def reader():
        while True:
            line = await proc.stdout.readline()
            if not line:
                break
            proc.log.append(line.decode().strip())

    register(proc, asyncio.get_event_loop().create_task(reader()))
    return proc


@pytest.mark.parametrize(
    'flags',
    [
        NameFlag.NONE,
        NameFlag.ALLOW_REPLACEMENT,
        NameFlag.ALLOW_REPLACEMENT | NameFlag.DO_NOT_QUEUE,
    ],
)
async def test_daemon_refuses_to_start_when_the_name_is_taken(
    bus_address, flags
):
    squatter = await new_bus(bus_address)
    assert await squatter.request_name(PLAYERCTLD_NAME, flags) == (
        RequestNameReply.PRIMARY_OWNER
    )

    proc = await spawn_playerctld(bus_address)

    assert await wait_exit(proc) == 1
    assert any('already running' in line for line in proc.log), proc.log
    # the squatter keeps the name, whatever replacement it allowed
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == os.getpid()
    await close_bus(squatter)


@pytest.mark.parametrize(
    'flags',
    [
        NameFlag.REPLACE_EXISTING,
        NameFlag.REPLACE_EXISTING | NameFlag.DO_NOT_QUEUE,
        NameFlag.REPLACE_EXISTING | NameFlag.ALLOW_REPLACEMENT,
    ],
)
async def test_running_daemon_cannot_be_replaced(
    bus_address, playerctld, daemon_bus, mpris_factory, flags
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'player1'])
    thief = await new_bus(bus_address)

    reply = await thief.request_name(PLAYERCTLD_NAME, flags)

    assert reply in (RequestNameReply.EXISTS, RequestNameReply.IN_QUEUE)
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == (
        playerctld.pid
    )
    assert await player_names(daemon_bus) == [PREFIX + 'player1']
    assert_healthy(playerctld)
    await close_bus(thief)


async def test_queued_squatter_does_not_block_a_restart(
    bus_address, playerctld, daemon_bus
):
    squatter = await new_bus(bus_address)
    assert await squatter.request_name(PLAYERCTLD_NAME) == (
        RequestNameReply.IN_QUEUE
    )

    playerctld.terminate()
    await playerctld.wait()

    # the queued client inherits the name; a new daemon must give up cleanly
    await wait_for_name(bus_address, PLAYERCTLD_NAME)
    proc = await spawn_playerctld(bus_address)
    assert await wait_exit(proc) == 1
    assert any('already running' in line for line in proc.log), proc.log
    await close_bus(squatter)


async def test_second_instance_exits_with_1_and_leaves_the_first_alone(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'player1'])

    second = await spawn_playerctld(bus_address)

    assert await wait_exit(second) == 1
    assert any('already running' in line for line in second.log), second.log
    assert playerctld.returncode is None
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == (
        playerctld.pid
    )
    assert await player_names(daemon_bus) == [PREFIX + 'player1']
    assert_healthy(playerctld)


async def test_many_second_instances_in_parallel_all_lose(
    bus_address, playerctld, daemon_bus
):
    procs = await asyncio.gather(
        *(spawn_playerctld(bus_address) for _ in range(8))
    )

    codes = await asyncio.gather(*(wait_exit(p) for p in procs))

    assert codes == [1] * 8
    assert_healthy(playerctld)


async def test_racing_daemons_leave_exactly_one_owner(bus_address):
    procs = await asyncio.gather(
        *(spawn_playerctld(bus_address) for _ in range(6))
    )
    await wait_for_name(bus_address, PLAYERCTLD_NAME)

    # 5 of the 6 exit with 1; the winner keeps running
    deadline = asyncio.get_running_loop().time() + 3
    while sum(p.returncode is not None for p in procs) < 5:
        assert asyncio.get_running_loop().time() < deadline, 'losers linger'
        await asyncio.sleep(0.02)
    winners = [p for p in procs if p.returncode is None]
    assert len(winners) == 1
    assert [p.returncode for p in procs if p.returncode is not None] == [1] * 5
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == (
        winners[0].pid
    )


async def test_other_clients_owning_the_interface_name_changes_nothing(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    # org._5mdt.playerctld and the legacy name are interface names, but
    # nothing stops a client from owning them as bus names
    squatter = await new_bus(bus_address)
    for name in ('org._5mdt.playerctld', 'com.github.altdesktop.playerctld'):
        assert await squatter.request_name(name) == (
            RequestNameReply.PRIMARY_OWNER
        )
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist', 'title')

    assert await wait_for_players(daemon_bus, [PREFIX + 'player1'])
    code, _, _ = await playerctld_cli(bus_address, 'shift')
    assert code == 0
    assert_healthy(playerctld)
    await close_bus(squatter)


async def test_daemon_starts_when_look_alike_names_are_already_taken(
    bus_address,
):
    squatter = await new_bus(bus_address)
    await squatter.request_name('org._5mdt.playerctld')
    await squatter.request_name(PLAYERCTLD_NAME + '.instance1')

    proc = await start_playerctld(bus_address)

    assert proc.returncode is None
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == proc.pid
    await close_bus(squatter)


@pytest.mark.parametrize(
    'suffix', ['playerctld.instance1', 'playerctld.a.b.c']
)
async def test_players_named_like_the_daemon_are_not_managed(
    bus_address, playerctld, daemon_bus, mpris_factory, suffix
):
    # org.mpris.MediaPlayer2.playerctld.* are playerctld's own names
    other = await RawPlayer.create(bus_address, suffix)
    [mpris] = await mpris_factory('real')
    await mpris.set_artist_title('artist', 'title')

    assert await wait_for_players(daemon_bus, [PREFIX + 'real']) == [
        PREFIX + 'real'
    ]
    await other.disconnect()


@pytest.mark.xfail(
    strict=True,
    reason='BUG-D2: well_known_name_is_managed() uses a prefix match, so any '
    'player whose name merely starts with "playerctld" is ignored',
)
@pytest.mark.parametrize(
    'suffix', ['playerctldX', 'playerctld2', 'playerctld_x']
)
async def test_player_whose_name_only_starts_with_playerctld_is_managed(
    bus_address, playerctld, daemon_bus, suffix
):
    other = await RawPlayer.create(bus_address, suffix)

    await wait_for_players(daemon_bus, [PREFIX + suffix])
    await other.disconnect()


@pytest.mark.parametrize(
    'name',
    [
        'a',
        'x' * 200,
        'x' * 232,  # 23 + 232 = 255, the longest valid bus name
        'with-dash_and_underscore',
        'dotted.instance.name.v1',
        'instance.i1234',
        'UPPER.Mixed.case',
    ],
)
async def test_odd_but_valid_player_names_are_managed_and_proxied(
    bus_address, playerctld, daemon_bus, playerctl, name
):
    player = await RawPlayer.create(bus_address, name)

    await wait_for_players(daemon_bus, [PREFIX + name])
    result = await playerctl.run('-p playerctld status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'
    await player.disconnect()
    await wait_for_player_names(daemon_bus, [])
    assert_healthy(playerctld)


@pytest.mark.parametrize(
    'name',
    [
        'org.mpris.MediaPlayer2.',
        'org.mpris.MediaPlayer2.' + 'x' * 233,
        'org.mpris.MediaPlayer2..double',
        'org.mpris.MediaPlayer2.1digit',
        'org.mpris.MediaPlayer2.sp ace',
        'org.mpris.MediaPlayer2.uml\u00e4ut',
        'org.mpris.MediaPlayer2.trailing.',
    ],
)
async def test_invalid_player_names_are_refused_by_the_bus(
    bus_address, playerctld, daemon_bus, name
):
    # dbus_next would refuse the name itself, so ask the bus directly
    bus = await new_bus(bus_address)

    reply = await dbus_call(bus, 'RequestName', 'su', [name, 0])

    assert reply.message_type == MessageType.ERROR, reply.body
    assert await player_names(daemon_bus) == []
    assert_healthy(playerctld)
    await close_bus(bus)


async def test_queued_second_owner_of_a_player_name_is_not_a_second_player(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [first] = await mpris_factory('dup')
    await first.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'dup'])

    [second] = await mpris_factory('dup', queued=True)
    await second.ping()

    assert await player_names(daemon_bus) == [PREFIX + 'dup']
    await first.disconnect()
    # the queued one takes over the name: still exactly one entry
    await wait_for_players(daemon_bus, [PREFIX + 'dup'])
    assert_healthy(playerctld)

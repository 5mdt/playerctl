"""US-10.27: As an operator, I want playerctld to start, stop and restart
cleanly: odd command lines are refused, signals end it without leaving the
bus name behind, and a crashed or restarted daemon rebuilds its state while
the clients that follow it carry on."""

import asyncio
import os
import signal

import pytest

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
    new_bus,
    process_state,
    wait_exit,
)
from ..helpers.follow import follow_cmd, next_line
from ..helpers.mpris import name_owner_pid, wait_for_name, gated

# ---- command line ----------------------------------------------------------


@pytest.mark.parametrize(
    'args',
    ['foo', 'SHIFT', 'shift2', '""', "' '", 'daemon-', '-- foo'],
)
async def test_unknown_commands_are_refused_with_the_help(bus_address, args):
    code, stdout, _ = await playerctld_cli(bus_address, args)

    assert code == 1
    assert 'Usage:' in stdout
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


@pytest.mark.parametrize(
    'args', ['--bogus', '-x', '--help-nonsense', '--version']
)
async def test_unknown_options_are_refused(bus_address, args):
    code, _, stderr = await playerctld_cli(bus_address, args)

    assert code == 1
    assert 'nknown option' in stderr, stderr
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


@pytest.mark.parametrize('args', ['--help', '-h'])
async def test_help_option_prints_usage_and_exits_0(bus_address, args):
    code, stdout, _ = await playerctld_cli(bus_address, args)

    assert code == 0
    assert 'Usage:' in stdout
    assert 'shift' in stdout


@pytest.mark.parametrize(
    'args', ['shift extra', 'shift --', 'unshift a b c', 'shift shift']
)
async def test_extra_arguments_after_a_command_do_not_start_a_daemon(
    bus_address, args
):
    code, _, stderr = await playerctld_cli(bus_address, args)

    # no daemon runs, so the command fails like a plain shift would
    assert code == 1
    assert 'Cannot' in stderr
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


@pytest.mark.parametrize('command', ['shift', 'unshift'])
async def test_shift_commands_without_a_daemon_do_not_start_one(
    bus_address, command
):
    code, _, stderr = await playerctld_cli(bus_address, command)

    assert code == 1
    assert 'Cannot' in stderr
    # NO_AUTO_START: asking must not activate the service
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) is None


async def test_no_session_bus_is_a_clean_failure():
    env = {
        **os.environ,
        'DBUS_SESSION_BUS_ADDRESS': 'unix:path=/nonexistent/bus',
    }
    for args in ('', 'shift', 'daemon'):
        proc = await asyncio.create_subprocess_shell(
            f'playerctld {args}',
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(proc.communicate(), 4)
        assert proc.returncode == 1, args
        assert b'could not connect' in stderr, stderr


async def test_parallel_daemon_commands_start_one_daemon(bus_address):
    results = await asyncio.gather(
        *(playerctld_cli(bus_address, 'daemon') for _ in range(8))
    )

    assert [r[0] for r in results] == [0] * 8, results
    await wait_for_name(bus_address, PLAYERCTLD_NAME)
    pid = await name_owner_pid(bus_address, PLAYERCTLD_NAME)
    again = await playerctld_cli(bus_address, 'daemon')
    assert again[0] == 0
    assert await name_owner_pid(bus_address, PLAYERCTLD_NAME) == pid
    os.kill(pid, signal.SIGTERM)


# ---- signals -----------------------------------------------------------------


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
async def test_terminating_signals_end_the_daemon_and_release_the_name(
    bus_address, mpris_factory, sig
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist', 'title')
    proc = await start_playerctld(bus_address)

    proc.send_signal(sig)
    code = await wait_exit(proc)

    assert code in (0, -sig), code
    await wait_for_name(bus_address, PLAYERCTLD_NAME, present=False)
    assert process_state(proc.pid) is None  # reaped, no zombie
    # the name is free for a successor, which sees the player again
    fresh = await start_playerctld(bus_address)
    bus = await new_bus(bus_address)
    await wait_for_players(bus, [PREFIX + 'player1'])
    assert fresh.returncode is None
    await close_bus(bus)


async def test_sigpipe_is_ignored(bus_address, playerctld, daemon_bus):
    for _ in range(3):
        playerctld.send_signal(signal.SIGPIPE)
        await asyncio.sleep(0.05)

    assert playerctld.returncode is None
    assert await player_names(daemon_bus) == []
    assert_healthy(playerctld)


async def test_stopped_and_continued_daemon_resumes(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    playerctld.send_signal(signal.SIGSTOP)
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist', 'title')
    playerctld.send_signal(signal.SIGCONT)

    await wait_for_players(daemon_bus, [PREFIX + 'player1'])
    assert_healthy(playerctld)


async def test_signal_while_clients_are_mid_call_does_not_hang_them(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    from ..helpers.daemon_attack import raw_call

    [mpris] = await mpris_factory(
        'slow', prepare=gated(lambda g: g.hold('Play'))
    )
    await mpris.set_artist_title('artist', 'title')
    await wait_for_players(daemon_bus, [PREFIX + 'slow'])
    call = asyncio.ensure_future(
        raw_call(
            daemon_bus, 'org.mpris.MediaPlayer2.Player', 'Play', timeout=3
        )
    )
    await mpris.gate.wait_held(1)

    playerctld.send_signal(signal.SIGTERM)
    reply = await call

    assert reply.message_type.name == 'ERROR'
    await wait_exit(playerctld)


# ---- crash and restart -----------------------------------------------------


async def test_killed_daemon_restarts_with_the_players_it_finds(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    players = await mpris_factory('p1', 'p2', 'p3')
    for p in players:
        await p.set_artist_title('artist', 'title')
    await wait_for_players(
        daemon_bus, [PREFIX + n for n in ('p1', 'p2', 'p3')]
    )

    playerctld.kill()
    await playerctld.wait()
    await wait_for_name(bus_address, PLAYERCTLD_NAME, present=False)
    fresh = await start_playerctld(bus_address)

    names = await wait_for_players(
        daemon_bus, [PREFIX + n for n in ('p1', 'p2', 'p3')]
    )
    assert len(names) == 3
    assert_healthy(fresh)
    assert fresh.pid != playerctld.pid


async def test_restart_while_a_player_comes_and_goes(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    [keep] = await mpris_factory('keep')
    await keep.set_artist_title('artist', 'title')
    playerctld.kill()
    await playerctld.wait()

    blink = await RawPlayer.create(bus_address, 'blink')
    fresh = await start_playerctld(bus_address)
    await blink.disconnect()

    await wait_for_players(daemon_bus, [PREFIX + 'keep'])
    assert_healthy(fresh)


async def test_follower_survives_a_daemon_restart(
    bus_address, playerctl, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    proc = await playerctl.start(follow_cmd('playerctld'))
    assert await next_line(proc) == 'playerctld: artist1 - title1'

    playerctld.kill()
    await playerctld.wait()
    fresh = await start_playerctld(bus_address)
    await mpris.set_artist_title('artist2', 'title2')

    assert proc.running()
    lines = []
    for _ in range(4):
        lines.append(await next_line(proc, timeout=3))
        if lines[-1] == 'playerctld: artist2 - title2':
            break
    assert lines[-1] == 'playerctld: artist2 - title2', lines
    assert fresh.returncode is None


async def test_follower_survives_repeated_daemon_restarts(
    bus_address, playerctl, playerctld, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist0', 'title0')
    proc = await playerctl.start(follow_cmd('playerctld'))
    assert await next_line(proc) == 'playerctld: artist0 - title0'
    current = playerctld

    for i in range(1, 4):
        current.terminate()
        await current.wait()
        current = await start_playerctld(bus_address)
        await mpris.set_artist_title(f'artist{i}', f'title{i}')
        seen = []
        while f'playerctld: artist{i} - title{i}' not in seen:
            seen.append(await next_line(proc, timeout=3))
            assert len(seen) < 6, seen

    assert proc.running()


async def test_kill_during_an_inflight_shift_gives_the_client_an_error(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    from ..helpers.mpris import PROPERTIES_INTERFACE

    [hang] = await mpris_factory(
        'hang',
        prepare=gated(
            lambda g: g.hold(
                'Get', PROPERTIES_INTERFACE, 'org.mpris.MediaPlayer2.Player'
            )
        ),
    )
    await hang.set_artist_title('artist', 'hang')
    [calm] = await mpris_factory('calm')
    await calm.set_artist_title('artist', 'calm')
    await wait_for_player_names(daemon_bus, [PREFIX + 'calm', PREFIX + 'hang'])
    shift = asyncio.ensure_future(playerctld_cli(bus_address, 'shift'))
    await hang.gate.wait_held(1)

    playerctld.kill()
    code, _, stderr = await asyncio.wait_for(shift, 3)

    assert code == 1
    assert 'Cannot shift' in stderr, stderr


async def test_restart_while_shifts_are_in_flight(
    bus_address, playerctld, daemon_bus, mpris_factory
):
    for name in ('a', 'b', 'c'):
        [mpris] = await mpris_factory(name)
        await mpris.set_artist_title('artist', name)
    await wait_for_players(daemon_bus, [PREFIX + n for n in 'abc'])

    shifts = [
        asyncio.ensure_future(playerctld_cli(bus_address, 'shift'))
        for _ in range(10)
    ]
    await asyncio.sleep(0.01)
    playerctld.kill()
    results = await asyncio.wait_for(asyncio.gather(*shifts), 4)

    assert all(code in (0, 1) for code, _, _ in results), results
    fresh = await start_playerctld(bus_address)
    await wait_for_players(daemon_bus, [PREFIX + n for n in 'abc'])
    assert_healthy(fresh)


async def test_start_with_100_existing_players(bus_address):
    players = [
        await RawPlayer.create(bus_address, f'pre{i:03d}') for i in range(100)
    ]

    proc = await start_playerctld(bus_address)
    bus = await new_bus(bus_address)
    names = await wait_for_players(
        bus, [PREFIX + f'pre{i:03d}' for i in range(100)], timeout=3
    )

    assert len(set(names)) == 100
    assert proc.returncode is None
    # all 100 are controllable one after the other
    for _ in range(100):
        code, _, stderr = await playerctld_cli(bus_address, 'shift')
        assert code == 0, stderr
    assert sorted(await player_names(bus)) == sorted(names)
    await close_bus(bus)
    for p in players:
        await p.disconnect()

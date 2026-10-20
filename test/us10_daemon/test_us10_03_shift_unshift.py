"""US-10.3: As a user, I want `playerctld shift` / `unshift` to cycle the
active player, with exit code 1 when there is none."""

import pytest
from dbus_next import MessageType

from ..helpers.daemon import (
    SignalListener,
    playerctld_call,
    playerctld_cli,
    playerctld_shift,
)
from ..helpers.mpris import PLAYERCTLD_INTERFACE
from ..helpers.follow import follow_cmd, next_line


async def test_shift_and_unshift_cycle_players(
    bus_address, playerctl, playerctld, mpris_factory
):
    [mpris1, mpris2, mpris3] = await mpris_factory(
        'player1', 'player2', 'player3'
    )
    proc = await playerctl.start(follow_cmd('playerctld'))

    await mpris1.set_artist_title('artist1', 'title1')
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    await mpris3.set_artist_title('artist3', 'title3')
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue

    code = await playerctld_shift(bus_address)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    code = await playerctld_shift(bus_address)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist1 - title1', proc.queue

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist2 - title2', proc.queue

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0
    line = await proc.queue.get()
    assert line == 'playerctld: artist3 - title3', proc.queue


async def test_shift_without_players_fails(
    bus_address, playerctl, playerctld, mpris_factory
):
    await playerctl.start(follow_cmd('playerctld'))

    code = await playerctld_shift(bus_address)
    assert code == 1

    [mpris1] = await mpris_factory('player1')
    code = await playerctld_shift(bus_address)
    assert code == 0

    await mpris1.disconnect()
    code = await playerctld_shift(bus_address)
    assert code == 1

    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 1

    [mpris1] = await mpris_factory('player1')
    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 0

    await mpris1.disconnect()
    code = await playerctld_shift(bus_address, reverse=True)
    assert code == 1


@pytest.mark.parametrize('member', ['Shift', 'Unshift'])
async def test_single_player_stays_active_without_signals(
    member, bus_address, playerctld, daemon_bus, mpris_factory
):
    [mpris] = await mpris_factory('player1')
    await mpris.set_artist_title('artist1', 'title1')
    listener = await SignalListener.start(bus_address)

    reply = await playerctld_call(daemon_bus, PLAYERCTLD_INTERFACE, member)

    assert reply.message_type == MessageType.METHOD_RETURN, reply.body
    assert reply.body == ['org.mpris.MediaPlayer2.player1']
    assert listener.queue.empty(), listener.queue.get_nowait()
    await listener.close()


@pytest.mark.parametrize('command', ['shift', 'unshift'])
async def test_failure_message_without_players(
    command, bus_address, playerctld
):
    code, _, stderr = await playerctld_cli(bus_address, command)

    assert code == 1
    assert stderr.startswith(f'Cannot {command}:'), stderr
    assert 'No player is being controlled by playerctld' in stderr


@pytest.mark.parametrize('command', ['shift', 'unshift'])
async def test_failure_message_without_daemon(command, bus_address):
    code, _, stderr = await playerctld_cli(bus_address, command)

    assert code == 1
    assert stderr.startswith(f'Cannot {command}:'), stderr


async def test_follow_player_name_updates_on_shift(
    bus_address, playerctl, playerctld, mpris_factory
):
    # 5mdt/playerctl#18: follow without -p printed nothing when the active
    # player changed with `playerctld shift`
    [mpris1, mpris2] = await mpris_factory('player1', 'player2')
    await mpris1.set_artist_title('artist1', 'title1')
    await mpris2.set_artist_title('artist2', 'title2')
    proc = await playerctl.start("metadata --format '{{playerName}}' --follow")
    first = await next_line(proc)

    code = await playerctld_shift(bus_address)

    assert code == 0
    second = await next_line(proc)
    assert {first, second} == {'player1', 'player2'}


async def test_pause_shift_play_alternates_players(
    bus_address, playerctl, playerctld, mpris_factory
):
    # 5mdt/playerctl#25: `pause -a && playerctld shift && play` sometimes
    # played the previous player again
    players = await mpris_factory('player1', 'player2')
    for mpris in players:
        await mpris.set_artist_title('artist', 'title')

    played = []
    for _ in range(6):
        await playerctl.run('--all-players pause')
        assert await playerctld_shift(bus_address) == 0
        result = await playerctl.run('-p playerctld play')
        assert result.returncode == 0, result.stderr
        [target] = [m for m in players if m.play_called]
        played.append(target)
        for mpris in players:
            mpris.play_called = False

    assert all(a is not b for a, b in zip(played, played[1:])), played

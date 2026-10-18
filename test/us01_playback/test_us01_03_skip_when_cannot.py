"""US-1.3: As a user, I want a player to be skipped when it reports it can't do
the action (`CanPlay`, `CanPause`, `CanGoNext`, ...)."""

import pytest

from ..helpers.mpris import was_called

# command -> the Can* property (mock attribute) that gates it
GATES = [
    ('play', 'can_play'),
    ('pause', 'can_pause'),
    ('play-pause', 'can_play'),
    ('stop', 'can_play'),
    ('next', 'can_go_next'),
    ('previous', 'can_go_previous'),
]


@pytest.mark.parametrize('command,gate', GATES)
async def test_only_player_cannot(command, gate, playerctl, mpris_factory):
    [mpris] = await mpris_factory('blocked')
    await mpris.emit_properties(**{gate: False})

    result = await playerctl.run(f'-p blocked {command}')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert not was_called(mpris, command)


@pytest.mark.parametrize('command,gate', GATES)
async def test_message_suppressed_with_no_messages(
    command, gate, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('blocked')
    await mpris.emit_properties(**{gate: False})

    result = await playerctl.run(f'-s -p blocked {command}')

    assert result.returncode == 1
    assert result.stderr == ''
    assert not was_called(mpris, command)


@pytest.mark.parametrize('command,gate', GATES)
async def test_capable_player_used_instead(
    command, gate, playerctl, mpris_factory
):
    blocked, able = await mpris_factory('blocked', 'able')
    await blocked.emit_properties(**{gate: False})

    result = await playerctl.run(f'-p blocked,able {command}')

    assert result.returncode == 0, result.stderr
    assert was_called(able, command)
    assert not was_called(blocked, command)


@pytest.mark.parametrize('command,gate', GATES)
async def test_all_players_skips_incapable(
    command, gate, playerctl, mpris_factory
):
    blocked, able = await mpris_factory('blocked', 'able')
    await blocked.emit_properties(**{gate: False})

    result = await playerctl.run(f'-a {command}')

    assert result.returncode == 0, result.stderr
    assert was_called(able, command)
    assert not was_called(blocked, command)


async def test_unrelated_can_flag_does_not_block(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    await mpris.emit_properties(can_go_next=False, can_pause=False)

    result = await playerctl.run('-p commands play')

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, 'play')

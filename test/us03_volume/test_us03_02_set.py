"""US-3.2: As a user, I want `volume 0.5` to set the level."""

import pytest


async def test_volume_set(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 1.0

    result = await playerctl.run('-p commands volume 0.8')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == 0.8


async def test_volume_set_skipped_when_cannot_control(
    playerctl, mpris_factory
):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5
    await mpris.emit_properties(can_control=False)

    result = await playerctl.run('-p commands volume 0.8')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert mpris.volume == 0.5


async def test_volume_set_falls_back_to_controllable_player(
    playerctl, mpris_factory
):
    first, second = await mpris_factory('commands1', 'commands2')
    first.volume = 0.5
    await first.emit_properties(can_control=False)

    result = await playerctl.run('volume 0.8')

    assert result.returncode == 0, result.stderr
    assert first.volume == 0.5
    assert second.volume == 0.8


@pytest.mark.parametrize('arg', ['1.5', '-1', '100'])
async def test_volume_out_of_range_not_applied(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    await playerctl.run(f'-p commands volume -- {arg}')

    # either rejected (unchanged) or clamped, but never outside 0.0-1.0
    assert 0.0 <= mpris.volume <= 1.0


@pytest.mark.parametrize('arg', ['abc', '+', '-'])
async def test_volume_invalid_absolute_rejected(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    result = await playerctl.run(f'-p commands volume -- {arg}')

    assert result.returncode == 1
    assert 'could not parse volume as a number' in result.stderr.lower()
    assert mpris.volume == 0.5

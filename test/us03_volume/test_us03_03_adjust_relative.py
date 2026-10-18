"""US-3.3: As a user, I want `volume 0.1+` / `0.1-` to change the level relative
to the current one."""

import pytest


@pytest.mark.parametrize(
    'start, arg, expected',
    [
        (0.5, '0.1+', 0.6),
        (0.5, '0.1-', 0.4),
        (0.2, '0.25+', 0.45),
        (0.8, '0.5-', 0.3),
        (0.5, '0+', 0.5),
    ],
)
async def test_volume_adjust_relative(
    start, arg, expected, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('commands')
    mpris.volume = start

    result = await playerctl.run(f'-p commands volume {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == pytest.approx(expected)


async def test_volume_adjust_repeated(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    await playerctl.run('-p commands volume 0.1+')
    await playerctl.run('-p commands volume 0.1+')
    result = await playerctl.run('-p commands volume 0.3-')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == pytest.approx(0.4)


@pytest.mark.parametrize('arg', ['0.3+', '0.3-'])
async def test_volume_adjust_stays_within_bounds(
    arg, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.9 if arg.endswith('+') else 0.1

    result = await playerctl.run(f'-p commands volume {arg}')

    assert result.returncode == 0, result.stderr
    assert 0.0 <= mpris.volume <= 1.0


@pytest.mark.parametrize('arg', ['abc', 'x+', 'one-', '+', '-'])
async def test_volume_adjust_invalid_rejected(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    result = await playerctl.run(f'-p commands volume -- {arg}')

    assert result.returncode == 1
    assert 'could not parse volume as a number' in result.stderr.lower()
    assert mpris.volume == 0.5


async def test_volume_adjust_all_players(playerctl, mpris_factory):
    [a, b] = await mpris_factory('a_player', 'b_player')
    a.volume = 0.2
    b.volume = 0.6

    result = await playerctl.run('-a volume 0.1+')

    assert result.returncode == 0, result.stderr
    assert a.volume == pytest.approx(0.3)
    assert b.volume == pytest.approx(0.7)

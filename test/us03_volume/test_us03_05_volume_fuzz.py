"""US-3.5: As a scripter, I want `volume` to clamp valid levels to 0.0..1.0
and reject everything else with exit code 1, leaving the player's volume
unchanged, whatever garbage the argument holds."""

import pytest

from ..helpers.cli_fuzz import (
    HOSTILE_NUMBERS,
    NOT_A_NUMBER,
    assert_sane,
    prepared,
    q,
    run,
    run_raw,
    snapshot,
)


@pytest.mark.parametrize('name', sorted(HOSTILE_NUMBERS))
async def test_hostile_volume_never_corrupts(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'vol')
    before = snapshot(mpris)

    result = await run(
        playerctl, f'-p vol volume -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert_sane(result, name)
    assert not result.stdout
    assert 0.0 <= mpris.volume <= 1.0
    if result.returncode == 1:
        assert snapshot(mpris) == before


@pytest.mark.parametrize('name', NOT_A_NUMBER)
async def test_non_numeric_volume_message(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'vol')

    result = await run(
        playerctl, f'-p vol volume -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert result.returncode == 1, result.stderr
    assert 'could not parse volume as a number' in result.stderr
    assert mpris.volume == 0.5


@pytest.mark.parametrize(
    'arg, expected',
    [
        ('0.3', 0.3),
        ('+0.3', 0.3),
        ('.5', 0.5),
        ('00.5', 0.5),
        ('1e0', 1.0),
        ('1e-5', 1e-5),
        ('2', 1.0),
        ('5.', 1.0),
        ('1e308', 1.0),
        ('9223372036854775807', 1.0),
        ('-0.3', 0.0),
        ('-2', 0.0),
        ('-0', 0.0),
        ('+0', 0.0),
        ('1e-400', 0.0),
        ('-9223372036854775808', 0.0),
    ],
)
async def test_absolute_volume_is_clamped(
    arg, expected, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'vol')

    result = await run(playerctl, f'-p vol volume -- {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == pytest.approx(expected)


@pytest.mark.parametrize(
    'arg, expected',
    [
        ('0.3+', 0.8),
        ('0.3-', 0.2),
        ('0.5+', 1.0),
        ('0.5-', 0.0),
        ('2+', 1.0),
        ('2-', 0.0),
        ('0+', 0.5),
        ('0-', 0.5),
        ('1e-3+', 0.501),
    ],
)
async def test_relative_volume_is_clamped(
    arg, expected, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'vol')

    result = await run(playerctl, f'-p vol volume {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == pytest.approx(expected)


@pytest.mark.parametrize('extra', ['0.9', 'abc', "''", '9+', '$(id)'])
async def test_extra_arguments_after_volume_are_ignored(
    extra, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'vol')

    result = await run(playerctl, f'-p vol volume 0.25 {extra}')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == pytest.approx(0.25)


async def test_all_players_rejected_value_touches_nobody(
    playerctl, mpris_factory
):
    players = await prepared(mpris_factory, 'one', 'two', 'three')

    result = await run(playerctl, '-a volume -- 0.5+-')

    assert result.returncode == 1
    assert [p.volume for p in players] == [0.5] * 3


async def test_all_players_clamped_independently(playerctl, mpris_factory):
    one, two = await prepared(mpris_factory, 'one', 'two')
    one.volume = 0.9
    two.volume = 0.1

    result = await run(playerctl, '-a volume 0.3+')

    assert result.returncode == 0, result.stderr
    assert one.volume == pytest.approx(1.0)
    assert two.volume == pytest.approx(0.4)


@pytest.mark.parametrize(
    'raw', [b'\xff', b'0.5\xff', b'\xc0\x80', b'\xe2\x82']
)
async def test_invalid_utf8_volume_argument(raw, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'vol')

    rc, out, err = await run_raw(playerctl, '-p', 'vol', 'volume', raw)

    assert rc == 1
    assert not out
    err.decode()
    assert b'CRITICAL' not in err
    assert mpris.volume == 0.5


@pytest.mark.parametrize('value', [0.0, 0.25, 1.0, 2.0])
async def test_volume_query_prints_plain_number(
    value, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'vol')
    mpris.volume = value

    result = await run(playerctl, '-p vol volume')

    assert result.returncode == 0, result.stderr
    assert float(result.stdout) == pytest.approx(value)

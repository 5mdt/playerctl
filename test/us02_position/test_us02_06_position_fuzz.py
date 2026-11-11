"""US-2.6: As a scripter, I want `position` to either do exactly what the
documented grammar says or reject the input with exit code 1 and leave the
player untouched, whatever garbage (huge, non-finite, hex, unicode, shell
metacharacters, invalid UTF-8) the argument holds."""

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

OUT_OF_RANGE = ['big-float', 'int64-max', 'int64-overflow', 'neg-int64-min']


@pytest.mark.parametrize('name', sorted(HOSTILE_NUMBERS))
async def test_hostile_position_never_corrupts(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')
    before = snapshot(mpris)

    result = await run(
        playerctl, f'-p seeker position -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert_sane(result, name)
    assert not result.stdout
    calls = (mpris.seek_called_with, mpris.set_position_called_with)
    if result.returncode == 1:
        assert snapshot(mpris) == before
    else:
        assert calls != (None, None)


@pytest.mark.parametrize('name', NOT_A_NUMBER)
async def test_non_numeric_position_message(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(
        playerctl, f'-p seeker position -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert result.returncode == 1, result.stderr
    assert 'Could not parse position as a number' in result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize('name', OUT_OF_RANGE)
async def test_out_of_range_position_rejected(name, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(
        playerctl, f'-p seeker position -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert result.returncode == 1, result.stderr
    assert 'Position out of range' in result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize(
    'arg, micros',
    [
        ('5', 5_000_000),
        ('+5', 5_000_000),
        ('00005', 5_000_000),
        ('5.', 5_000_000),
        ('.5', 500_000),
        ('1.5', 1_500_000),
        ('1e3', 1_000_000_000),
        ('1e-3', 1_000),
        ('0', 0),
        ('-0', 0),
        ('0.0000001', 0),
        ('9e12', 9_000_000_000_000_000_000),
    ],
)
async def test_absolute_grammar(arg, micros, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(playerctl, f'-p seeker position -- {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with[1] == micros


@pytest.mark.parametrize(
    'arg, micros',
    [
        ('5+', 5_000_000),
        ('5-', -5_000_000),
        ('0.5-', -500_000),
        ('1e3+', 1_000_000_000),
        ('1e12-', -1_000_000_000_000_000_000),
    ],
)
async def test_relative_grammar(arg, micros, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(playerctl, f'-p seeker position {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.set_position_called_with is None
    assert mpris.seek_called_with == micros


@pytest.mark.parametrize('arg', ['-5', '-1e-7', '-0.5', '-1e12'])
async def test_negative_absolute_position_rejected(
    arg, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(playerctl, f'-p seeker position -- {arg}')

    assert result.returncode == 1
    assert 'Position out of range' in result.stderr
    assert mpris.set_position_called_with is None
    assert mpris.seek_called_with is None


@pytest.mark.parametrize('arg', ['1e308+', '1e308-', '1e18-', '1e15', '1e13+'])
async def test_overflowing_microseconds_rejected(
    arg, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(playerctl, f'-p seeker position -- {arg}')

    assert result.returncode == 1
    assert 'Position out of range' in result.stderr
    assert mpris.set_position_called_with is None
    assert mpris.seek_called_with is None


@pytest.mark.parametrize(
    'extra', ['2', 'abc', "''", '--', '5+', '$(id)', '-- -1']
)
async def test_extra_arguments_after_position_are_ignored(
    extra, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'seeker')

    result = await run(playerctl, f'-p seeker position 1 {extra}')

    assert_sane(result)
    assert result.returncode == 0, result.stderr
    assert mpris.set_position_called_with[1] == 1_000_000


async def test_all_players_rejected_value_touches_nobody(
    playerctl, mpris_factory
):
    players = await prepared(mpris_factory, 'one', 'two', 'three')
    before = [snapshot(p) for p in players]

    result = await run(playerctl, '-a position -- 5+-')

    assert result.returncode == 1
    assert 'Could not parse position as a number' in result.stderr
    assert [snapshot(p) for p in players] == before


async def test_all_players_valid_value_reaches_everybody(
    playerctl, mpris_factory
):
    players = await prepared(mpris_factory, 'one', 'two', 'three')

    result = await run(playerctl, '-a position 2+')

    assert result.returncode == 0, result.stderr
    assert [p.seek_called_with for p in players] == [2_000_000] * 3


@pytest.mark.parametrize(
    'raw', [b'\xff', b'5\xff', b'\xc0\x80', b'\xed\xa0\x80', b'\xe2\x82']
)
async def test_invalid_utf8_position_argument(raw, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')
    before = snapshot(mpris)

    rc, out, err = await run_raw(playerctl, '-p', 'seeker', 'position', raw)

    assert rc == 1
    assert not out
    err.decode()  # stderr stays valid UTF-8
    assert b'CRITICAL' not in err
    assert snapshot(mpris) == before


async def test_position_with_a_huge_player_name(playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'seeker')
    before = snapshot(mpris)

    result = await run(playerctl, f'-p {q("n" * 100_000)} position 5')

    assert_sane(result)
    assert result.returncode == 1
    assert snapshot(mpris) == before

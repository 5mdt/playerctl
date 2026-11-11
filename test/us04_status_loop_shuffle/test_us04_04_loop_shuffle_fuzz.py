"""US-4.4: As a scripter, I want `loop` and `shuffle` to accept only their
documented words (any letter case) and reject every other argument with exit
code 1 and an unchanged player."""

import pytest

from ..helpers.cli_fuzz import (
    HOSTILE_NUMBERS,
    assert_sane,
    prepared,
    q,
    run,
    run_raw,
    snapshot,
)

LOOP_WORDS = ['None', 'Track', 'Playlist']
SHUFFLE_WORDS = ['On', 'Off', 'Toggle']


@pytest.mark.parametrize('command', ['loop', 'shuffle'])
@pytest.mark.parametrize('name', sorted(HOSTILE_NUMBERS))
async def test_hostile_value_rejected(name, command, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    before = snapshot(mpris)

    result = await run(
        playerctl, f'-p sw {command} -- {q(HOSTILE_NUMBERS[name])}'
    )

    assert_sane(result, name)
    assert not result.stdout
    if name == 'empty':
        # `loop ''` is not a query: it must not silently do anything
        assert snapshot(mpris) == before
        return
    assert result.returncode == 1, result.stderr
    assert f'unknown {command} status' in result.stderr
    assert snapshot(mpris) == before


@pytest.mark.parametrize('word', LOOP_WORDS)
@pytest.mark.parametrize('case', ['lower', 'upper', 'swap'])
async def test_loop_words_any_case(word, case, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    mpris.loop_status = 'Track' if word == 'None' else 'None'
    arg = {
        'lower': word.lower(),
        'upper': word.upper(),
        'swap': word.swapcase(),
    }[case]

    result = await run(playerctl, f'-p sw loop {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.loop_status == word


@pytest.mark.parametrize(
    'word, start, expected',
    [
        ('On', False, True),
        ('on', False, True),
        ('ON', True, True),
        ('Off', True, False),
        ('oFF', False, False),
        ('Toggle', False, True),
        ('TOGGLE', True, False),
    ],
)
async def test_shuffle_words_any_case(
    word, start, expected, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'sw')
    mpris.shuffle = start

    result = await run(playerctl, f'-p sw shuffle {word}')

    assert result.returncode == 0, result.stderr
    assert mpris.shuffle is expected


@pytest.mark.parametrize(
    'arg', [' none', 'none ', 'no ne', 'tracks', 'playlis', 'None,Track', 'n']
)
async def test_loop_near_misses_rejected(arg, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    mpris.loop_status = 'Track'

    result = await run(playerctl, f'-p sw loop {q(arg)}')

    assert result.returncode == 1
    assert 'unknown loop status' in result.stderr
    assert mpris.loop_status == 'Track'


@pytest.mark.parametrize(
    'arg', [' on', 'on ', 'of', 'offf', 'true', '1', 'On,Off', 'tog gle']
)
async def test_shuffle_near_misses_rejected(arg, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    mpris.shuffle = True

    result = await run(playerctl, f'-p sw shuffle {q(arg)}')

    assert result.returncode == 1
    assert 'unknown shuffle status' in result.stderr
    assert mpris.shuffle is True


@pytest.mark.parametrize('command', ['loop', 'shuffle'])
async def test_extra_arguments_are_ignored(command, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    word = 'Track' if command == 'loop' else 'On'

    result = await run(playerctl, f'-p sw {command} {word} bogus --')

    assert result.returncode == 0, result.stderr
    assert (
        (mpris.loop_status == 'Track') if command == 'loop' else mpris.shuffle
    )


@pytest.mark.parametrize('command', ['loop', 'shuffle'])
async def test_all_players_rejected_value_touches_nobody(
    command, playerctl, mpris_factory
):
    players = await prepared(mpris_factory, 'one', 'two')
    before = [snapshot(p) for p in players]

    result = await run(playerctl, f'-a {command} -- bogus')

    assert result.returncode == 1
    assert [snapshot(p) for p in players] == before


@pytest.mark.parametrize('command', ['loop', 'shuffle', 'status'])
@pytest.mark.parametrize('raw', [b'\xff', b'on\xff', b'\xc0\x80'])
async def test_invalid_utf8_argument(command, raw, playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'sw')
    before = snapshot(mpris)

    rc, out, err = await run_raw(playerctl, '-p', 'sw', command, raw)

    err.decode()
    out.decode()
    assert rc in (0, 1)
    assert b'CRITICAL' not in err
    assert snapshot(mpris) == before
    if command != 'status':
        assert rc == 1

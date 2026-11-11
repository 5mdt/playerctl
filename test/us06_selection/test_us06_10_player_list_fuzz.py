"""US-6.10: As a scripter, I want hostile `--player` / `--ignore-player`
lists (empty items, blanks, repeats, `%any` twice, ten thousand entries)
handled without a crash, a hang or a CRITICAL, and I want the selection to
follow the documented order."""

import pytest

from ..helpers.cli_fuzz import assert_sane, prepared, q, run

BLANK_LISTS = ["''", "' '", "','", "',,,'", "' , '", "'a,,b'", "',a'", "'a,'"]


async def three(mpris_factory):
    a, b, c = await prepared(mpris_factory, 'a', 'b', 'c')
    a.playback_status = 'Playing'
    b.playback_status = 'Paused'
    c.playback_status = 'Stopped'
    return a, b, c


@pytest.mark.parametrize('arg', BLANK_LISTS)
@pytest.mark.parametrize('option', ['-p', '--player', '-i', '--ignore-player'])
async def test_blank_list_items_are_harmless(
    arg, option, playerctl, mpris_factory
):
    await three(mpris_factory)

    result = await run(playerctl, f'{option} {arg} status')

    assert_sane(result, arg)
    assert result.returncode in (0, 1)
    assert not result.stdout or result.stdout in (
        'Playing',
        'Paused',
        'Stopped',
    )
    if result.returncode == 1:
        assert 'No players found' in result.stderr


@pytest.mark.parametrize(
    'args, expected',
    [
        ('-p a,b', 'Playing'),
        ('-p b,a', 'Paused'),
        ('-p c,b,a', 'Stopped'),
        ('-p nosuch,b', 'Paused'),
        ('-p b,%any', 'Paused'),
        ('-p %any,b', 'Playing'),
        ('-p c,%any,a', 'Stopped'),
        ('-p a,a,a,b', 'Playing'),
        ('-i a', 'Paused'),
        ('-i a,b', 'Stopped'),
        ('-i a,b,c,d', None),
        ('-i %any', None),
        ('-p a -i a', None),
        ('-p b -i a', 'Paused'),
        ('-i nosuch', 'Playing'),
    ],
)
async def test_selection_order(args, expected, playerctl, mpris_factory):
    await three(mpris_factory)

    result = await run(playerctl, f'{args} status')

    assert_sane(result, args)
    if expected is None:
        assert result.returncode == 1
        assert 'No players found' in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        assert result.stdout == expected


@pytest.mark.parametrize(
    'list_arg',
    ['%any,%any', '%any,a,%any', 'a,%any,b,%any,c', '%any,%any,%any'],
)
async def test_any_placeholder_twice(list_arg, playerctl, mpris_factory):
    await three(mpris_factory)

    result = await run(playerctl, f'-p {list_arg} status')

    assert_sane(result, list_arg)
    assert result.returncode == 0, result.stderr
    assert result.stdout in ('Playing', 'Paused', 'Stopped')


@pytest.mark.parametrize(
    'args',
    [
        '-p a -p b',
        '-p a --player=b',
        '-p b -p a',
        '-i a -i b',
        '-a -p a',
        '-p a -a',
        '-a -i a',
        '-a -a',
        '-s -s -s',
    ],
)
async def test_repeated_and_conflicting_options(
    args, playerctl, mpris_factory
):
    await three(mpris_factory)

    result = await run(playerctl, f'{args} status')

    assert_sane(result, args)
    assert result.returncode in (0, 1)
    assert set(result.stdout.splitlines()) <= {'Playing', 'Paused', 'Stopped'}


async def test_last_player_option_wins(playerctl, mpris_factory):
    await three(mpris_factory)

    first = await run(playerctl, '-p a -p b status')
    second = await run(playerctl, '-p b -p a status')

    assert (first.stdout, second.stdout) == ('Paused', 'Playing')


async def test_all_players_with_player_list_acts_on_the_list(
    playerctl, mpris_factory
):
    await three(mpris_factory)

    result = await run(playerctl, '-a -p a,c status')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['Playing', 'Stopped']


@pytest.mark.parametrize('option', ['-p', '-i'])
async def test_ten_thousand_entries(option, playerctl, mpris_factory):
    await three(mpris_factory)
    names = ','.join(f'p{i}' for i in range(10_000))

    result = await run(playerctl, f'{option} {names} status')

    assert_sane(result)
    if option == '-p':
        assert result.returncode == 1
        assert 'No players found' in result.stderr
    else:
        assert result.returncode == 0
        assert result.stdout == 'Playing'


@pytest.mark.parametrize('item', ['a', '%any', 'nosuch'])
async def test_ten_thousand_repeats(item, playerctl, mpris_factory):
    await three(mpris_factory)

    result = await run(playerctl, f'-p {",".join([item] * 10_000)} status')

    assert_sane(result)
    if item == 'nosuch':
        assert result.returncode == 1
    else:
        assert result.stdout == 'Playing'


async def test_ten_thousand_entries_with_all_players(playerctl, mpris_factory):
    await three(mpris_factory)
    names = ','.join(f'p{i}' for i in range(10_000))

    result = await run(playerctl, f'-a -i {names} status')

    assert_sane(result)
    assert result.stdout.splitlines() == ['Playing', 'Paused', 'Stopped']


@pytest.mark.parametrize(
    'name',
    ['n' * 100_000, 'é漢字🎵', '../../x', 'a b', '%s%n', '$(id)', '*', "a'b"],
)
async def test_hostile_player_names_match_nothing(
    name, playerctl, mpris_factory
):
    a, b, c = await three(mpris_factory)

    result = await run(playerctl, f'-p {q(name)} -s play')

    assert_sane(result)
    assert result.returncode == 1
    assert not (a.play_called or b.play_called or c.play_called)


@pytest.mark.parametrize('name', ['n' * 100_000, 'é漢字🎵', '%any', ' '])
async def test_hostile_ignore_names_ignore_nothing_real(
    name, playerctl, mpris_factory
):
    await three(mpris_factory)

    result = await run(playerctl, f'-i {q(name)} status')

    assert_sane(result)
    if name == '%any':
        assert result.returncode == 1
    else:
        assert result.stdout == 'Playing'


@pytest.mark.parametrize(
    'args', ['-l -p a', '-l -i a', '-l -p a,b -i b', '-l -a', '-l -p ,']
)
async def test_list_all_with_selection_options(args, playerctl, mpris_factory):
    await three(mpris_factory)

    result = await run(playerctl, args)

    assert_sane(result)
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) <= {'a', 'b', 'c'}


@pytest.mark.parametrize(
    'args', ['-l extra', '-l -- --', "-l ''", '-l status', '-l -f x']
)
async def test_list_all_ignores_trailing_arguments(
    args, playerctl, mpris_factory
):
    await three(mpris_factory)

    result = await run(playerctl, args)

    assert_sane(result)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['a', 'b', 'c']

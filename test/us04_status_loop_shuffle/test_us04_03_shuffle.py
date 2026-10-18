"""US-4.3: As a user, I want `shuffle` to print `On`/`Off` and
`shuffle on|off|toggle` to set it (case-insensitive)."""

import pytest


async def test_shuffle_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('shuffle')

    assert query.stdout == ('On' if mpris.shuffle else 'Off'), query.stderr


async def test_shuffle_on(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = False

    result = await playerctl.run('-p commands shuffle on')

    assert result.returncode == 0, result.stderr
    assert mpris.shuffle


async def test_shuffle_toggle(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = True

    result = await playerctl.run('-p commands shuffle toggle')

    assert result.returncode == 0, result.stderr
    assert not mpris.shuffle


async def test_shuffle_off(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = True

    result = await playerctl.run('-p commands shuffle off')

    assert result.returncode == 0, result.stderr
    assert not mpris.shuffle


@pytest.mark.parametrize('start', [False, True])
async def test_shuffle_toggle_both_directions(start, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = start

    result = await playerctl.run('-p commands shuffle toggle')

    assert result.returncode == 0, result.stderr
    assert mpris.shuffle == (not start)


@pytest.mark.parametrize(
    'arg, start, expected',
    [
        ('ON', False, True),
        ('On', False, True),
        ('OFF', True, False),
        ('Off', True, False),
        ('Toggle', False, True),
        ('TOGGLE', True, False),
    ],
)
async def test_shuffle_case_insensitive(
    arg, start, expected, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = start

    result = await playerctl.run(f'-p commands shuffle {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.shuffle == expected


@pytest.mark.parametrize('start', [False, True])
@pytest.mark.parametrize('arg', ['bogus', 'yes', '1', 'true'])
async def test_shuffle_invalid_rejected(arg, start, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = start

    result = await playerctl.run(f'-p commands shuffle {arg}')

    assert result.returncode == 1
    assert 'unknown shuffle status' in result.stderr.lower()
    assert mpris.shuffle == start


@pytest.mark.parametrize('shuffle, expected', [(True, 'On'), (False, 'Off')])
async def test_shuffle_query_on_off(
    shuffle, expected, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('queries')
    mpris.shuffle = shuffle

    query = await playerctl.run('-p queries shuffle')

    assert query.returncode == 0, query.stderr
    assert query.stdout == expected


@pytest.mark.parametrize('arg', ['on', 'off', 'toggle'])
async def test_shuffle_set_skipped_when_cannot_control(
    arg, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = False
    await mpris.emit_properties(can_control=False)

    result = await playerctl.run(f'-p commands shuffle {arg}')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert not mpris.shuffle


async def test_shuffle_skipped_when_player_has_no_shuffle(
    playerctl, mpris_factory
):
    await mpris_factory('queries', hidden=['Shuffle'])

    query = await playerctl.run('-p queries shuffle')

    assert query.returncode == 1
    assert not query.stdout
    assert 'No player could handle this command' in query.stderr


@pytest.mark.parametrize(
    'shuffle, expected', [(True, 'true'), (False, 'false')]
)
async def test_shuffle_with_format(
    shuffle, expected, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('queries')
    mpris.shuffle = shuffle

    query = await playerctl.run("-p queries shuffle --format '{{shuffle}}'")

    assert query.returncode == 0, query.stderr
    assert query.stdout == expected

"""US-4.2: As a user, I want `loop` to print the loop status and
`loop None|Track|Playlist` to set it."""

import pytest


@pytest.mark.parametrize('status', ['None', 'Track', 'Playlist'])
async def test_loop_query(status, playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.loop_status = status

    query = await playerctl.run('-p queries loop')

    assert query.returncode == 0, query.stderr
    assert query.stdout == status, query.stderr


@pytest.mark.parametrize(
    'start, arg, expected',
    [
        ('Track', 'playlist', 'Playlist'),
        ('Playlist', 'None', 'None'),
        ('None', 'Track', 'Track'),
        ('None', 'TRACK', 'Track'),
        ('Track', 'none', 'None'),
    ],
)
async def test_loop_set(start, arg, expected, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.loop_status = start

    result = await playerctl.run(f'-p commands loop {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.loop_status == expected


@pytest.mark.parametrize('arg', ['bogus', 'on', 'toggle'])
async def test_loop_invalid_rejected(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.loop_status = 'Track'

    result = await playerctl.run(f'-p commands loop {arg}')

    assert result.returncode == 1
    assert 'unknown loop status' in result.stderr.lower()
    assert mpris.loop_status == 'Track'


async def test_loop_set_skipped_when_cannot_control(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    await mpris.emit_properties(can_control=False)

    result = await playerctl.run('-p commands loop Track')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert mpris.loop_status == 'None'


async def test_loop_skipped_when_player_has_no_loop_status(
    playerctl, mpris_factory
):
    await mpris_factory('queries', hidden=['LoopStatus'])

    query = await playerctl.run('-p queries loop')

    assert query.returncode == 1
    assert not query.stdout
    assert 'No player could handle this command' in query.stderr


async def test_loop_with_format(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.loop_status = 'Playlist'

    query = await playerctl.run("-p queries loop --format 'loop={{loop}}'")

    assert query.returncode == 0, query.stderr
    assert query.stdout == 'loop=Playlist'

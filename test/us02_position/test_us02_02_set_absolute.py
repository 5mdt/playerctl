"""US-2.2: As a user, I want `position 30` to jump to an absolute position."""

import pytest


@pytest.mark.parametrize(
    'arg, expected',
    [('30', 30000000), ('0', 0), ('12.5', 12500000), ('0.000001', 1)],
)
async def test_set_absolute_position(arg, expected, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title', track_id='/track/7')

    result = await playerctl.run(f'-p seeker position {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.set_position_called_with == ('/track/7', expected)
    assert mpris.seek_called_with is None


async def test_set_position_skipped_when_cannot_seek(playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title')
    await mpris.emit_properties(can_seek=False)

    result = await playerctl.run('-p seeker position 30')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert mpris.set_position_called_with is None


async def test_set_position_without_track_id_fails(playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')

    result = await playerctl.run('-p seeker position 30')

    assert result.returncode == 1
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize(
    'arg, expected', [('1e1', 10000000), ('2.5e0', 2500000)]
)
async def test_exponent_notation(arg, expected, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title', track_id='/track/7')

    result = await playerctl.run(f'-p seeker position {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.set_position_called_with == ('/track/7', expected)


async def test_negative_absolute_position_rejected(playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title', track_id='/track/7')

    result = await playerctl.run('-p seeker position -- -5')

    assert result.returncode == 1
    assert mpris.set_position_called_with is None
    assert mpris.seek_called_with is None

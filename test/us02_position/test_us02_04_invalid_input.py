"""US-2.4: As a user, I want input that isn't a number to be rejected with an
error."""

import pytest


@pytest.mark.parametrize('arg', ['abc', 'x+', 'one-', '+', '-', '++'])
async def test_invalid_position_rejected(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title')

    result = await playerctl.run(f'-p seeker position -- {arg}')

    assert result.returncode == 1
    assert 'Could not parse position as a number' in result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize('arg', ['10abc', '5s', '1.5.2', '3x+', '2:30'])
async def test_trailing_garbage_rejected(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title')

    result = await playerctl.run(f'-p seeker position -- {arg}')

    assert result.returncode == 1
    assert 'Could not parse position as a number' in result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None

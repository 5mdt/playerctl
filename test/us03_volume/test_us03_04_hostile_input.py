"""US-3.4: As a user, I want empty and non-finite volume arguments rejected
with an error instead of reading out of bounds or reaching the player."""

import pytest


async def test_empty_volume_is_rejected(playerctl, mpris_factory):
    # audit: playerctl-cli.c:499 strlen("") - 1 wraps and volume[last] reads
    # out of bounds
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    result = await playerctl.run("-p commands volume ''")

    assert result.returncode == 1, result.stderr
    assert 'could not parse volume as a number' in result.stderr
    assert mpris.volume == 0.5


@pytest.mark.parametrize('arg', ['nan', 'inf', '-inf', 'nan+', 'inf-'])
async def test_non_finite_volume_is_rejected(arg, playerctl, mpris_factory):
    # audit: playerctl-cli.c strtod accepts nan/inf and sends them to the player
    [mpris] = await mpris_factory('commands')
    mpris.volume = 0.5

    result = await playerctl.run(f'-p commands volume -- {arg}')

    assert result.returncode == 1, result.stderr
    assert mpris.volume == 0.5

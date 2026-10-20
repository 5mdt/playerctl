"""US-2.5: As a user, I want positions that do not fit a 64-bit microsecond
count rejected with an error."""

import pytest


@pytest.mark.parametrize(
    'arg', ['1e300', '-1e300', 'nan', 'inf', '-inf', '1e300+', '1e300-']
)
async def test_out_of_range_position_is_rejected(
    arg, playerctl, mpris_factory
):
    # audit: playerctl-cli.c:402 double -> gint64 cast is undefined behaviour
    [mpris] = await mpris_factory('seeker')
    await mpris.set_artist_title('artist', 'title')

    result = await playerctl.run(f'-p seeker position -- {arg}')

    assert result.returncode == 1, result.stderr
    assert mpris.seek_called_with is None
    assert mpris.set_position_called_with is None

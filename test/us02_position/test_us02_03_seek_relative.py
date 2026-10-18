"""US-2.3: As a user, I want `position 10+` / `10-` to seek relative to the
current position (requires `CanSeek`)."""

import pytest


@pytest.mark.parametrize(
    'arg, expected',
    [
        ('10+', 10000000),
        ('10-', -10000000),
        ('2.5+', 2500000),
        ('0.5-', -500000),
    ],
)
async def test_seek_relative(arg, expected, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')

    result = await playerctl.run(f'-p seeker position {arg}')

    assert result.returncode == 0, result.stderr
    assert mpris.seek_called_with == expected
    assert mpris.set_position_called_with is None


@pytest.mark.parametrize('arg', ['10+', '10-'])
async def test_seek_skipped_when_cannot_seek(arg, playerctl, mpris_factory):
    [mpris] = await mpris_factory('seeker')
    await mpris.emit_properties(can_seek=False)

    result = await playerctl.run(f'-p seeker position {arg}')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert mpris.seek_called_with is None


async def test_seek_falls_back_to_seekable_player(playerctl, mpris_factory):
    [fixed, seekable] = await mpris_factory('a_fixed', 'b_seekable')
    await fixed.emit_properties(can_seek=False)

    result = await playerctl.run('position 5+')

    assert result.returncode == 0, result.stderr
    assert fixed.seek_called_with is None
    assert seekable.seek_called_with == 5000000

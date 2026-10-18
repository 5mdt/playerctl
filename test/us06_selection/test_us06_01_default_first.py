"""US-6.1: As a user, I want playerctl to act on the first available player by
default."""

from ..helpers.mpris import was_called


async def test_single_player_is_used(playerctl, mpris_factory):
    [mpris] = await mpris_factory('only')

    result = await playerctl.run('play')

    assert result.returncode == 0, result.stderr
    assert was_called(mpris, 'play')


async def test_acts_on_exactly_one_player(playerctl, mpris_factory):
    mprises = await mpris_factory('first1', 'first2', 'first3')

    result = await playerctl.run('play')

    assert result.returncode == 0, result.stderr
    assert sum(was_called(m, 'play') for m in mprises) == 1


async def test_acted_player_is_first_in_list_all(playerctl, mpris_factory):
    await mpris_factory('first1', 'first2', 'first3')

    listed = await playerctl.list()
    result = await playerctl.run('status --format "{{playerInstance}}"')

    assert result.returncode == 0, result.stderr
    assert result.stdout == listed[0]

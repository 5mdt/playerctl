"""US-8.9: As a bar author, I want `-F` to honour `-i/--ignore-player` and the
`-p` selection for players that appear later."""

import pytest

from ..helpers.follow import expect_no_line, follow_cmd, next_line


@pytest.mark.parametrize('flag', ['-i', '--ignore-player'])
async def test_ignored_player_changes_do_not_print(
    flag, playerctl, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist', 'title')
    cmd = follow_cmd().replace('metadata', f'{flag} test2 metadata', 1)
    proc = await playerctl.start(cmd)
    assert await next_line(proc) == 'test1: artist - title'

    await mpris2.set_artist_title('artist2', 'title2')
    await expect_no_line(proc)

    await mpris1.set_artist_title('artist3', 'title3')
    assert await next_line(proc) == 'test1: artist3 - title3'


async def test_ignored_player_appearing_later(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd(ignore='test2'))
    assert await next_line(proc) == 'test1: artist - title'

    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title2')
    await expect_no_line(proc)


async def test_unselected_player_appearing_later(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd('test1'))
    assert await next_line(proc) == 'test1: artist - title'

    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title2')
    await expect_no_line(proc)

    [mpris3] = await mpris_factory('test1x')
    await mpris3.set_artist_title('artist3', 'title3')
    await expect_no_line(proc)


async def test_ignore_all_leaves_nothing_to_follow(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(follow_cmd(ignore='%any'))
    await expect_no_line(proc)
    await mpris1.set_artist_title('artist2', 'title2')
    await expect_no_line(proc)
    assert proc.running()

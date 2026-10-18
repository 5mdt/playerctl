"""US-8.11: As a bar author, I want follow mode to keep the `-p` priority
order (instances, `%any`) while players update, appear and vanish, and to fall
back to most-recently-updated with `-a`."""

from ..helpers.follow import expect_no_line, follow_cmd, lines_until, next_line


async def test_priority_player_wins_over_recent_update(
    playerctl, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist-test1', 'title')
    await mpris2.set_artist_title('artist-test2', 'title')
    proc = await playerctl.start(follow_cmd('test1,test2'))
    assert await next_line(proc) == 'test1: artist-test1 - title'

    # test2 updated last, but test1 is listed first
    await mpris2.set_artist_title('artist-test2', 'other')
    await expect_no_line(proc)

    await mpris1.set_artist_title('artist-test1', 'other')
    assert await next_line(proc) == 'test1: artist-test1 - other'


async def test_lower_priority_player_appearing_does_not_take_over(
    playerctl, mpris_factory
):
    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title')
    proc = await playerctl.start(follow_cmd('test2,test1'))
    assert await next_line(proc) == 'test2: artist2 - title'

    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    await expect_no_line(proc)

    # and when the preferred one leaves, the other one is shown
    await mpris2.disconnect()
    assert await next_line(proc) == 'test1: artist1 - title'


async def test_higher_priority_player_appearing_takes_over(
    playerctl, mpris_factory
):
    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title')
    proc = await playerctl.start(follow_cmd('test1,test2'))
    assert await next_line(proc) == 'test2: artist2 - title'

    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    await lines_until(proc, 'test1: artist1 - title')


async def test_any_placeholder_ranks_the_rest(playerctl, mpris_factory):
    [mpris1, mpris2, mpris3] = await mpris_factory('test1', 'test2', 'test3')
    for i, mpris in enumerate((mpris1, mpris2, mpris3), 1):
        await mpris.set_artist_title(f'artist{i}', 'title')
    proc = await playerctl.start(follow_cmd('test1,%any,test3'))
    assert await next_line(proc) == 'test1: artist1 - title'

    await mpris1.disconnect()
    # test3 is listed after %any, so it ranks last
    assert await next_line(proc) == 'test2: artist2 - title'
    await mpris2.disconnect()
    assert await next_line(proc) == 'test3: artist3 - title'


async def test_any_placeholder_first_puts_listed_player_last(
    playerctl, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist1', 'title')
    await mpris2.set_artist_title('artist2', 'title')
    proc = await playerctl.start(follow_cmd('%any,test1'))
    assert await next_line(proc) == 'test2: artist2 - title'

    await mpris2.disconnect()
    assert await next_line(proc) == 'test1: artist1 - title'


async def test_instances_of_a_listed_name_share_its_rank(
    playerctl, mpris_factory
):
    [mpris1, inst1, inst2] = await mpris_factory(
        'test1', 'test1.instance1', 'test1.instance2'
    )
    await mpris1.set_artist_title('artist', 'plain')
    await inst1.set_artist_title('artist', 'one')
    await inst2.set_artist_title('artist', 'two')
    proc = await playerctl.start(follow_cmd('test1'))
    await next_line(proc)

    # same rank, so the most recently updated instance leads
    await inst1.set_artist_title('artist', 'one-b')
    await lines_until(proc, 'test1.instance1: artist - one-b')
    await inst2.set_artist_title('artist', 'two-b')
    assert await next_line(proc) == 'test1.instance2: artist - two-b'


async def test_exact_instance_ranks_above_bare_name(playerctl, mpris_factory):
    [mpris1, inst1] = await mpris_factory('test1', 'test1.instance1')
    await mpris1.set_artist_title('artist', 'plain')
    await inst1.set_artist_title('artist', 'one')
    proc = await playerctl.start(follow_cmd('test1.instance1,test1'))
    # (FAILS: `player_compare_func` ranks by the `player-name` property,
    # which has no instance suffix, so both players rank the same)
    assert await next_line(proc) == 'test1.instance1: artist - one'

    await mpris1.set_artist_title('artist', 'plain-b')
    await expect_no_line(proc)


async def test_all_players_follow_the_latest_update(playerctl, mpris_factory):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist1', 'title')
    await mpris2.set_artist_title('artist2', 'title')
    # with -a the -p order is not enforced while following
    proc = await playerctl.start(follow_cmd('test1,test2', all_players=True))
    await next_line(proc)

    await mpris2.set_artist_title('artist2', 'other')
    await lines_until(proc, 'test2: artist2 - other')
    await mpris1.set_artist_title('artist1', 'other')
    assert await next_line(proc) == 'test1: artist1 - other'


async def test_all_players_without_selection(playerctl, mpris_factory):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    await mpris1.set_artist_title('artist1', 'title')
    await mpris2.set_artist_title('artist2', 'title')
    proc = await playerctl.start(follow_cmd(all_players=True))
    await next_line(proc)

    await mpris1.set_artist_title('artist1', 'other')
    await lines_until(proc, 'test1: artist1 - other')
    await mpris2.disconnect()
    await expect_no_line(proc)
    await mpris1.disconnect()
    assert await next_line(proc) == ''


async def test_only_player_replaced_by_another(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist1', 'title')
    proc = await playerctl.start(follow_cmd())
    assert await next_line(proc) == 'test1: artist1 - title'

    [mpris2] = await mpris_factory('test2')
    await mpris2.set_artist_title('artist2', 'title')
    await lines_until(proc, 'test2: artist2 - title')
    await mpris1.disconnect()
    await expect_no_line(proc)  # test2 is still the one printed

    await mpris2.disconnect()
    assert await next_line(proc) == ''
    assert proc.running()

"""US-6.5: As a user, I want `-a/--all-players` to send the command to every
matching player."""

import asyncio

import pytest

from ..helpers.follow import follow_cmd
from ..helpers.selection import SELECTIONS


@pytest.mark.parametrize(
    ('selection', 'expected'),
    SELECTIONS.items(),
    ids=['-'.join(s) for s in SELECTIONS],
)
async def test_every_matching_player_in_priority_order(
    selection, expected, selection_players, select_many
):
    assert await select_many(*selection) == expected


async def test_follow_all_players(playerctl, mpris_factory):
    [mpris1, mpris2, mpris3, mpris4] = await mpris_factory(
        'test1', 'test2', 'test3', 'test4'
    )

    await asyncio.gather(
        *[
            mpris.set_artist_title('artist', 'title')
            for mpris in [mpris1, mpris2, mpris3, mpris4]
        ]
    )

    proc = await playerctl.start(
        follow_cmd('test3,test2,test1', all_players=True)
    )

    # player4 is ignored
    await mpris4.set_artist_title('artist', 'title')
    assert proc.queue.empty()

    # no precedence, just whoever changes metadata last
    await mpris1.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris3.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test3: artist2 - title2'

    await mpris2.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris1.set_artist_title('artist2', 'title2')
    line = await proc.queue.get()
    assert line == 'test1: artist2 - title2'

    await mpris1.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == 'test2: artist2 - title2'

    await mpris2.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == 'test3: artist2 - title2'

    await mpris3.disconnect()
    await mpris4.ping()

    line = await proc.queue.get()
    assert line == ''


@pytest.mark.parametrize(
    'command, prop, values, expected',
    [
        ('volume', 'volume', (0.25, 0.75), ['0.250000', '0.750000']),
        ('position', 'position', (1000000, 2000000), ['1.000000', '2.000000']),
        ('loop', 'loop_status', ('Track', 'Playlist'), ['Playlist', 'Track']),
        ('shuffle', 'shuffle', (True, False), ['Off', 'On']),
        (
            'status',
            'playback_status',
            ('Paused', 'Stopped'),
            ['Paused', 'Stopped'],
        ),
    ],
)
async def test_query_prints_every_player(
    command, prop, values, expected, playerctl, mpris_factory
):
    players = await mpris_factory('all1', 'all2')
    for player, value in zip(players, values):
        player.playback_status = 'Paused'  # a playing position advances
        setattr(player, prop, value)

    result = await playerctl.run(f'--all-players {command}')

    assert result.returncode == 0, result.stderr
    assert sorted(result.stdout.splitlines()) == expected


async def test_query_skips_players_without_the_property(
    playerctl, mpris_factory
):
    await mpris_factory('all1', hidden=['Volume'])
    [second] = await mpris_factory('all2')
    second.volume = 0.5

    result = await playerctl.run('--all-players volume')

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ['0.500000']


async def test_every_player_incapable(playerctl, mpris_factory):
    players = await mpris_factory('all1', 'all2', 'all3')
    for player in players:
        await player.emit_properties(can_play=False)

    result = await playerctl.run('--all-players play')

    assert result.returncode == 1
    assert not result.stdout
    assert 'No player could handle this command' in result.stderr
    assert not any(player.play_called for player in players)


async def test_every_player_missing_the_property(playerctl, mpris_factory):
    await mpris_factory('all1', 'all2', hidden=['Volume'])

    result = await playerctl.run('--all-players volume')

    assert result.returncode == 1
    assert not result.stdout
    assert 'No player could handle this command' in result.stderr


async def test_command_reaches_only_capable_players(playerctl, mpris_factory):
    first, second, third = await mpris_factory('all1', 'all2', 'all3')
    await second.emit_properties(can_play=False)

    result = await playerctl.run('--all-players play')

    assert result.returncode == 0, result.stderr
    assert (first.play_called, second.play_called, third.play_called) == (
        True,
        False,
        True,
    )

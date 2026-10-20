"""US-5.1: As a bar author, I want `metadata` to print every metadata key."""

import pytest
from dbus_next import Variant


def parse_table(stdout):
    '''Split `player key value` lines (`%-5s %-25s %s`) into tuples.'''
    rows = []
    for line in stdout.splitlines():
        player, key, value = line.split(None, 2)
        rows.append((player, key, value))
    return rows


async def test_every_key_is_printed(playerctl, mpris_factory):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {
        'mpris:trackid': Variant('o', '/track/1'),
        'mpris:length': Variant('x', 100000),
        'xesam:title': Variant('s', 'A Title'),
        'xesam:album': Variant('s', 'An Album'),
        'xesam:trackNumber': Variant('i', 7),
    }

    cmd = await playerctl.run('-p meta metadata')

    assert cmd.returncode == 0, cmd.stderr
    assert sorted(parse_table(cmd.stdout)) == sorted(
        [
            ('meta', 'mpris:trackid', '/track/1'),
            ('meta', 'mpris:length', '100000'),
            ('meta', 'xesam:title', 'A Title'),
            ('meta', 'xesam:album', 'An Album'),
            ('meta', 'xesam:trackNumber', '7'),
        ]
    )


async def test_line_format(playerctl, mpris_factory):
    '''Each line is the player name, the key and the value in columns.'''
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {'xesam:title': Variant('s', 'A Title')}

    cmd = await playerctl.run('-p meta metadata')

    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == f'{"meta":<5} {"xesam:title":<25} A Title'


async def test_list_valued_key_prints_a_line_per_item(
    playerctl, mpris_factory
):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {
        'xesam:title': Variant('s', 'A Title'),
        'xesam:artist': Variant('as', ['First', 'Second']),
    }

    cmd = await playerctl.run('-p meta metadata')

    assert cmd.returncode == 0, cmd.stderr
    rows = parse_table(cmd.stdout)
    assert ('meta', 'xesam:artist', 'First') in rows
    assert ('meta', 'xesam:artist', 'Second') in rows
    assert ('meta', 'xesam:title', 'A Title') in rows
    assert len(rows) == 3


async def test_value_with_spaces_kept_whole(playerctl, mpris_factory):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {'xesam:title': Variant('s', 'Many words in a title')}

    cmd = await playerctl.run('-p meta metadata')

    assert parse_table(cmd.stdout) == [
        ('meta', 'xesam:title', 'Many words in a title')
    ]


async def test_each_player_prints_its_own_keys(playerctl, mpris_factory):
    first, second = await mpris_factory('one', 'two')
    first.metadata = {'xesam:title': Variant('s', 'Song One')}
    second.metadata = {'xesam:title': Variant('s', 'Song Two')}

    cmd = await playerctl.run('--all-players metadata')

    assert cmd.returncode == 0, cmd.stderr
    assert sorted(parse_table(cmd.stdout)) == [
        ('one', 'xesam:title', 'Song One'),
        ('two', 'xesam:title', 'Song Two'),
    ]


async def test_no_metadata_prints_nothing(playerctl, mpris_factory):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {}

    cmd = await playerctl.run('-p meta metadata')

    assert cmd.stdout == ''


@pytest.mark.parametrize('args', ['', 'artist', 'xesam:title'])
async def test_skipped_when_cannot_play(args, playerctl, mpris_factory):
    [mpris] = await mpris_factory('meta')
    await mpris.set_artist_title('artist', 'title')
    await mpris.emit_properties(can_play=False)

    cmd = await playerctl.run(f'-p meta metadata {args}')

    assert cmd.returncode == 1
    assert not cmd.stdout
    assert 'No player could handle this command' in cmd.stderr


async def test_cannot_play_falls_back_to_next_player(playerctl, mpris_factory):
    first, second = await mpris_factory('meta1', 'meta2')
    await first.set_artist_title('artist1', 'title1')
    await second.set_artist_title('artist2', 'title2')
    await first.emit_properties(can_play=False)

    cmd = await playerctl.run('metadata title')

    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == 'title2'


async def test_format_with_empty_metadata_prints_nothing(
    playerctl, mpris_factory
):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {}

    cmd = await playerctl.run("-p meta metadata --format '{{title}}'")

    assert cmd.stdout == ''

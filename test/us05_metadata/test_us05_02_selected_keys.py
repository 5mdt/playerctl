"""US-5.2: As a bar author, I want `metadata artist title album` or any raw key
(such as `mpris:length`) to print only those values."""

import pytest
from dbus_next import Variant


@pytest.fixture()
async def meta_player(mpris_factory):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {
        'mpris:trackid': Variant('o', '/track/1'),
        'mpris:length': Variant('x', 100000),
        'xesam:title': Variant('s', 'A Title'),
        'xesam:artist': Variant('as', ['First', 'Second']),
        'xesam:album': Variant('s', 'An Album'),
    }
    return mpris


@pytest.mark.parametrize(
    'key, expected',
    [
        ('artist', 'First, Second'),
        ('title', 'A Title'),
        ('album', 'An Album'),
        ('xesam:title', 'A Title'),
        ('xesam:artist', 'First, Second'),
        ('mpris:length', '100000'),
        ('mpris:trackid', '/track/1'),
    ],
)
async def test_single_key(key, expected, playerctl, meta_player):
    cmd = await playerctl.run(f'-p meta metadata {key}')

    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == expected, cmd.stderr


async def test_multiple_keys_in_requested_order(playerctl, meta_player):
    cmd = await playerctl.run('-p meta metadata title album artist')

    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout.splitlines() == [
        'A Title',
        'An Album',
        'First, Second',
    ]


async def test_multiple_keys_reversed_order(playerctl, meta_player):
    cmd = await playerctl.run('-p meta metadata mpris:length artist')

    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout.splitlines() == ['100000', 'First, Second']


async def test_unselected_keys_are_not_printed(playerctl, meta_player):
    cmd = await playerctl.run('-p meta metadata title')

    assert 'Album' not in cmd.stdout
    assert 'First' not in cmd.stdout


async def test_missing_key_prints_nothing(playerctl, meta_player):
    cmd = await playerctl.run('-p meta metadata xesam:nonexistent')

    assert cmd.stdout == ''


async def test_missing_shortcut_prints_nothing(playerctl, mpris_factory):
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {'xesam:title': Variant('s', 'A Title')}

    cmd = await playerctl.run('-p meta metadata album')

    assert cmd.stdout == ''


async def test_missing_key_among_present_ones(playerctl, mpris_factory):
    '''Keys the player does have are still printed.'''
    [mpris] = await mpris_factory('meta')
    mpris.metadata = {'xesam:title': Variant('s', 'A Title')}

    cmd = await playerctl.run('-p meta metadata title album')

    assert 'A Title' in cmd.stdout.splitlines()

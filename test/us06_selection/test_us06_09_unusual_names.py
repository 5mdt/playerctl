"""US-6.9: As a user, I want players with unusual bus names (dashes,
underscores, dots, digits, instance suffixes) to be listed and selectable."""

import pytest

NAMES = [
    'my-player',
    'my_player',
    'Player42',
    'dotted.name.here',
    'vlc.instance1234',
    'vlc.instancenotanumber',
    'x',
    'a' * 100,
]


async def test_list_all_unusual_names(playerctl, mpris_factory):
    await mpris_factory(*NAMES)

    result = await playerctl.run('--list-all')

    assert result.returncode == 0, result.stderr
    assert sorted(result.stdout.splitlines()) == sorted(NAMES)


@pytest.mark.parametrize('name', NAMES)
async def test_select_unusual_name(name, playerctl, mpris_factory):
    [mpris] = await mpris_factory(name)
    other = await mpris_factory('other')
    await other[0].set_artist_title('other', 'title')
    await mpris.set_artist_title('wanted', 'title')

    result = await playerctl.run(f'-p {name} metadata artist')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'wanted'


async def test_list_all_ignoring_unusual_names(playerctl, mpris_factory):
    await mpris_factory('my-player', 'my_player', 'plain')

    result = await playerctl.run('-l -i my-player,my_player')

    assert result.stdout.splitlines() == ['plain']


async def test_instance_selected_by_base_name(playerctl, mpris_factory):
    await mpris_factory('vlc.instance1234', 'vlc.instancenotanumber')

    result = await playerctl.run('-l -p vlc')

    assert sorted(result.stdout.splitlines()) == [
        'vlc.instance1234',
        'vlc.instancenotanumber',
    ]

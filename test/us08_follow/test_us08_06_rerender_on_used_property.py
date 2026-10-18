"""US-8.6: As a bar author, I want the template re-rendered when any property it
uses changes."""

import pytest

from ..helpers.follow import expect_no_line, next_line

TEMPLATE = '{{status}} {{volume}} {{artist}}'


async def test_rerender_when_used_property_changes(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(f'metadata --format "{TEMPLATE}" --follow')
    assert await next_line(proc) == 'Playing 1.0 artist'

    await mpris1.emit_properties(playback_status='Paused')
    assert await next_line(proc) == 'Paused 1.0 artist'

    await mpris1.emit_properties(volume=0.5)
    assert await next_line(proc) == 'Paused 0.5 artist'

    await mpris1.set_artist_title('artist2', 'title')
    assert await next_line(proc) == 'Paused 0.5 artist2'


@pytest.mark.parametrize(
    'command,props,expected',
    [
        ('status', {'volume': 0.5}, 'Playing 0.5'),
        ('volume', {'playback_status': 'Paused'}, 'Paused 1.0'),
        ('loop', {'playback_status': 'Paused'}, 'Paused 1.0'),
        ('shuffle', {'volume': 0.5}, 'Playing 0.5'),
    ],
)
async def test_rerender_from_other_command(
    command, props, expected, playerctl, mpris_factory
):
    '''The template re-renders for properties of other commands it uses.'''
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    template = '{{status}} {{volume}}'
    proc = await playerctl.start(f'{command} --format "{template}" --follow')
    assert await next_line(proc) == 'Playing 1.0'

    await mpris1.emit_properties(**props)
    assert await next_line(proc) == expected


async def test_unused_property_does_not_rerender(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start('status --format "{{status}}" --follow')
    assert await next_line(proc) == 'Playing'

    await mpris1.emit_properties(volume=0.3)
    await expect_no_line(proc)


async def test_rerender_on_seeked_when_position_used(playerctl, mpris_factory):
    '''`position` in another command's template follows `Seeked`.'''
    [mpris1] = await mpris_factory('test1')
    mpris1.playback_status = 'Paused'  # a playing position advances
    mpris1.position = 0
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        'status --format "{{status}} {{position}}" --follow'
    )
    assert await next_line(proc) == 'Paused 0'

    mpris1.position = 5000000
    mpris1.seeked_value = 5000000
    mpris1.Seeked()
    await mpris1.ping()
    assert await next_line(proc) == 'Paused 5000000'


async def test_seeked_ignored_when_position_unused(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start('status --format "{{status}}" --follow')
    assert await next_line(proc) == 'Playing'

    mpris1.seeked_value = 5000000
    mpris1.Seeked()
    await mpris1.ping()
    await expect_no_line(proc)

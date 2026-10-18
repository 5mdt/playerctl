"""US-4.1: As a bar author, I want `status` to print `Playing`, `Paused` or
`Stopped`."""

import pytest


@pytest.mark.parametrize('status', ['Playing', 'Paused', 'Stopped'])
async def test_status_query(status, playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.playback_status = status

    query = await playerctl.run('-p queries status')

    assert query.returncode == 0, query.stderr
    assert query.stdout == status, query.stderr


async def test_status_skipped_when_player_has_no_status(
    playerctl, mpris_factory
):
    await mpris_factory('queries', hidden=['PlaybackStatus'])

    query = await playerctl.run('-p queries status')

    assert query.returncode == 1
    assert not query.stdout
    assert 'No player could handle this command' in query.stderr


async def test_status_with_format(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.playback_status = 'Paused'

    query = await playerctl.run("-p queries status -f '[{{status}}]'")

    assert query.returncode == 0, query.stderr
    assert query.stdout == '[Paused]'


async def test_status_format_without_metadata_variables_is_empty(
    playerctl, mpris_factory
):
    '''`status` renders its template without metadata, so `title` is empty.'''
    [mpris] = await mpris_factory('queries')
    await mpris.set_artist_title('artist', 'title')

    query = await playerctl.run("-p queries status -f '{{title}}'")

    assert query.returncode == 0, query.stderr
    assert query.stdout == ''

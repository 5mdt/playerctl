"""US-2.1: As a user, I want `position` to print the current position in
seconds."""

import math


async def test_position_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.position = 2500000

    query = await playerctl.run('position')

    assert math.fabs(float(query.stdout) * 1000000 - mpris.position) < 100, (
        query.stderr
    )


async def test_position_with_format(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.playback_status = 'Paused'  # a playing position advances
    mpris.position = 12500000

    query = await playerctl.run(
        "-p queries position --format '{{position / 1000000}}s'"
    )

    assert query.returncode == 0, query.stderr
    assert query.stdout == '12.5s'


async def test_position_skipped_when_player_has_no_position(
    playerctl, mpris_factory
):
    await mpris_factory('queries', hidden=['Position'])

    query = await playerctl.run('-p queries position')

    assert query.returncode == 1
    assert not query.stdout
    assert 'No player could handle this command' in query.stderr


async def test_position_falls_back_to_player_with_position(
    playerctl, mpris_factory
):
    await mpris_factory('queries1', hidden=['Position'])
    [second] = await mpris_factory('queries2')
    second.playback_status = 'Paused'  # a playing position advances
    second.position = 3000000

    query = await playerctl.run('position')

    assert query.returncode == 0, query.stderr
    assert float(query.stdout) == 3.0

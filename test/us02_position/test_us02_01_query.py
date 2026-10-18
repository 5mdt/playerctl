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

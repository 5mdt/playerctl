"""US-3.1: As a user, I want `volume` to print the level (0.0-1.0)."""


async def test_volume_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('volume')

    assert float(query.stdout) == mpris.volume, query.stderr

"""US-3.1: As a user, I want `volume` to print the level (0.0-1.0)."""


async def test_volume_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('volume')

    assert float(query.stdout) == mpris.volume, query.stderr


async def test_volume_with_format(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')
    mpris.volume = 0.25

    query = await playerctl.run("-p queries volume --format 'vol={{volume}}'")

    assert query.returncode == 0, query.stderr
    assert query.stdout == 'vol=0.25'


async def test_volume_skipped_when_player_has_no_volume(
    playerctl, mpris_factory
):
    await mpris_factory('queries', hidden=['Volume'])

    query = await playerctl.run('-p queries volume')

    assert query.returncode == 1
    assert not query.stdout
    assert 'No player could handle this command' in query.stderr


async def test_volume_falls_back_to_player_with_volume(
    playerctl, mpris_factory
):
    await mpris_factory('queries1', hidden=['Volume'])
    [second] = await mpris_factory('queries2')
    second.volume = 0.5

    query = await playerctl.run('volume')

    assert query.returncode == 0, query.stderr
    assert float(query.stdout) == 0.5

"""US-4.1: As a bar author, I want `status` to print `Playing`, `Paused` or
`Stopped`."""


async def test_status_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('status')

    assert query.stdout == mpris.playback_status, query.stderr

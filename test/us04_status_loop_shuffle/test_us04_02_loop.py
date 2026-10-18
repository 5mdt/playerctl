"""US-4.2: As a user, I want `loop` to print the loop status and
`loop None|Track|Playlist` to set it."""


async def test_loop_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('loop')

    assert query.stdout == mpris.loop_status, query.stderr


async def test_loop_set(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.loop_status = 'Track'

    result = await playerctl.run('-p commands loop playlist')

    assert result.returncode == 0, result.stderr
    assert mpris.loop_status == 'Playlist'

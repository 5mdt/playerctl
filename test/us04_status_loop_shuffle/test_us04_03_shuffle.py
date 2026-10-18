"""US-4.3: As a user, I want `shuffle` to print `On`/`Off` and
`shuffle on|off|toggle` to set it (case-insensitive)."""


async def test_shuffle_query(playerctl, mpris_factory):
    [mpris] = await mpris_factory('queries')

    query = await playerctl.run('shuffle')

    assert query.stdout == ('On' if mpris.shuffle else 'Off'), query.stderr


async def test_shuffle_on(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = False

    result = await playerctl.run('-p commands shuffle on')

    assert result.returncode == 0, result.stderr
    assert mpris.shuffle


async def test_shuffle_toggle(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.shuffle = True

    result = await playerctl.run('-p commands shuffle toggle')

    assert result.returncode == 0, result.stderr
    assert not mpris.shuffle

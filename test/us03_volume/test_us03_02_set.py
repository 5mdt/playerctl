"""US-3.2: As a user, I want `volume 0.5` to set the level."""


async def test_volume_set(playerctl, mpris_factory):
    [mpris] = await mpris_factory('commands')
    mpris.volume = 1.0

    result = await playerctl.run('-p commands volume 0.8')

    assert result.returncode == 0, result.stderr
    assert mpris.volume == 0.8

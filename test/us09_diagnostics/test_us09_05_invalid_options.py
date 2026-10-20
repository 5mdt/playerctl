"""US-9.5: As a scripter, I want an unknown option or an option missing its
value to fail with an error message and exit code 1."""

import pytest


@pytest.mark.parametrize('option', ['--bogus', '-x', '--bogus=1'])
async def test_unknown_option(option, playerctl, mpris_factory):
    [mpris] = await mpris_factory('opts')

    result = await playerctl.run(f'{option} play')

    assert result.returncode == 1
    assert not result.stdout
    assert 'Unknown option' in result.stderr
    assert not mpris.play_called


@pytest.mark.parametrize(
    'option',
    ['-p', '--player', '-i', '--ignore-player', '-f', '--format'],
)
async def test_option_missing_its_value(option, playerctl, mpris_factory):
    await mpris_factory('opts')

    result = await playerctl.run(option)

    assert result.returncode == 1
    assert not result.stdout
    assert 'Missing argument' in result.stderr


async def test_unknown_option_is_reported_with_no_messages(
    playerctl, mpris_factory
):
    '''`-s` only silences the player diagnostics, not usage errors.'''
    await mpris_factory('opts')

    result = await playerctl.run('-s --bogus play')

    assert result.returncode == 1
    assert 'Unknown option' in result.stderr

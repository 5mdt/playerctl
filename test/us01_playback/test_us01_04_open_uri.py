"""US-1.4: As a user, I want `open URI` to open a local file (converted to
`file://`) or a remote URL."""

import pytest


async def test_local_path_becomes_file_uri(playerctl, mpris_factory, tmp_path):
    [mpris] = await mpris_factory('opener')
    song = tmp_path / 'song.mp3'
    song.write_bytes(b'')

    result = await playerctl.run(f'-p opener open {song}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == song.as_uri()


async def test_local_path_with_spaces_is_escaped(
    playerctl, mpris_factory, tmp_path
):
    [mpris] = await mpris_factory('opener')
    song = tmp_path / 'my song.mp3'
    song.write_bytes(b'')

    result = await playerctl.run(f"-p opener open '{song}'")

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == song.as_uri()
    assert '%20' in mpris.open_uri_called_with


@pytest.mark.parametrize(
    'uri',
    ['https://example.com/stream.mp3', 'spotify:track:abc123'],
)
async def test_remote_uri_passed_as_is(uri, playerctl, mpris_factory):
    [mpris] = await mpris_factory('opener')

    result = await playerctl.run(f'-p opener open {uri}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == uri


async def test_existing_file_uri_passed_as_is(
    playerctl, mpris_factory, tmp_path
):
    [mpris] = await mpris_factory('opener')
    song = tmp_path / 'song.mp3'
    song.write_bytes(b'')

    result = await playerctl.run(f'-p opener open {song.as_uri()}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == song.as_uri()


async def test_missing_path_passed_as_is(playerctl, mpris_factory, tmp_path):
    [mpris] = await mpris_factory('opener')
    missing = str(tmp_path / 'nope.mp3')

    result = await playerctl.run(f'-p opener open {missing}')

    assert result.returncode == 0, result.stderr
    assert mpris.open_uri_called_with == missing


async def test_skipped_when_cannot_control(playerctl, mpris_factory):
    [mpris] = await mpris_factory('opener')
    await mpris.emit_properties(can_control=False)

    result = await playerctl.run('-p opener open https://example.com/a.mp3')

    assert result.returncode == 1
    assert 'No player could handle this command' in result.stderr
    assert mpris.open_uri_called_with is None


async def test_open_without_uri_does_nothing(playerctl, mpris_factory):
    [mpris] = await mpris_factory('opener')

    result = await playerctl.run('-p opener open')

    assert result.returncode in (0, 1)
    assert not result.stdout
    assert mpris.open_uri_called_with is None

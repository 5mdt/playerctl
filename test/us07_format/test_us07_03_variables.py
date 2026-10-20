"""US-7.3: As a bar author, I want template variables: raw metadata keys
(`mpris:length`), shortcuts `artist`/`title`/`album`, plus `playerName`,
`playerInstance`, `status`, `loop`, `shuffle`, `volume`, `position`."""

from ..helpers.format import PLAYER_INSTANCE, PLAYER_NAME


async def test_variables(metadata_test):
    metadata_test.add('{{mpris:length}}', '100000')
    metadata_test.add(
        '{{playerName}} - {{playerInstance}}',
        f'{PLAYER_NAME} - {PLAYER_INSTANCE}',
    )

    await metadata_test.run()


async def test_loop(metadata_test, format_player):
    for status in ('None', 'Track', 'Playlist'):
        format_player.loop_status = status
        await format_player.ping()
        metadata_test.tests.clear()
        metadata_test.add('{{loop}}', status)
        await metadata_test.run()


async def test_shuffle(metadata_test, format_player):
    for shuffle, expected in ((True, 'true'), (False, 'false')):
        format_player.shuffle = shuffle
        await format_player.ping()
        metadata_test.tests.clear()
        metadata_test.add('{{shuffle}}', expected)
        await metadata_test.run()


async def test_position(metadata_test, format_player):
    # position is reported in microseconds
    format_player.playback_status = 'Paused'  # a playing position advances
    format_player.position = 12500000
    await format_player.ping()
    metadata_test.add('{{position}}', '12500000')
    metadata_test.add('{{position / 1000000}}', '12.5')

    await metadata_test.run()

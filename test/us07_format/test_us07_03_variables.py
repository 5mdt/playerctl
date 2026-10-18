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

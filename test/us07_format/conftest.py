import pytest
from dbus_next import Variant

from ..helpers.format import (
    ALBUM,
    ARTIST,
    PLAYER_INSTANCE,
    TITLE,
    VOLUME,
    NUMERIC_METADATA,
    MetadataTest,
)


@pytest.fixture()
async def format_player(mpris_factory):
    '''A mock player with the fixed metadata the format tests expect.'''
    [mpris] = await mpris_factory(PLAYER_INSTANCE)
    mpris.metadata = {
        'xesam:title': Variant('s', TITLE),
        'xesam:artist': Variant('as', [ARTIST]),
        'xesam:escapeme': Variant('s', '<hi>'),
        'xesam:album': Variant('s', ALBUM),
        'mpris:length': Variant('x', 100000),
    }
    mpris.volume = VOLUME
    return mpris


@pytest.fixture()
def metadata_test(playerctl, format_player):
    return MetadataTest(playerctl)


@pytest.fixture()
async def numeric_player(format_player):
    '''The format player plus int64/uint64/double/boolean metadata keys.'''
    metadata = dict(format_player.metadata)
    for key, (sig, value) in NUMERIC_METADATA.items():
        metadata[key] = Variant(sig, value)
    format_player.metadata = metadata
    await format_player.ping()
    return format_player

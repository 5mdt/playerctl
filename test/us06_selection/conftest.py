import pytest

from ..helpers.selection import PLAYERS, selector


@pytest.fixture()
async def selection_players(mpris_factory):
    return await mpris_factory(*PLAYERS)


@pytest.fixture()
def select(playerctl):
    return selector(playerctl)[0]


@pytest.fixture()
def select_many(playerctl):
    return selector(playerctl)[1]

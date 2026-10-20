import pytest


@pytest.fixture()
async def follow_players(mpris_factory):
    '''The four mock players test1..test4 shared by the follow scenarios.'''
    return await mpris_factory('test1', 'test2', 'test3', 'test4')

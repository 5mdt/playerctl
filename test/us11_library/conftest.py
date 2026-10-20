import pytest

from ..helpers.gi import run_gi, start_gi


@pytest.fixture()
def gi_run(bus_address):
    '''Run a PyGObject snippet against the test bus; skipped without PyGObject.'''
    pytest.importorskip('gi')

    async def run(body, env=None):
        return await run_gi(bus_address, body, env)

    return run


@pytest.fixture()
def gi_start(bus_address):
    '''Start a long-running PyGObject snippet; skipped without PyGObject.'''
    pytest.importorskip('gi')

    async def start(body, env=None):
        return await start_gi(bus_address, body, env)

    return start

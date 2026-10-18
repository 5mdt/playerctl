import asyncio

import pytest
from .playerctl import stop_all


@pytest.fixture(autouse=True)
async def cleanup_processes():
    yield
    await stop_all()


@pytest.fixture()
async def bus_address():
    proc = await asyncio.create_subprocess_exec(
        'dbus-daemon',
        '--session',
        '--nofork',
        '--print-address=1',
        stdout=asyncio.subprocess.PIPE,
    )
    address = (await proc.stdout.readline()).decode().strip()
    assert address

    yield address

    if proc.returncode is None:
        proc.terminate()
    await proc.wait()

"""US-9.8: As a scripter, I want `open ''` rejected instead of opening the
current directory, and I want a failed write to stdout (disk full, closed
pipe target) to make playerctl exit with 1 instead of reporting success.

Both are known defects, kept as strict xfails (see build/qa/bugs-cli.md)."""

import pytest

from ..helpers.cli_fuzz import prepared, run


@pytest.mark.xfail(
    strict=True,
    reason='BUG-C1: `open ""` goes through g_file_new_for_commandline_arg, '
    'which maps "" to the cwd, so OpenUri(file://<cwd>) is sent '
    '(playerctl-cli.c playercmd_open)',
)
async def test_open_empty_uri_is_rejected(playerctl, mpris_factory):
    [mpris] = await prepared(mpris_factory, 'victim')

    result = await run(playerctl, "-p victim open ''")

    assert result.returncode == 1
    assert mpris.open_uri_called_with is None


@pytest.mark.xfail(
    strict=True,
    reason='BUG-C2: output is not checked/flushed for errors, so a failed '
    'write to stdout still exits 0',
)
@pytest.mark.parametrize(
    'cmd',
    [
        '-p a status > /dev/full',
        '-p a metadata > /dev/full',
        '-l > /dev/full',
        '-v > /dev/full',
    ],
)
async def test_failed_stdout_write_exits_with_error(
    cmd, playerctl, mpris_factory
):
    [mpris] = await prepared(mpris_factory, 'a')

    result = await run(playerctl, cmd)

    assert result.returncode == 1

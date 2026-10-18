"""US-8.8: As a bar author, I want a template that fails while rendering
during `-F` to stop follow mode with exit code 1."""

import asyncio

from ..helpers.follow import next_line


async def _expect_failure(
    proc, timeout=3, message='Error while executing command'
):
    await asyncio.wait_for(proc.proc.wait(), timeout)
    stderr = (await proc.proc.stderr.read()).decode()
    assert proc.proc.returncode == 1, stderr
    assert message in stderr
    return stderr


async def test_error_on_property_change(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        'status --format "{{ 10 / volume }}" --follow'
    )
    assert await next_line(proc) == '10.0'

    # dividing by zero only fails once the volume changes
    await mpris1.emit_properties(volume=0.0)
    stderr = await _expect_failure(proc)
    assert 'Divide by zero' in stderr
    assert proc.queue.empty()


async def test_position_tick_reports_error_from_property_change(
    playerctl, mpris_factory
):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        'status --format "{{ duration(position) }} {{ 10 / volume }}" --follow'
    )
    assert await next_line(proc) == '0:00 10.0'

    # the change callback swallows the error, but the template uses
    # `position`, so the one-second tick renders it again and fails
    await mpris1.emit_properties(volume=0.0)
    stderr = await _expect_failure(proc, timeout=3)
    assert 'Divide by zero' in stderr
    assert proc.queue.empty()


async def test_error_for_player_that_appears(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        'status --format "{{ 10 / volume }}" --follow'
    )
    assert await next_line(proc) == '10.0'

    # the new player is the first one asked, and its template fails
    await mpris_factory(
        'test2', prepare=lambda player: setattr(player, 'volume', 0.0)
    )
    stderr = await _expect_failure(proc, message='Could not execute command')
    assert 'Divide by zero' in stderr


async def test_error_for_player_left_after_one_vanishes(
    playerctl, mpris_factory
):
    [mpris1, mpris2] = await mpris_factory('test1', 'test2')
    mpris1.volume = 0.5
    mpris2.volume = 0.0
    await mpris2.set_artist_title('artist', 'title')
    await mpris1.set_artist_title('artist', 'title')
    proc = await playerctl.start(
        '-p test1,test2 status --format "{{ 10 / volume }}" --follow'
    )
    assert await next_line(proc) == '20.0'

    # test2 is next in line and cannot be rendered
    await mpris1.disconnect()
    stderr = await _expect_failure(proc, message='Could not execute command')
    assert 'Divide by zero' in stderr


async def test_error_for_player_present_at_start(playerctl, mpris_factory):
    [mpris1] = await mpris_factory('test1')
    mpris1.volume = 0.0
    await mpris1.set_artist_title('artist', 'title')

    proc = await playerctl.start(
        'status --format "{{ 10 / volume }}" --follow'
    )

    stderr = await _expect_failure(proc, message='Connection to player failed')
    assert 'Divide by zero' in stderr

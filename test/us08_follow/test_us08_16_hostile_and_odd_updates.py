"""US-8.16: As a bar author, I want follow mode to render hostile metadata
verbatim and to ignore updates that do not change what I asked for
(other interfaces, empty updates, invalidated-only updates, Seeked) while
still reacting to rapid status flips, re-registered names and players taking
turns."""

import asyncio

import pytest
from dbus_next.service import Variant

from ..helpers.chaos import (
    assert_clean_stderr,
    emit_title,
    no_consecutive_duplicates,
    raw_properties_changed,
    start_raw,
)
from ..helpers.mpris import ROOT_INTERFACE

FMT = '{{playerInstance}}: {{artist}} - {{title}}'
CMD = f'metadata --format "{FMT}" --follow'


async def finish(proc):
    code, stderr = await proc.terminate()
    assert code in (-15, 0), (code, stderr)
    assert_clean_stderr(stderr)


@pytest.mark.parametrize(
    'title',
    [
        pytest.param('x' * (1024 * 1024), id='1MB'),
        pytest.param('é中\U0001f3b5 ‮ rtl ́', id='unicode'),
        pytest.param('\x1b[31mred\x1b[0m\x1b]0;pwn\x07', id='ansi'),
        pytest.param('{{title}} {{ 1/0 }} %s %n', id='template-like'),
        pytest.param('tab\there', id='tab'),
        pytest.param('a' * 70000, id='single-70k'),
        pytest.param(' ' * 10, id='spaces'),
    ],
)
async def test_hostile_title_rendered_verbatim(
    playerctl, mpris_factory, title
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - start')

    await p.set_artist_title('artist', title)
    expected = f'test1: artist - {title}'
    # the reader strips only the newline, so compare the raw bytes
    await proc.wait_for(
        lambda ls: any(
            line == expected.rstrip() or line == expected for line in ls
        ),
        timeout=4,
        what='hostile line',
    )
    await proc.settle()
    assert proc.running()
    await finish(proc)


async def test_hostile_title_with_newline_prints_both_lines(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'start')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - start')
    await p.set_artist_title('artist', 'line1\nline2')
    await proc.wait_line('line2')
    assert b'test1: artist - line1\nline2\n' in proc.buf
    await finish(proc)


async def test_hostile_artist_through_json_and_markup_helpers(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a"<b>&\\ ', 'start')
    proc = await start_raw(
        playerctl,
        'metadata --format "{{markup_escape(artist)}}|{{artist}}" --follow',
    )
    await proc.wait_line('a&quot;&lt;b&gt;&amp;\\ |a"<b>&\\ ')
    await finish(proc)


async def test_empty_properties_changed_prints_nothing(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'title')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - title')
    for _ in range(50):
        await raw_properties_changed(p, {})
    await p.ping()
    assert await proc.settle() == ['test1: artist - title']
    await finish(proc)


async def test_properties_changed_for_other_interface_is_ignored(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'title')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - title')

    other = {
        'Metadata': Variant('a{sv}', {'xesam:title': Variant('s', 'evil')})
    }
    await raw_properties_changed(p, other, interface=ROOT_INTERFACE)
    await raw_properties_changed(p, other, interface='org.example.Other')
    await raw_properties_changed(
        p, {'Identity': Variant('s', 'x')}, ['Identity'], ROOT_INTERFACE
    )
    await raw_properties_changed(
        p, {}, ['Metadata'], interface='org.example.Other'
    )
    await p.ping()
    assert await proc.settle() == ['test1: artist - title']
    await finish(proc)


async def test_unknown_property_in_player_update_is_ignored(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'title')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - title')
    await raw_properties_changed(
        p, {'NoSuchProperty': Variant('s', 'x')}, ['AlsoNotAProperty', '']
    )
    await p.ping()
    assert await proc.settle() == ['test1: artist - title']
    await finish(proc)


async def test_invalidated_only_update_rereads_property(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('artist', 'old')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: artist - old')

    # the new value is only reachable through a Get after the invalidation
    p.metadata = {
        'xesam:title': Variant('s', 'fresh'),
        'xesam:artist': Variant('as', ['artist']),
        'mpris:trackid': Variant('o', '/99'),
    }
    await raw_properties_changed(p, {}, ['Metadata'])
    await p.ping()
    await proc.wait_line('test1: artist - fresh')
    await finish(proc)


async def test_invalidated_status_only_update(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    proc = await start_raw(playerctl, 'status --follow')
    await proc.wait_line('Playing')
    p.playback_status = 'Paused'
    await raw_properties_changed(p, {}, ['PlaybackStatus'])
    await p.ping()
    await proc.wait_line('Paused')
    await finish(proc)


async def test_seeked_with_position_format(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    p.position = 0
    proc = await start_raw(playerctl, 'position --follow')
    await proc.wait_line('0.000000')
    for value in (1000000, 2000000, 3000000):
        p.seeked_value = value
        p.Seeked()
        await p.ping()
    await proc.wait_last('3.000000')
    assert no_consecutive_duplicates(proc.lines())
    await finish(proc)


async def test_seeked_storm_ends_on_last_position(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    proc = await start_raw(playerctl, 'position --follow')
    await proc.wait_line('0.000000')
    for i in range(1, 300):
        p.seeked_value = i * 1000000
        p.Seeked()
    await p.ping()
    await proc.wait_last('299.000000', timeout=4)
    assert no_consecutive_duplicates(await proc.settle())
    await finish(proc)


async def test_seeked_to_same_position_prints_once(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    p.playback_status = 'Paused'
    proc = await start_raw(playerctl, 'position --follow')
    await proc.wait_line('0.000000')
    p.seeked_value = 5000000
    for _ in range(20):
        p.Seeked()
    await p.ping()
    await proc.wait_line('5.000000')
    assert (await proc.settle()).count('5.000000') == 1
    await finish(proc)


async def test_status_flip_playing_stopped_playing_quickly(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    proc = await start_raw(playerctl, 'status --follow')
    await proc.wait_line('Playing')
    for _ in range(100):
        for status in ('Stopped', 'Playing'):
            p.playback_status = status
            p.emit_properties_changed({'PlaybackStatus': status})
    await p.ping()
    await asyncio.sleep(0.3)
    lines = await proc.settle()
    assert lines[0] == 'Playing'
    assert lines[-1] == 'Playing'
    assert set(lines) <= {'Playing', 'Stopped'}
    assert no_consecutive_duplicates(lines)
    await finish(proc)


async def test_status_flip_lands_on_final_state_stopped(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    proc = await start_raw(playerctl, 'status --follow')
    await proc.wait_line('Playing')
    for status in ('Paused', 'Playing', 'Paused', 'Playing', 'Stopped'):
        await p.emit_properties(playback_status=status)
    await proc.wait_last('Stopped')
    assert no_consecutive_duplicates(proc.lines())
    await finish(proc)


async def test_status_flip_with_metadata_in_one_signal(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('a', 'one')
    proc = await start_raw(
        playerctl, 'metadata --format "{{status}} {{title}}" --follow'
    )
    await proc.wait_line('Playing one')
    from ..helpers.chaos import metadata_variant

    md = metadata_variant(p, 'two')
    p.playback_status = 'Paused'
    p.emit_properties_changed({'PlaybackStatus': 'Paused', 'Metadata': md})
    await p.ping()
    await proc.wait_last('Paused two')
    await finish(proc)


async def test_reregistered_name_with_different_content(
    playerctl, mpris_factory
):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('first', 'song')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: first - song')

    for i in range(10):
        await p.disconnect()
        [p] = await mpris_factory('test1')
        await p.set_artist_title(f'gen{i}', 'song')
    await proc.wait_last('test1: gen9 - song', timeout=4)
    lines = await proc.settle()
    assert no_consecutive_duplicates(lines)
    # the vanished player may leave an empty line between generations
    assert all(line in ('',) or line.startswith('test1: ') for line in lines)
    await finish(proc)


async def test_reregistered_name_with_no_metadata(playerctl, mpris_factory):
    [p] = await mpris_factory('test1')
    await p.set_artist_title('first', 'song')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_line('test1: first - song')
    await p.disconnect()
    [p2] = await mpris_factory('test1')  # no metadata at all
    await p2.ping()
    await p2.set_artist_title('second', 'song')
    await proc.wait_last('test1: second - song')
    await finish(proc)


async def test_two_players_swap_most_recent_in_all_mode(
    playerctl, mpris_factory
):
    [a, b] = await mpris_factory('pa', 'pb')
    await a.set_artist_title('x', '0')
    await b.set_artist_title('x', '0')
    proc = await start_raw(playerctl, f'--all-players {CMD}')
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    await asyncio.sleep(0.3)
    for i in range(1, 40):
        player = a if i % 2 else b
        name = 'pa' if i % 2 else 'pb'
        await player.set_artist_title('x', str(i))
        await proc.wait_last(f'{name}: x - {i}')
    assert no_consecutive_duplicates(proc.lines())
    await finish(proc)


async def test_two_players_swap_burst_in_default_mode(
    playerctl, mpris_factory
):
    [a, b] = await mpris_factory('pa', 'pb')
    await a.set_artist_title('x', '0')
    await b.set_artist_title('x', '0')
    proc = await start_raw(playerctl, CMD)
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    await asyncio.sleep(0.3)
    for i in range(1, 200):
        await emit_title(a if i % 2 else b, str(i), artist='x')
    await a.ping()
    await b.ping()
    await proc.wait_last('pa: x - 199', timeout=4)
    assert no_consecutive_duplicates(await proc.settle())
    await finish(proc)


@pytest.mark.parametrize(
    'sel',
    [
        '--player pa',
        '--player pb,pa',
        '--ignore-player pb',
        '--player pa --all-players',
    ],
)
async def test_storms_on_unselected_players_print_nothing(
    playerctl, mpris_factory, sel
):
    [a, b] = await mpris_factory('pa', 'pb')
    await a.set_artist_title('x', 'a')
    await b.set_artist_title('x', 'b')
    proc = await start_raw(playerctl, f'{sel} {CMD}')
    await proc.wait_for(lambda ls: len(ls) >= 1, what='first line')
    first = proc.lines()[0]
    assert first.startswith('pa: ') or sel == '--player pb,pa'
    await asyncio.sleep(0.2)
    n = len(proc.lines())
    if sel != '--player pb,pa':
        for i in range(100):
            await emit_title(b, f'n{i}', artist='x')
        await b.ping()
        assert len(await proc.settle()) == n
    await finish(proc)

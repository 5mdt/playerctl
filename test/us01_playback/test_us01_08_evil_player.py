"""US-1.8: As a scripter, I want a hostile or broken player (lying `Can*`
properties, odd D-Bus errors, missing interfaces, one that dies or never
answers) to make a command fail with exit code 1 at worst: never a crash, a
hang, or GLib CRITICAL noise."""

import asyncio

import pytest
from dbus_next import Variant

from ..helpers.evil_mpris import (
    HUGE,
    INT64_MAX,
    assert_sane,
    failing,
    holding,
    run,
    send_signal,
    tamper,
)
from ..helpers.mpris import (
    PLAYER_INTERFACE,
    PROPERTIES_INTERFACE,
    MessageGate,
    setup_partial_player,
    was_called,
)

ONE_SHOT = ['play', 'pause', 'play-pause', 'stop', 'next', 'previous']

# command -> D-Bus method it ends up calling
CONTROL = {
    'play': 'Play',
    'pause': 'Pause',
    'play-pause': 'PlayPause',
    'stop': 'Stop',
    'next': 'Next',
    'previous': 'Previous',
    'open https://example.com/a.mp3': 'OpenUri',
    'position 5': 'SetPosition',
    'position 5+': 'Seek',
    'position 5-': 'Seek',
}

SETTERS = ['volume 0.5', 'loop Track', 'shuffle on']

ALL_COMMANDS = [*CONTROL, *SETTERS]

ERRORS = [
    ('custom', 'org.example.Custom.Error', 'custom text'),
    ('empty-text', 'org.example.Error', ''),
    ('long-name', 'org.example.' + 'E' * 200, 'x'),
    ('dbus-failed', 'org.freedesktop.DBus.Error.Failed', 'failed'),
    ('not-supported', 'org.freedesktop.DBus.Error.NotSupported', 'no'),
    ('invalid-args', 'org.freedesktop.DBus.Error.InvalidArgs', 'bad args'),
    ('access-denied', 'org.freedesktop.DBus.Error.AccessDenied', 'nope'),
    ('unknown-method', 'org.freedesktop.DBus.Error.UnknownMethod', 'huh'),
    ('no-memory', 'org.freedesktop.DBus.Error.NoMemory', 'oom'),
    ('timeout', 'org.freedesktop.DBus.Error.Timeout', 'slow'),
    ('nasty-text', 'org.example.Error', 'a\x1b[31mred\nline2\t%s%n{{x}}'),
    ('unicode-text', 'org.example.Error', '‮\U0001f600﻿'),
    ('huge-text', 'org.example.Error', 'E' * HUGE),
]


def _fail_rules(member, error, text):
    if member in ('Set',):
        return (member, PROPERTIES_INTERFACE, error, text)
    return (member, PLAYER_INTERFACE, error, text)


@pytest.mark.parametrize(
    ('eid', 'error', 'text'), ERRORS, ids=[e[0] for e in ERRORS]
)
@pytest.mark.parametrize('command', ALL_COMMANDS)
async def test_error_mid_command(
    command, eid, error, text, playerctl, mpris_factory
):
    member = CONTROL.get(command, 'Set')
    [mpris] = await mpris_factory(
        'evil', prepare=failing(_fail_rules(member, error, text))
    )
    await mpris.set_artist_title('artist', 'title')

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result, allowed=(1,))
    assert not result.stdout
    assert 'Could not execute command' in result.stderr


@pytest.mark.parametrize('command', ALL_COMMANDS)
async def test_error_text_survives_with_no_messages_flag(
    command, playerctl, mpris_factory
):
    member = CONTROL.get(command, 'Set')
    [mpris] = await mpris_factory(
        'evil',
        prepare=failing(_fail_rules(member, 'org.example.Error', 'kaput')),
    )
    await mpris.set_artist_title('artist', 'title')

    result = await run(playerctl, f'-s -p evil {command}')

    assert_sane(result, allowed=(1,))
    assert 'kaput' in result.stderr


# --- Can* lies ------------------------------------------------------------

GATES = [
    ('play', 'CanPlay'),
    ('pause', 'CanPause'),
    ('play-pause', 'CanPlay'),
    ('stop', 'CanPlay'),
    ('next', 'CanGoNext'),
    ('previous', 'CanGoPrevious'),
]


@pytest.mark.parametrize(('command', 'gate'), GATES)
@pytest.mark.parametrize(
    ('lie', 'value'),
    [
        ('string', Variant('s', 'true')),
        ('int', Variant('i', 1)),
        ('double', Variant('d', 1.0)),
        ('array', Variant('ab', [True])),
        ('dict', Variant('a{sv}', {})),
        ('nested', Variant('v', Variant('b', True))),
    ],
    ids=lambda p: p if isinstance(p, str) else '',
)
async def test_capability_of_wrong_type(
    command, gate, lie, value, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil', prepare=tamper({gate: value}))

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


@pytest.mark.parametrize(('command', 'gate'), GATES)
async def test_missing_capability(command, gate, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil', prepare=tamper(drop=[gate]))

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


@pytest.mark.parametrize(('command', 'gate'), GATES)
async def test_cannot_but_works_is_not_called(
    command, gate, playerctl, mpris_factory
):
    """CanPlay=false but the method would work: honour the player's word."""
    [mpris] = await mpris_factory('evil')
    await mpris.emit_properties(
        **{
            ''.join(
                ('_' + c.lower()) if c.isupper() else c for c in gate
            ).lstrip('_'): False
        }
    )

    result = await run(playerctl, f'-p evil {command}')

    assert result.returncode == 1
    assert not was_called(mpris, command)


async def test_can_seek_true_but_seek_errors(playerctl, mpris_factory):
    [mpris] = await mpris_factory(
        'evil',
        prepare=failing(('Seek', PLAYER_INTERFACE, 'org.example.Err', 'no')),
    )
    mpris.can_seek = True
    await mpris.set_artist_title('a', 't')

    result = await run(playerctl, '-p evil position 5+')

    assert_sane(result, allowed=(1,))
    assert 'Could not execute command' in result.stderr


async def test_can_seek_false_seek_command(playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    await mpris.emit_properties(can_seek=False)
    await mpris.set_artist_title('a', 't')

    for command in ('position 5', 'position 5+', 'position 5-'):
        result = await run(playerctl, f'-p evil {command}')
        assert_sane(result)


# --- never answering ------------------------------------------------------


@pytest.mark.parametrize(
    'command',
    ['play', 'next', 'open https://example.com/a.mp3', 'position 5']
    + ['position 5+', *SETTERS],
)
async def test_unanswered_call_blocks_until_answered(
    command, playerctl, mpris_factory
):
    member = CONTROL.get(command)
    if member is None:
        [mpris] = await mpris_factory('evil')
        mpris.gate = MessageGate(mpris.bus)
        mpris.gate.hold('Set', PROPERTIES_INTERFACE, PLAYER_INTERFACE)
    else:
        [mpris] = await mpris_factory('evil', prepare=holding(member))
    await mpris.set_artist_title('a', 't')
    proc = await playerctl.start(f'-p evil {command}')

    await mpris.gate.wait_held()
    await asyncio.sleep(0.5)
    assert proc.running()
    mpris.gate.release()
    await asyncio.wait_for(proc.proc.wait(), 3)

    assert proc.proc.returncode == 0


@pytest.mark.xfail(
    strict=True,
    reason='BUG-E3: a method call to a player that never replies blocks for '
    'the 25 s GDBus default timeout; the CLI has no timeout of its own',
)
async def test_unanswered_call_gives_up_quickly(playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil', prepare=holding('Play'))
    proc = await playerctl.start('-p evil play')

    await asyncio.wait_for(proc.proc.wait(), 3)

    assert proc.proc.returncode in (0, 1)


async def test_reply_after_client_gave_up(playerctl, mpris_factory):
    """The client is killed while a call is pending; a late reply must not
    upset the player or the next client."""
    [mpris] = await mpris_factory('evil', prepare=holding('Play'))
    proc = await playerctl.start('-p evil play')
    await mpris.gate.wait_held()
    proc.proc.kill()
    await proc.proc.wait()

    mpris.gate.release()
    result = await run(playerctl, '-p evil status')

    assert result.returncode == 0, result.stderr
    assert result.stdout == 'Playing'


# --- player disappearing ---------------------------------------------------


@pytest.mark.parametrize('command', ALL_COMMANDS)
@pytest.mark.parametrize('when', ['die_on', 'die_after'])
async def test_player_dies_on_first_contact(
    command, when, playerctl, mpris_factory
):
    if when == 'die_on':
        prepare = tamper(die_on=[CONTROL.get(command, 'Set')])
    else:
        prepare = tamper(die_after=['GetAll', 'Get'])
    [mpris] = await mpris_factory('evil', prepare=prepare)
    mpris.disconnected = True  # the mock closes its own connection

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


@pytest.mark.parametrize('command', ['status', 'position', 'metadata'])
async def test_player_dies_after_get(command, playerctl, mpris_factory):
    [mpris] = await mpris_factory(
        'evil', prepare=tamper(die_after=['GetAll', 'Get'])
    )
    mpris.disconnected = True

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


# --- missing interfaces ----------------------------------------------------


@pytest.mark.parametrize(
    'shape',
    [{}, {'root': True}, {'player': True}],
    ids=['nothing', 'root-only', 'player-only'],
)
@pytest.mark.parametrize(
    'command',
    [
        *ALL_COMMANDS,
        'status',
        'position',
        'volume',
        'loop',
        'shuffle',
        'metadata',
        'metadata title',
        "metadata --format '{{title}} {{position}} {{status}}'",
    ],
)
async def test_missing_interfaces(command, shape, playerctl, bus_address):
    bus = await setup_partial_player('partial', bus_address, **shape)
    try:
        result = await run(playerctl, f'-p partial {command}')
    finally:
        bus.disconnect()

    assert_sane(result)


@pytest.mark.parametrize('command', ['status', 'play', 'metadata', 'next'])
async def test_missing_interface_does_not_block_a_good_player(
    command, playerctl, mpris_factory, bus_address
):
    bus = await setup_partial_player('aaa', bus_address)
    try:
        [good] = await mpris_factory('zzz')
        await good.set_artist_title('A', 'T')
        result = await run(playerctl, f'-p aaa,zzz {command}')
    finally:
        bus.disconnect()

    assert result.returncode == 0, result.stderr
    if command in ONE_SHOT:
        assert was_called(good, command)


# --- every property dropped -----------------------------------------------

PLAYER_PROPS = [
    'PlaybackStatus',
    'LoopStatus',
    'Shuffle',
    'Volume',
    'Position',
    'Metadata',
    'CanPlay',
    'CanPause',
    'CanSeek',
    'CanGoNext',
    'CanGoPrevious',
    'CanControl',
    'Rate',
]


@pytest.mark.parametrize('command', [*ALL_COMMANDS, 'status', 'metadata'])
async def test_every_property_missing(command, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil', prepare=tamper(drop=PLAYER_PROPS))

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


@pytest.mark.parametrize('prop', PLAYER_PROPS)
@pytest.mark.parametrize(
    'command',
    ['status', 'position', 'volume', 'loop', 'shuffle', 'metadata', 'play'],
)
async def test_one_property_missing(prop, command, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil', prepare=tamper(drop=[prop]))

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


# --- position corner cases -------------------------------------------------


@pytest.mark.parametrize(
    'position', [INT64_MAX, INT64_MAX - 1, 2**62, -(2**63), -1]
)
async def test_playing_position_overflow(position, playerctl, mpris_factory):
    """A playing player's position grows with elapsed time; near INT64_MAX
    that sum must not wrap to a negative number."""
    [mpris] = await mpris_factory('evil')
    mpris.playback_status = 'Playing'
    await mpris.emit_properties(position=position)
    await asyncio.sleep(0.05)

    result = await run(playerctl, '-p evil position')

    assert_sane(result, allowed=(0, 1))


@pytest.mark.xfail(
    strict=True,
    reason='BUG-E4: position near INT64_MAX plus the elapsed time since the '
    'last update overflows (signed wrap) and a negative position is printed',
)
async def test_position_does_not_wrap(playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    mpris.playback_status = 'Playing'
    await mpris.emit_properties(position=INT64_MAX)
    await asyncio.sleep(0.2)

    result = await run(playerctl, '-p evil position')

    assert result.returncode == 0, result.stderr
    assert float(result.stdout) > 0


@pytest.mark.parametrize('seeked', [-1, INT64_MAX, -(2**63), 0])
@pytest.mark.parametrize('status', ['Playing', 'Paused'])
async def test_seeked_extreme_values(seeked, status, playerctl, mpris_factory):
    [mpris] = await mpris_factory('evil')
    mpris.playback_status = status
    await mpris.emit_properties(position=0)
    await send_signal(mpris, 'Seeked', 'x', [seeked], PLAYER_INTERFACE)

    result = await run(
        playerctl,
        "-p evil position --format '{{position}} {{duration(position)}}'",
    )

    assert_sane(result)


# --- list / all-players with evil company -------------------------------


ODD_NAMES = [
    'a-b_c',
    'x' * 200,
    'a.b.c.d.e.f',
    'playerctld.foo',
    'instance.a1234',
    'INSTANCE',
    '_',
    'a--b',
    'name.instance_withUnderscore',
    'ünicode'.encode('ascii', 'ignore').decode() or 'u',
]


@pytest.mark.parametrize('name', ODD_NAMES)
async def test_odd_bus_names(name, playerctl, mpris_factory):
    [mpris] = await mpris_factory(name)
    await mpris.set_artist_title('a', 't')

    for cmd in (
        '-a status',
        '-l',
        '-a metadata title',
        f'-p {name} status',
        '-a play',
    ):
        result = await run(playerctl, cmd)
        assert_sane(result)


@pytest.mark.parametrize('command', ['status', 'metadata title', 'play', '-l'])
async def test_all_players_with_hostile_neighbours(
    command, playerctl, mpris_factory, bus_address
):
    broken = [
        await setup_partial_player('broken1', bus_address),
        await setup_partial_player('broken2', bus_address, root=True),
        await setup_partial_player('broken3', bus_address, player=True),
    ]
    liar, slow, good = await mpris_factory('liar', 'slow', 'good')
    await good.set_artist_title('A', 'T')
    try:
        result = await run(playerctl, f'-a {command}')
    finally:
        for bus in broken:
            bus.disconnect()

    assert_sane(result)
    if command == 'status':
        assert 'Playing' in result.stdout


async def test_list_shows_players_without_interfaces(playerctl, bus_address):
    bus = await setup_partial_player('empty', bus_address)
    try:
        result = await run(playerctl, '-l')
    finally:
        bus.disconnect()

    assert_sane(result)


async def test_evil_player_before_good_in_all_players_status(
    playerctl, mpris_factory
):
    [evil] = await mpris_factory(
        'aaa', prepare=tamper({'PlaybackStatus': Variant('s', 'Banana')})
    )
    [good] = await mpris_factory('bbb')

    result = await run(playerctl, '-a status')

    assert_sane(result)
    assert 'Playing' in result.stdout

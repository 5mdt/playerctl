"""US-11.15: As a developer, I want hostile or nonsensical player names,
sources and `PlayerctlPlayerName` values to give me a `GLib.Error`, never a
crash or a GLib CRITICAL."""

import pytest

from ..helpers.gi import compose
from ..helpers.gi_abuse import (
    ATTEMPT,
    PLAYER_ERROR_DOMAIN,
    assert_clean,
    assert_not_found,
    parse_attempts,
)

HOSTILE_NAMES = {
    'empty': '',
    'space': ' ',
    'tab': '\t',
    'newline': 'lib\n',
    'dotted': 'a.b.c',
    'leading-dot': '.lib',
    'trailing-dot': 'lib.',
    'double-dot': '..',
    'wrong-case': 'LIB',
    'trailing-space': 'lib ',
    'full-bus-name': 'org.mpris.MediaPlayer2.lib',
    'prefix-only': 'org.mpris.MediaPlayer2.',
    'long-255': 'x' * 255,
    'long-100k': 'x' * 100000,
    'unicode': '\u00e9\u4e2d\U0001f3b5',
    'control': 'a\x01b\x7f',
    'glob': '*',
    'percent': '%s%n%d',
    'instance-empty': 'lib.instance',
    'instance-other': 'lib.instance1',
    'instance-huge': 'lib.instance' + '9' * 100,
    'instance-twice': 'lib.instance1.instance2',
    'instance-negative': 'lib.instance-1',
    'quote': '"; DROP',
}


@pytest.mark.parametrize(
    'name', HOSTILE_NAMES.values(), ids=HOSTILE_NAMES.keys()
)
async def test_hostile_name_is_not_found(name, gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        name = {name!r}
        attempt('new', lambda: Playerctl.Player.new(name))
        attempt('session', lambda: Playerctl.Player.new_for_source(
            name, Playerctl.Source.DBUS_SESSION))
        attempt('system', lambda: Playerctl.Player.new_for_source(
            name, Playerctl.Source.DBUS_SYSTEM))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    for label in ('new', 'session', 'system'):
        assert_not_found(parsed, label)


@pytest.mark.parametrize(
    'name',
    ['', ' ', 'a.b.c', 'x' * 255, '\u00e9', 'lib.instance1'],
    ids=['empty', 'space', 'dotted', 'long', 'unicode', 'instance'],
)
async def test_hostile_name_without_any_player(name, gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        attempt('new', lambda: Playerctl.Player.new({name!r}))
        """,
        )
    )

    assert_clean(result)
    assert_not_found(parse_attempts(result), 'new')


async def test_new_none_takes_the_first_player(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new(None)
        out(player.props.player_name)
    """)

    assert_clean(result)
    assert result.stdout == 'lib'


async def test_new_none_without_players_is_not_found(gi_run):
    result = await gi_run(
        compose(ATTEMPT, "attempt('new', lambda: Playerctl.Player.new(None))")
    )

    assert_clean(result)
    assert_not_found(parse_attempts(result), 'new')


async def test_new_for_source_none_source_searches_both_buses(
    gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run("""
        player = Playerctl.Player.new_for_source(
            'lib', Playerctl.Source.NONE)
        out(player.props.source.value_nick)
    """)

    assert_clean(result)
    assert result.stdout == 'dbus-session'


async def test_new_for_source_system_ignores_session_players(
    gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        attempt('system', lambda: Playerctl.Player.new_for_source(
            'lib', Playerctl.Source.DBUS_SYSTEM))
        """,
        )
    )

    assert_clean(result)
    assert_not_found(parse_attempts(result), 'system')


@pytest.mark.parametrize('source', [-1, 3, 77, 2**31, 'x', None, 1.5])
async def test_invalid_source_is_rejected_by_the_bindings(source, gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        attempt('src', lambda: Playerctl.Player.new_for_source(
            'lib', {source!r}))
        """,
        )
    )

    assert_clean(result)
    kind, _ = parse_attempts(result)['src']
    assert kind in ('pyexc', 'gerror')


async def test_instance_with_no_source_is_an_error(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run(
        compose(
            ATTEMPT,
            """
        name = Playerctl.PlayerName()
        name.name = 'lib'
        name.instance = 'lib'
        name.source = Playerctl.Source.NONE
        attempt('from', lambda: Playerctl.Player.new_from_name(name))
        """,
        )
    )

    assert_clean(result)
    assert parse_attempts(result)['from'] == (
        'gerror',
        f'{PLAYER_ERROR_DOMAIN} 3',
    )


async def test_new_from_name_for_an_absent_system_bus(gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            """
        import os
        os.environ['DBUS_SYSTEM_BUS_ADDRESS'] = 'unix:path=/nonexistent/bus'
        name = Playerctl.PlayerName()
        name.name = 'lib'
        name.instance = 'lib'
        name.source = Playerctl.Source.DBUS_SYSTEM
        attempt('from', lambda: Playerctl.Player.new_from_name(name))
        attempt('source', lambda: Playerctl.Player.new_for_source(
            'lib', Playerctl.Source.DBUS_SYSTEM))
        attempt('list', Playerctl.list_players)
        attempt('manager', Playerctl.PlayerManager)
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    for label in ('from', 'source', 'list', 'manager'):
        assert parsed[label][0] in ('gerror', 'ok'), (label, parsed[label])


async def test_absent_session_bus(gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            """
        import os
        os.environ['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=/nonexistent/bus'
        attempt('new', lambda: Playerctl.Player.new('lib'))
        attempt('none', lambda: Playerctl.Player.new(None))
        attempt('list', Playerctl.list_players)
        """,
        )
    )

    # the library says so on stderr (a warning, by design) and reports the
    # player as not found
    assert_clean(result, allow=['unable to list player names'])
    parsed = parse_attempts(result)
    assert_not_found(parsed, 'new')
    assert_not_found(parsed, 'none')
    assert parsed['list'][0] in ('ok', 'gerror')


GARBAGE_NAMES = [
    ('zzz', 'zzz'),
    ('zzz', None),
    (None, 'zzz'),
    (None, None),
    ('lib', 'lib.instance1'),
    ('a.b.c', 'a.b.c'),
]

# instance strings that are no valid D-Bus name: the library hands them to
# GDBus unchecked.
INVALID_BUS_NAMES = {
    'empty': '',
    'space': ' ',
    'long-255': 'x' * 255,
    'digit-start': '1abc',
    'bad-chars': 'a b$c',
    'double-dot': 'a..b',
}


async def _new_from_garbage(name, instance, gi_run):
    return await gi_run(
        compose(
            ATTEMPT,
            f"""
        name = Playerctl.PlayerName()
        name.name = {name!r}
        name.instance = {instance!r}
        name.source = Playerctl.Source.DBUS_SESSION
        try:
            player = Playerctl.Player.new_from_name(name)
        except GLib.Error as e:
            out('from gerror', e.domain)
            player = None
        if player is not None:
            out('from ok')
            attempt('play', player.play)
            attempt('title', player.get_title)
            attempt('position', player.get_position)
            attempt('volume', lambda: player.props.volume)
        """,
        )
    )


@pytest.mark.parametrize(('name', 'instance'), GARBAGE_NAMES)
async def test_new_from_garbage_name_never_crashes(
    name, instance, gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await _new_from_garbage(name, instance, gi_run)

    assert_clean(result, allow=['could not get metadata'])
    lines = result.stdout.splitlines()
    assert lines[0].startswith('from ')
    for line in lines[1:]:
        assert line.split()[1] in ('ok', 'gerror') or line == 'from ok', line


@pytest.mark.parametrize(
    'instance',
    [
        pytest.param(
            value,
            marks=pytest.mark.xfail(
                strict=True,
                reason='BUG-L1: new_from_name() passes an invalid D-Bus '
                'name to GDBus unchecked, which logs GLib-GIO-CRITICALs '
                'instead of failing with a GError',
            ),
            id=key,
        )
        for key, value in INVALID_BUS_NAMES.items()
    ],
)
async def test_new_from_invalid_bus_name_is_a_clean_error(
    instance, gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await _new_from_garbage('lib', instance, gi_run)

    assert_clean(result)
    assert result.stdout.splitlines()[0].startswith('from gerror')


async def test_player_for_a_name_that_never_existed_fails_on_use(gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            """
        name = Playerctl.PlayerName()
        name.name = 'ghost'
        name.instance = 'ghost'
        name.source = Playerctl.Source.DBUS_SESSION
        player = Playerctl.Player.new_from_name(name)
        attempt('play', player.play)
        attempt('position', player.get_position)
        attempt('seek', lambda: player.seek(1))
        """,
        )
    )

    assert_clean(result)
    parsed = parse_attempts(result)
    for label in ('play', 'position', 'seek'):
        assert parsed[label][0] == 'gerror', (label, parsed[label])


async def test_player_name_copy_is_independent(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        [original] = Playerctl.list_players()
        copy = original.copy()
        copy.name = 'changed'
        copy.instance = 'changed.instance1'
        out(original.name, original.instance, copy.name, copy.instance)
        del copy
        out(original.name, original.instance)
    """)

    assert_clean(result)
    assert result.stdout.splitlines() == [
        'lib lib changed changed.instance1',
        'lib lib',
    ]


async def test_player_name_copy_of_an_empty_name(gi_run):
    result = await gi_run("""
        empty = Playerctl.PlayerName()
        copy = empty.copy()
        out(copy.name, copy.instance, copy.source.value_nick)
        out(copy.copy().name)
    """)

    assert_clean(result)
    assert result.stdout.splitlines() == ['None None none', 'None']


async def test_player_name_copy_survives_the_original(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        import gc
        [original] = Playerctl.list_players()
        copy = original.copy()
        del original
        gc.collect()
        out(copy.name, copy.instance)
    """)

    assert_clean(result)
    assert result.stdout == 'lib lib'


async def test_player_name_survives_its_source_list(gi_run, mpris_factory):
    await mpris_factory('lib')

    result = await gi_run("""
        import gc
        names = Playerctl.list_players()
        keep = names[0]
        del names
        gc.collect()
        out(keep.name, Playerctl.Player.new_from_name(keep).props.player_name)
    """)

    assert_clean(result)
    assert result.stdout == 'lib lib'


@pytest.mark.parametrize('value', [None, 5, 1.5, b'x', [1]])
async def test_player_name_rejects_wrongly_typed_fields(value, gi_run):
    result = await gi_run(
        compose(
            ATTEMPT,
            f"""
        name = Playerctl.PlayerName()

        def assign():
            name.name = {value!r}
            return name.name

        attempt('assign', assign)
        """,
        )
    )

    assert_clean(result)
    kind, _ = parse_attempts(result)['assign']
    assert kind in ('ok', 'pyexc')


async def test_player_names_compare_by_identity_in_python(
    gi_run, mpris_factory
):
    await mpris_factory('lib')

    result = await gi_run("""
        [a] = Playerctl.list_players()
        [b] = Playerctl.list_players()
        out(a == a, a == b.copy(), a is b)
    """)

    assert_clean(result)
    assert result.stdout.split()[0] == 'True'

"""US-5.3: As a bar author, I want a player that reports a property with the
wrong type, an absurd value or not at all to never crash, hang or spam GLib
warnings in playerctl: the exit code stays 0 or 1 and stderr stays clean."""

import pytest

from ..helpers.evil_mpris import (
    PLAYER_LIES,
    assert_sane,
    run,
    tamper,
)

READ_COMMANDS = [
    'status',
    'position',
    'volume',
    'loop',
    'shuffle',
    'metadata',
    'metadata title',
    'metadata artist',
    'metadata mpris:length',
    "metadata --format '{{title}}|{{artist}}|{{position}}|{{volume}}|{{status}}'",
]


FORMAT = READ_COMMANDS[-1]
# BUG-E2: a Metadata that is not a{sv} aborts playerctl (SIGABRT) in
# g_variant_lookup_value(), playerctl-player-commands.c:367 and
# playerctl-cli.c:703 and the formatter
BUG_E2 = pytest.mark.xfail(
    strict=True,
    reason='BUG-E2: non-dict Metadata aborts in g_variant_lookup_value()',
)
BUG_E2_CASES = {
    (lie, command)
    for lie in ('metadata-string', 'metadata-ai', 'metadata-int')
    for command in (
        'metadata title',
        'metadata artist',
        'metadata mpris:length',
        FORMAT,
    )
} | {('metadata-a-ss', FORMAT)}


def _cases():
    for lie, prop, value in PLAYER_LIES:
        for command in READ_COMMANDS:
            marks = [BUG_E2] if (lie, command) in BUG_E2_CASES else []
            yield pytest.param(
                prop, value, command, id=f'{lie}-{command}', marks=marks
            )


@pytest.mark.parametrize(('prop', 'value', 'command'), list(_cases()))
async def test_wrong_property_value(
    prop, value, command, playerctl, mpris_factory
):
    [mpris] = await mpris_factory('evil', prepare=tamper({prop: value}))
    await mpris.set_artist_title('artist', 'title')

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result)


@pytest.mark.xfail(
    strict=True,
    reason='BUG-E1: GIO prints a GLib-GIO-WARNING for a property of the '
    'wrong type',
)
@pytest.mark.parametrize(
    ('lie', 'command'),
    [
        ('status-int', 'status'),
        ('volume-string', 'volume'),
        ('position-string', 'position'),
        ('shuffle-string', 'shuffle'),
        ('loop-int', 'loop'),
    ],
)
async def test_wrong_type_does_not_warn(
    lie, command, playerctl, mpris_factory
):
    prop, value = next((p, v) for i, p, v in PLAYER_LIES if i == lie)
    [mpris] = await mpris_factory('evil', prepare=tamper({prop: value}))

    result = await run(playerctl, f'-p evil {command}')

    assert_sane(result, tolerate_gio_type_warning=False)

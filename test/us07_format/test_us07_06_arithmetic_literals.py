"""US-7.6: As a bar author, I want arithmetic (`+ - * /`, parentheses, unary
minus) and string literals."""

import pytest
from dbus_next import Variant

from ..helpers.format import (
    ARTIST,
    MATH_FUNCTIONS,
    MATH_NUMBERS,
    MATH_VARIABLES,
    TITLE,
    check_math,
)


async def test_string_literals(metadata_test):
    metadata_test.add('{{uc("Hi")}}', 'HI')
    metadata_test.add(
        '@{{ uc( "hi" ) }} - {{uc( lc( "HO"  ) ) }} . {{lc( uc(  title ) )   }}@',
        f'@HI - HO . {TITLE.lower()}@',
    )

    await metadata_test.run()


@pytest.mark.parametrize('expr', MATH_NUMBERS)
async def test_numbers(expr, playerctl, format_player):
    await check_math(playerctl, expr)


@pytest.mark.parametrize('expr', MATH_VARIABLES)
async def test_variables(expr, playerctl, format_player):
    await check_math(playerctl, expr, volume=format_player.volume)


@pytest.mark.parametrize('expr', MATH_FUNCTIONS)
async def test_functions(expr, playerctl, format_player):
    await check_math(playerctl, expr)


@pytest.mark.parametrize(
    ('expr', 'expected'),
    [
        ('.5', 0.5),
        ('1.', 1.0),
        ('.5 + .5', 1.0),
        ('1. + 2.', 3.0),
        ('0.25 * 4', 1.0),
        ('007', 7.0),
        ('2 * 3', 6.0),  # number terminating the expression
        ('(2)', 2.0),
        ('(.5)', 0.5),
        ('1.5e0', None),  # exponent form is not supported
    ],
)
async def test_number_literal_forms(expr, expected, playerctl, format_player):
    cmd = await playerctl.run("metadata --format '{{" + expr + "}}'")
    if expected is None:
        assert cmd.returncode == 1, cmd.stderr
    else:
        assert cmd.returncode == 0, cmd.stderr
        assert float(cmd.stdout) == expected


async def test_literal_at_end_of_template(metadata_test):
    metadata_test.add('{{ 5 }}', '5.0')
    metadata_test.add('{{5}}', '5.0')
    metadata_test.add('{{ "x" }}', 'x')
    metadata_test.add('v={{1}}', 'v=1.0')

    await metadata_test.run()


async def test_metadata_key_shadows_default_variable(playerctl, format_player):
    format_player.metadata = {
        **format_player.metadata,
        'title': Variant('s', 'Shadow'),
        'volume': Variant('s', 'loud'),
    }
    await format_player.ping()
    cmd = await playerctl.run(
        "metadata --format '{{title}}|{{volume}}|{{artist}}'"
    )
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == f'Shadow|loud|{ARTIST}'

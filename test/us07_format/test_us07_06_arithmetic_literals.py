"""US-7.6: As a bar author, I want arithmetic (`+ - * /`, parentheses, unary
minus) and string literals."""

import pytest

from ..helpers.format import (
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

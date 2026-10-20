"""US-7.9: As a bar author, I want arithmetic on integer, unsigned, double and
missing values to either compute correctly or fail with a clear error."""

import pytest


async def run_fmt(playerctl, template):
    return await playerctl.run(f"metadata --format '{template}'")


@pytest.mark.parametrize(
    ('expr', 'expected'),
    [
        ('xesam:i7 / xesam:i2', '3'),  # int64 division truncates
        ('-xesam:i7 / xesam:i2', '-3'),  # truncates toward zero
        ('-xesam:i7', '-7'),
        ('+xesam:i7', '7'),
        ('xesam:i7 + xesam:i2 * xesam:i2', '11'),
        ('xesam:i7 * xesam:i2', '14'),
        ('-xesam:i7 * xesam:i2', '-14'),
        ('xesam:i0 * xesam:i7', '0'),
    ],
)
async def test_int64_arithmetic(expr, expected, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == expected


@pytest.mark.parametrize(
    ('expr', 'expected'),
    [
        ('xesam:i7 / 2', 3.5),  # int64 / double is a double division
        ('xesam:i7 + 0.5', 7.5),
        ('xesam:d2 * xesam:i2', 5.0),
        ('xesam:d2 / 2', 1.25),
        ('mpris:length + 1', 100001.0),
        ('mpris:length - 1', 99999.0),
        ('mpris:length * 2', 200000.0),
        ('mpris:length / 1000', 100.0),
        ('-xesam:d2', -2.5),
        ('+xesam:d2', 2.5),
    ],
)
async def test_mixed_and_double_arithmetic(
    expr, expected, playerctl, numeric_player
):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 0, cmd.stderr
    assert float(cmd.stdout) == expected


@pytest.mark.parametrize(
    ('expr', 'expected'),
    [
        ('xesam:u5 + 1', 6.0),
        ('xesam:u5 * 2', 10.0),
        ('xesam:u5 - 7', -2.0),
        ('xesam:u5 / 2', 2.5),
        ('xesam:u5 + xesam:u5', 10.0),
        ('xesam:u5 + xesam:i2', 7.0),
        ('+xesam:u5', 5.0),
    ],
)
async def test_uint64_arithmetic(expr, expected, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 0, cmd.stderr
    assert float(cmd.stdout) == expected


async def test_uint64_unary_minus(playerctl, numeric_player):
    # unary + accepts uint64, so unary - should too
    cmd = await run_fmt(playerctl, '{{-xesam:u5}}')
    assert cmd.returncode == 0, cmd.stderr
    assert float(cmd.stdout) == -5.0


@pytest.mark.parametrize(
    'expr',
    [
        'xesam:i7 / xesam:i0',  # int64 divide by zero
        'xesam:i7 / 0',  # double divide by zero
        'xesam:d2 / xesam:d0',
        'xesam:d2 / xesam:i0',
        'xesam:u5 / xesam:u0',
        'xesam:i7 / (1 - 1)',
    ],
)
async def test_divide_by_zero(expr, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'Divide by zero' in cmd.stderr


@pytest.mark.parametrize(
    'expr',
    [
        'xesam:imax + xesam:i2',
        'xesam:imin - xesam:i2',
        'xesam:imax - -xesam:i2',
        'xesam:imax * xesam:i2',
        'xesam:imin * xesam:i2',
    ],
)
async def test_int64_overflow(expr, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'overflow' in cmd.stderr.lower()


@pytest.mark.parametrize(
    'expr',
    [
        'title + 1',
        '1 + title',
        'title - 1',
        'title * 2',
        'title / 2',
        '-title',
        '+title',
        '"a" * 2',
        '"a" + "b"',
        'artist * 2',
        'xesam:flag + 1',
        '-xesam:flag',
    ],
)
async def test_type_errors(expr, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'unsupported operand' in cmd.stderr


@pytest.mark.parametrize(
    'expr',
    [
        'xesam:missing + 1',
        '1 + xesam:missing',
        'xesam:missing - 1',
        'xesam:missing * 2',
        '2 * xesam:missing',
        'xesam:missing / 2',
        '-xesam:missing',
        '+xesam:missing',
        'xesam:missing + xesam:missing',
    ],
)
async def test_missing_operand_is_an_error(expr, playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{' + expr + '}}')
    # a clean error exit, not a crash (signals give negative codes)
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'unsupported operand' in cmd.stderr
    assert 'CRITICAL' not in cmd.stderr
    assert 'assert' not in cmd.stderr.lower()


async def test_missing_variable_alone_renders_empty(playerctl, numeric_player):
    cmd = await run_fmt(playerctl, '{{xesam:missing}}')
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == ''

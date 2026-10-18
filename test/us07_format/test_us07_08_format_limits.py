"""US-7.8: As a bar author, I want oversized templates (too long, too many
function arguments) rejected with a clear error instead of misbehaving."""

import pytest

MAX_FORMAT_LEN = 1027  # lengths >= 1028 are rejected


async def run_fmt(playerctl, template):
    return await playerctl.run(f"metadata --format '{template}'")


async def test_format_at_max_length_is_accepted(playerctl, format_player):
    template = 'x' * MAX_FORMAT_LEN
    cmd = await run_fmt(playerctl, template)
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == template


@pytest.mark.parametrize('length', [MAX_FORMAT_LEN + 1, 2000, 5000])
async def test_format_over_max_length_is_rejected(
    length, playerctl, format_player
):
    cmd = await run_fmt(playerctl, 'x' * length)
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'maximum format string length' in cmd.stderr


async def test_long_template_with_expression_at_limit(
    playerctl, format_player
):
    expr = '{{title}}'
    template = 'y' * (MAX_FORMAT_LEN - len(expr)) + expr
    assert len(template) == MAX_FORMAT_LEN
    cmd = await run_fmt(playerctl, template)
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout == 'y' * (MAX_FORMAT_LEN - len(expr)) + 'A Title'


async def test_max_function_arguments_boundary(playerctl, format_player):
    # 32 arguments is the limit: reaches the helper, which rejects the count
    args = ', '.join(['title'] * 32)
    cmd = await run_fmt(playerctl, '{{lc(' + args + ')}}')
    assert cmd.returncode == 1, cmd.stderr
    assert 'takes exactly one argument' in cmd.stderr


@pytest.mark.parametrize('count', [33, 34, 100])
async def test_too_many_function_arguments(count, playerctl, format_player):
    args = ', '.join(['title'] * count)
    cmd = await run_fmt(playerctl, '{{lc(' + args + ')}}')
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert 'maximum args of 32 exceeded' in cmd.stderr

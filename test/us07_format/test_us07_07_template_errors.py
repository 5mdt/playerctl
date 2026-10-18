"""US-7.7: As a user, I want template errors to fail with exit code 1."""

import pytest

from dbus_next import Variant


async def test_emoji_with_bad_arguments(playerctl, mpris_factory):
    [mpris] = await mpris_factory('emoji-format-test')
    mpris.metadata = {'mpris:length': Variant('x', 100000)}
    await mpris.ping()

    cmd = await playerctl.run("metadata --format '{{emoji(\"hi\")}}'")
    assert cmd.returncode == 1, cmd.stderr

    cmd = await playerctl.run("metadata --format '{{emoji(status, volume)}}'")
    assert cmd.returncode == 1, cmd.stderr


@pytest.mark.parametrize(
    'template',
    [
        '{{nosuchfunc(title)}}',
        '{{nosuchfunc(1)}}',
        '{{ lc(nosuchfunc(title)) }}',
        '{{title',  # unterminated expression
        '{{lc(title}}',  # unbalanced paren
        '{{lc(title))}}',
        '{{(1 + 2}}',
        '{{1 +}}',
        '{{}}',
        '{{lc(title,)}}',
        '{{"unterminated}}',
        '{{1..2}}',
        '{{title title}}',
        '{{lc(title) )}}',
    ],
)
async def test_syntax_errors(template, playerctl, format_player):
    cmd = await playerctl.run(f"metadata --format '{template}'")
    assert cmd.returncode == 1, cmd.stderr
    assert cmd.stdout == ''
    assert cmd.stderr


async def test_unknown_function_message(playerctl, format_player):
    cmd = await playerctl.run("metadata --format '{{nosuchfunc(title)}}'")
    assert cmd.returncode == 1, cmd.stderr
    assert 'unknown template function: nosuchfunc' in cmd.stderr


@pytest.mark.parametrize(
    'template',
    [
        '{{lc()}}',
        '{{lc(title, title)}}',
        '{{uc(title, title)}}',
        '{{default(title)}}',
        '{{trunc(title)}}',
    ],
)
async def test_wrong_argument_count(template, playerctl, format_player):
    cmd = await playerctl.run(f"metadata --format '{template}'")
    assert cmd.returncode == 1, cmd.stderr


@pytest.mark.parametrize(
    ('template', 'message'),
    [
        ('{{title', 'unexpected end of expression'),
        ('{{title }', 'expecting "}}"'),
        ('{{title} }', 'expecting "}}"'),
        ('{{lc(title}}', 'expecting ")"'),
        ('{{lc(title title)}}', 'expecting ")"'),
        ('{{}}', 'expected expression'),
        ('{{1..2}}', 'invalid number'),
        ('{{1.2.3}}', 'invalid number'),
    ],
)
async def test_error_wording(template, message, playerctl, format_player):
    cmd = await playerctl.run(f"metadata --format '{template}'")
    assert cmd.returncode == 1, cmd.stderr
    assert message in cmd.stderr

"""US-9.4: the command list in `--help` matches the manual page and
doc/usage.md, which carry the same list by hand."""

import re
from pathlib import Path

DOC = Path(__file__).resolve().parents[2] / 'doc'


def _help_commands(help_text):
    section = help_text.split('Available Commands:', 1)[1]
    return re.findall(r'^  ([a-z-]+)(?: |$)', section, re.MULTILINE)


async def test_help_commands_are_documented(playerctl):
    result = await playerctl.run('--help')
    assert result.returncode == 0, result.stderr
    commands = _help_commands(result.stdout)
    assert len(commands) >= 12, result.stdout

    manual = (DOC / 'playerctl.1.in').read_text()
    usage = (DOC / 'usage.md').read_text()
    for command in commands:
        assert f'.It Cm {command}' in manual, f'{command} missing in manpage'
        assert re.search(
            rf'\*\*`{re.escape(command)}[ `]', usage
        ), f'{command} missing in usage.md'

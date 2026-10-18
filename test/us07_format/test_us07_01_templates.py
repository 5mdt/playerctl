"""US-7.1: As a bar author, I want `-f '{{artist}} - {{title}}'` templates on
query commands."""

from ..helpers.format import ALBUM, ARTIST, TITLE


async def test_template_with_metadata(metadata_test):
    metadata_test.add('{{artist}} - {{title}}', f'{ARTIST} - {TITLE}')
    # text around the expression is kept
    metadata_test.add(' {{lc(album)}} ', ALBUM.lower())

    await metadata_test.run()


async def test_plain_text_without_expressions(metadata_test):
    metadata_test.add('just text', 'just text')
    metadata_test.add('a { b } c', 'a { b } c')
    metadata_test.add('lone { brace', 'lone { brace')
    metadata_test.add('stray }} close', 'stray }} close')
    metadata_test.add('{single} braces', '{single} braces')

    await metadata_test.run()


async def test_empty_format(playerctl, format_player):
    cmd = await playerctl.run("metadata --format ''")
    assert cmd.returncode == 0, cmd.stderr
    assert cmd.stdout.strip() == ''


async def test_missing_variable_renders_empty(metadata_test):
    metadata_test.add('{{xesam:missing}}', '')
    metadata_test.add('[{{xesam:missing}}]', '[]')
    metadata_test.add('{{ xesam:missing }}', '')
    metadata_test.add('{{xesam:missing}}{{title}}', 'A Title')

    await metadata_test.run()

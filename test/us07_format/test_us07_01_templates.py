"""US-7.1: As a bar author, I want `-f '{{artist}} - {{title}}'` templates on
query commands."""

from ..helpers.format import ALBUM, ARTIST, TITLE


async def test_template_with_metadata(metadata_test):
    metadata_test.add('{{artist}} - {{title}}', f'{ARTIST} - {TITLE}')
    # text around the expression is kept
    metadata_test.add(' {{lc(album)}} ', ALBUM.lower())

    await metadata_test.run()

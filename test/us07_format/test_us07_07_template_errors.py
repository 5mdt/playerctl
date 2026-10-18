"""US-7.7: As a user, I want template errors to fail with exit code 1."""

from dbus_next import Variant


async def test_emoji_with_bad_arguments(playerctl, mpris_factory):
    [mpris] = await mpris_factory('emoji-format-test')
    mpris.metadata = {'mpris:length': Variant('x', 100000)}
    await mpris.ping()

    cmd = await playerctl.run("metadata --format '{{emoji(\"hi\")}}'")
    assert cmd.returncode == 1, cmd.stderr

    cmd = await playerctl.run("metadata --format '{{emoji(status, volume)}}'")
    assert cmd.returncode == 1, cmd.stderr

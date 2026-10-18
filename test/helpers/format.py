import asyncio

TITLE = 'A Title'
ARTIST = 'An Artist'
ALBUM = 'An Album'
PLAYER_NAME = 'format-test'
PLAYER_INSTANCE = f'{PLAYER_NAME}.instance123'
VOLUME = 2.0


class MetadataTest:
    '''Collect `metadata --format` cases and run them concurrently.'''

    def __init__(self, playerctl):
        self.tests = []
        self.playerctl = playerctl

    def add(self, fmt, expected, ret=0):
        fmt = fmt.replace("'", r"\'")
        self.tests.append((f"metadata --format '{fmt}'", expected, ret))

    async def run(self):
        coros = [self.playerctl.run(fmt) for fmt, _, _ in self.tests]
        results = await asyncio.gather(*coros)

        for i, cmd in enumerate(results):
            fmt, expected, ret = self.tests[i]
            assert cmd.returncode == ret, cmd.stderr
            if ret == 0:
                assert cmd.stdout == expected, cmd.stderr


MATH_NUMBERS = [
    '10',
    '-10 + 20',
    '10 + 10',
    '10 * 10',
    '10 / 10',
    '10 + 10 * 10 + 10',
    '10 + 10 * -10 + 10',
    '10 + 10 * -10 + -10',
    '-10 * 10 + 10',
    '-10 * -10 * -1 + -10',
    '-10 * 10 + -10 * -10 + 20 / 10 * -20 + -10',
    '8+-+--++-4',
    '2 - 10 * 1 + 1',
    '2 / -2 + 2 * 2 * -2 - 2 - 2 * -2',
    '2 * (2 + 2)',
    '10 * (10 + 12) - 4',
    '-(10)',
    '-(10 + 12 * -2)',
    '14 - (10 * 2 + 5) * -6',
    '(14 - 2 * 3) * (14 * -2 - 6) + -(4 - 2) * 5',
]

MATH_VARIABLES = [
    'volume',
    'volume + 10',
    '-volume',
    '-volume * -1',
    '-volume + volume',
    'volume * volume',
    'volume * -volume',
    'volume + volume * -volume * volume + -volume',
    'volume / -volume + volume * volume * -volume - volume - volume * -volume',
    '-(volume + 3) * 5 * (volume + 2)',
]

MATH_FUNCTIONS = [
    'default(5+5, None)',
    '-default(5 + 5, None)',
    '(-default(5 - 5, None) + 2) * 8',
    '2 + (5 * 4 + 3 * -default(5, default(6 * (3 + 4 * (6 + 2)) / 2, None)) + -56)',
]


def default_shim(arg1, arg2):
    '''Python equivalent of the template `default` helper, for eval().'''
    if arg1 is None:
        return arg2
    return arg1


async def check_math(playerctl, expr, volume=VOLUME):
    cmd = await playerctl.run("metadata --format '{{" + expr + "}}'")
    assert cmd.returncode == 0, cmd.stderr
    assert float(cmd.stdout) == eval(
        expr, {'volume': volume, 'default': default_shim}
    ), expr

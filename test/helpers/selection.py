S1 = 'selection1'
S1I = 'selection1.i_123'
S2 = 'selection2'
S3 = 'selection3'
M4 = 'selection4'
M5 = 'selection5'
M6 = 'selection6'
S6I = 'selection6.i_2'
ANY = '%any'

# the mock players that actually exist on the bus (M4..M6 are missing, S6I is
# an instance of M6)
PLAYERS = (S1, S1I, S2, S3, S6I)

# selection passed to --player -> expected players in priority order
SELECTIONS = {
    (S1,): (S1, S1I),
    (S3, S1): (S3, S1, S1I),
    (S2, S1, S3): (S2, S1, S1I, S3),
    (S1, S2): (S1, S1I, S2),
    (M4, M5, S2, S3): (S2, S3),
    (M5, S1, M4, S3): (S1, S1I, S3),
    (S1, S1I): (S1, S1I),
    (S1I, S1): (S1I, S1),
    (M6, S1): (S6I, S1, S1I),
    (M4, M6, S3): (S6I, S3),
    (ANY,): (S1, S1I, S2, S3, S6I),
    (S1, ANY): (S1, S1I, S2, S3, S6I),  # s1 first
    (ANY, S1): (S2, S3, S6I, S1, S1I),  # s1 last
    (M6, ANY, S2): (S6I, S1, S1I, S3, S2),  # s6 first, s2 last
    (M6, S1, ANY, S2): (S6I, S1, S1I, S3, S2),
}

PLAIN_SELECTIONS = {k: v for k, v in SELECTIONS.items() if ANY not in k}
ANY_SELECTIONS = {k: v for k, v in SELECTIONS.items() if ANY in k}

# selection, players known to playerctld, expected --list-all result
DAEMON_S2I = 'selection2.i_123'
DAEMON_PLAYERS = [S1, S1I, S2, S3, S6I]
DAEMON_SELECTIONS = [
    (None, DAEMON_PLAYERS, DAEMON_PLAYERS),
    (DAEMON_PLAYERS, DAEMON_PLAYERS, DAEMON_PLAYERS),
    ([S2], [S1, S2], [S2]),
    ([S1], [S2, S1I, S1], [S1I, S1]),
    ([S1], [S2, S1, S1I], [S1, S1I]),
    ([S1I, S1], [S1, S1I], [S1I, S1]),
    ([ANY], DAEMON_PLAYERS, DAEMON_PLAYERS),
    ([ANY, S1], [S1, S1I, DAEMON_S2I, S2], [DAEMON_S2I, S2, S1, S1I]),
    ([ANY, S1], [S1, S1I, S2, DAEMON_S2I], [S2, DAEMON_S2I, S1, S1I]),
    ([ANY, S1], [S1I, S1, DAEMON_S2I, S2], [DAEMON_S2I, S2, S1I, S1]),
    ([ANY, S1], [S1I, S1, S2, DAEMON_S2I], [S2, DAEMON_S2I, S1I, S1]),
    ([S2, ANY], [S1, S1I, DAEMON_S2I, S2], [DAEMON_S2I, S2, S1, S1I]),
    ([S2, ANY], [S1, S1I, S2, DAEMON_S2I], [S2, DAEMON_S2I, S1, S1I]),
    ([S2, ANY], [S1I, S1, DAEMON_S2I, S2], [DAEMON_S2I, S2, S1I, S1]),
    ([S2, ANY], [S1I, S1, S2, DAEMON_S2I], [S2, DAEMON_S2I, S1I, S1]),
    ([DAEMON_S2I, ANY], [S1I, S1, S2, DAEMON_S2I], [DAEMON_S2I, S1I, S1, S2]),
]


def selector(playerctl):
    '''Return (select, select_many) coroutines bound to a PlayerctlCli.'''

    async def select(*players):
        assert players
        cmd = (
            '-p '
            + str.join(',', players)
            + ' status --format "{{playerInstance}}"'
        )
        result = await playerctl.run(cmd)
        assert result.returncode == 0, result.stderr
        return result.stdout

    async def select_many(*players):
        assert players
        cmd = (
            '--all-players -p '
            + str.join(',', players)
            + ' status --format "{{playerInstance}}"'
        )
        result = await playerctl.run(cmd)
        assert result.returncode == 0, result.stderr
        return tuple(result.stdout.split('\n'))

    return select, select_many

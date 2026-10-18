import asyncio

FOLLOW_FORMAT = '{{playerInstance}}: {{artist}} - {{title}}'


def follow_cmd(selection=None, all_players=False, ignore=None):
    '''Build `metadata --follow` args for the standard follow format.'''
    args = []
    if all_players:
        args.append('--all-players')
    if selection:
        args.append(f'--player {selection}')
    if ignore:
        args.append(f'--ignore-player {ignore}')
    args.append(f'metadata --format "{FOLLOW_FORMAT}" --follow')
    return ' '.join(args)


async def next_line(proc, timeout=2.0):
    '''Next line a follow process prints; fails fast if none arrives.'''
    return await asyncio.wait_for(proc.queue.get(), timeout)


async def expect_no_line(proc, wait=0.5):
    '''Assert the follow process prints nothing for `wait` seconds.'''
    await asyncio.sleep(wait)
    assert proc.queue.empty(), f'unexpected line: {proc.queue.get_nowait()!r}'


async def lines_until(proc, expected, limit=4):
    '''Read lines until `expected` shows up; fails if it does not within `limit`.'''
    seen = []
    for _ in range(limit):
        line = await next_line(proc)
        seen.append(line)
        if line == expected:
            return seen
    raise AssertionError(f'{expected!r} not printed, got {seen!r}')

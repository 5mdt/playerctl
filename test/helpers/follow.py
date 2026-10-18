FOLLOW_FORMAT = '{{playerInstance}}: {{artist}} - {{title}}'


def follow_cmd(selection=None, all_players=False):
    '''Build `metadata --follow` args for the standard follow format.'''
    args = []
    if all_players:
        args.append('--all-players')
    if selection:
        args.append(f'--player {selection}')
    args.append(f'metadata --format "{FOLLOW_FORMAT}" --follow')
    return ' '.join(args)

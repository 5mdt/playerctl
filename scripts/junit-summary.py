#!/usr/bin/env python3
"""Print a per-category outcome table from JUnit XML files (pytest, meson).

Usage: junit-summary.py [--csv HISTORY.csv] FILE.xml ...

--csv appends the table rows to a time series, tagged with $HISTORY_TIME (default: now, UTC)
and $GIT_COMMIT.

The category of a pytest case is its usNN_* test directory; a meson case is
categorized by its test executable (the part of the suite name after ':').
"""

import argparse
import csv
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from junitparser import Error, Failure, JUnitXml, Skipped

COLUMNS = ('passed', 'failed', 'error', 'xfailed', 'skipped')
HEADER = ['category', 'total', *COLUMNS]
CATEGORY = re.compile(r'\bus\d+_\w+')


def outcome(case):
    results = case.result or []
    if any(isinstance(r, Failure) for r in results):
        return 'failed'
    if any(isinstance(r, Error) for r in results):
        return 'error'
    for r in results:
        if isinstance(r, Skipped):
            return 'xfailed' if 'xfail' in (r.type or '') else 'skipped'
    return 'passed'


def collect(paths):
    counts = defaultdict(lambda: dict.fromkeys(COLUMNS, 0))
    for path in paths:
        for suite in JUnitXml.fromfile(path):
            for case in suite:
                classname = case.classname or ''
                match = CATEGORY.search(classname)
                category = match.group() if match else classname.split(':')[-1]
                counts[category or Path(path).stem][outcome(case)] += 1
    return counts


def rows(counts):
    """One row per category, then TOTAL: [name, total, *COLUMNS]."""
    table = [
        [name, sum(c.values()), *c.values()]
        for name, c in sorted(counts.items())
    ]
    table.append(
        ['TOTAL', *(sum(r[i] for r in table) for i in range(1, len(HEADER)))]
    )
    return table


def render(table):
    width = max(len(r[0]) for r in table)
    lines = [
        ' '.join(
            h.ljust(width) if i == 0 else h.rjust(8)
            for i, h in enumerate(HEADER)
        )
    ]
    lines.append('-' * len(lines[0]))
    lines += [
        ' '.join(
            str(c).ljust(width) if i == 0 else str(c).rjust(8)
            for i, c in enumerate(r)
        )
        for r in table
    ]
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--csv', help='append the rows to this time series')
    parser.add_argument('files', nargs='+')
    args = parser.parse_args()
    table = rows(collect(args.files))
    print(render(table))
    if args.csv:
        new = not Path(args.csv).exists()
        now = os.environ.get('HISTORY_TIME') or datetime.now(
            timezone.utc
        ).isoformat(timespec='seconds')
        commit = os.environ.get('GIT_COMMIT', '')
        with open(args.csv, 'a', newline='') as f:
            out = csv.writer(f)
            if new:
                out.writerow(['time', 'commit', *HEADER])
            out.writerows([now, commit, *r] for r in table)


if __name__ == '__main__':
    main()

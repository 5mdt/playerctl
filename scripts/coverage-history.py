#!/usr/bin/env python3
"""Append a gcovr --json-summary report to a coverage time-series CSV.

Usage: coverage-history.py SUMMARY.json HISTORY.csv

Writes one row per source file plus a TOTAL row, tagged with the UTC time and
$GIT_COMMIT.
"""

import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

HEADER = [
    'time',
    'commit',
    'file',
    'lines_total',
    'lines_covered',
    'line_percent',
    'branches_total',
    'branches_covered',
    'branch_percent',
]
FIELDS = ['line_total', 'line_covered', 'line_percent'] + [
    'branch_total',
    'branch_covered',
    'branch_percent',
]


def main(summary, history):
    report = json.loads(Path(summary).read_text())
    entries = sorted(report['files'], key=lambda f: f['filename'])
    entries.append({**report, 'filename': 'TOTAL'})
    now = os.environ.get('HISTORY_TIME') or datetime.now(
        timezone.utc
    ).isoformat(timespec='seconds')
    commit = os.environ.get('GIT_COMMIT', '')
    new = not Path(history).exists()
    with open(history, 'a', newline='') as f:
        out = csv.writer(f)
        if new:
            out.writerow(HEADER)
        out.writerows(
            [now, commit, e['filename'], *(e[k] for k in FIELDS)]
            for e in entries
        )


if __name__ == '__main__':
    main(*sys.argv[1:3])

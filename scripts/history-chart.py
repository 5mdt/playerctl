#!/usr/bin/env python3
"""Chart the test and coverage history CSVs over time.

Usage: history-chart.py TEST_HISTORY.csv COVERAGE_HISTORY.csv OUT.png|OUT.svg

A stacked area per test category, pattern and colour per category. Inside a
category the passed tests keep its colour and the others are drawn on top in a
fixed colour per status (xfailed, skipped, error, failed). The height of the
stack at each run is that run's line coverage (0-100%), split between the
categories and statuses by their share of the tests. That split is a rough
picture, not a measurement: coverage is not attributable to a category. Runs
are matched by commit.
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime

import matplotlib

matplotlib.use('Agg')
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import PercentFormatter  # noqa: E402

BACKGROUND = '#eceff4'
# one per category in sorted order, so neighbours differ in colour and pattern
HATCHES = ['', '/', '\\', '|', '-', '+', 'x']
# bottom to top within a category; passed takes the (subtle) colour of the
# category, the others are bright so that they stand out
STATUSES = {
    'passed': None,
    'xfailed': '#ffd800',
    'skipped': '#1e90ff',
    'error': '#ff7a00',
    'failed': '#ff1a1a',
}


def main(tests, coverage, output):
    with open(coverage, newline='') as f:
        line_percent = {
            r['commit']: float(r['line_percent'])
            for r in csv.DictReader(f)
            if r['file'] == 'TOTAL'
        }
    times, counts = {}, defaultdict(dict)
    with open(tests, newline='') as f:
        for r in csv.DictReader(f):
            commit = r['commit']
            if commit not in line_percent:
                continue
            if r['category'] == 'TOTAL':
                times[commit] = datetime.fromisoformat(r['time'])
            else:
                counts[r['category'], commit] = r
    commits = list(times)
    names = sorted({name for name, _ in counts})
    total = {
        c: sum(int(counts[n, c]['total']) for n in names if (n, c) in counts)
        for c in commits
    }

    palette = plt.get_cmap('Pastel1').colors + plt.get_cmap('Pastel2').colors
    stacks, colors, hatches = [], [], []
    for i, name in enumerate(names):
        for status, color in STATUSES.items():
            stacks.append(
                [
                    line_percent[c]
                    * int(
                        counts[name, c][status] if (name, c) in counts else 0
                    )
                    / total[c]
                    for c in commits
                ]
            )
            colors.append(color or palette[i % len(palette)])
            hatches.append(HATCHES[i % len(HATCHES)])

    fig, ax = plt.subplots(figsize=(10, 5), facecolor=BACKGROUND)
    ax.set_facecolor(BACKGROUND)
    areas = ax.stackplot(list(times.values()), stacks, colors=colors)
    for area, hatch in zip(areas, hatches):
        area.set_hatch(hatch)
        area.set_edgecolor((0, 0, 0, 0.4))
        area.set_linewidth(0)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_title('Line coverage, split by test category and status')
    categories = [
        Patch(
            facecolor=palette[i % len(palette)],
            edgecolor=(0, 0, 0, 0.4),
            hatch=HATCHES[i % len(HATCHES)],
            label=name,
        )
        for i, name in enumerate(names)
    ]
    others = [
        Patch(facecolor=color, label=f'{status} (any category)')
        for status, color in STATUSES.items()
        if color
    ]
    ax.legend(
        handles=categories[::-1] + others[::-1],
        loc='center left',
        bbox_to_anchor=(1.01, 0.5),
        frameon=False,
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d %H:%M'))
    fig.autofmt_xdate()
    fig.savefig(output, dpi=120, bbox_inches='tight')
    print(f'wrote {output}')


if __name__ == '__main__':
    main(*sys.argv[1:4])

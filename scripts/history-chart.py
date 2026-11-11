#!/usr/bin/env python3
"""Chart the test and coverage history CSVs over time.

Usage: history-chart.py TEST_HISTORY.csv COVERAGE_HISTORY.csv OUT.png|OUT.svg

One position per test run, evenly spaced on the x axis (labelled by the
run's commit, dates above the plot). A stacked area per test category, pattern
and colour per category. Inside a category the passed tests keep its colour and the others are drawn on top in a
fixed colour per status (xfailed, skipped, error, failed). The height of the
stack at each run is that run's line coverage (0-100%), split between the
categories and statuses by their share of the tests. A non-passed status that
occurs is always at least one pixel tall. The legend shows the test counts of
the last run. That split is a rough
picture, not a measurement: coverage is not attributable to a category. A test
run is matched with the coverage run of the same commit (the n-th with the
n-th).
"""

import csv
import sys
from collections import defaultdict
from datetime import datetime

import matplotlib

matplotlib.use('Agg')
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
        percents = defaultdict(list)
        for r in csv.DictReader(f):
            if r['file'] == 'TOTAL':
                percents[r['commit']].append(float(r['line_percent']))
    # one run per (time, commit) in the test history; the n-th run of a commit
    # is matched with the n-th coverage run of that commit
    by_run, per_commit = {}, defaultdict(int)
    with open(tests, newline='') as f:
        for r in csv.DictReader(f):
            key = r['time'], r['commit']
            if key not in by_run:
                n = per_commit[r['commit']]
                per_commit[r['commit']] += 1
                if n >= len(percents[r['commit']]):
                    continue
                by_run[key] = {'percent': percents[r['commit']][n]}
            if key in by_run and r['category'] != 'TOTAL':
                by_run[key][r['category']] = r
    runs = list(by_run)
    names = sorted(
        {name for run in by_run.values() for name in run} - {'percent'}
    )
    total = {
        k: sum(int(run[n]['total']) for n in names if n in run)
        for k, run in by_run.items()
    }

    palette = plt.get_cmap('Pastel1').colors + plt.get_cmap('Pastel2').colors
    fig, ax = plt.subplots(figsize=(10, 5), facecolor=BACKGROUND, dpi=120)
    ax.set_facecolor(BACKGROUND)
    # one pixel of height in data units (the y axis spans 0-100)
    min_h = 100 / ax.bbox.height
    stacks, colors, hatches = [], [], []
    for i, name in enumerate(names):
        cols = {s: [] for s in STATUSES}
        for k in runs:
            count = {
                s: int(by_run[k][name][s]) if name in by_run[k] else 0
                for s in STATUSES
            }
            vals = {
                s: by_run[k]['percent'] * count[s] / total[k] for s in STATUSES
            }
            # a non-passed status that is present is at least 1 px tall; the
            # extra height is taken from the passed band of the same category
            for s in STATUSES:
                if s != 'passed' and count[s] and vals[s] < min_h:
                    vals['passed'] = max(
                        0.0, vals['passed'] - (min_h - vals[s])
                    )
                    vals[s] = min_h
            for s in STATUSES:
                cols[s].append(vals[s])
        for status, color in STATUSES.items():
            stacks.append(cols[status])
            colors.append(color or palette[i % len(palette)])
            hatches.append(HATCHES[i % len(HATCHES)])

    positions = list(range(len(runs)))
    areas = ax.stackplot(positions, stacks, colors=colors)
    for area, hatch in zip(areas, hatches):
        area.set_hatch(hatch)
        area.set_edgecolor((0, 0, 0, 0.4))
        area.set_linewidth(0)
    ax.set_ylim(0, 100)
    ax.yaxis.set_major_formatter(PercentFormatter(decimals=0))
    ax.set_title('Line coverage, split by test category and status')
    last = by_run[runs[-1]]

    def last_count(name):
        return int(last[name]['total']) if name in last else 0

    def status_count(status):
        return sum(int(last[n][status]) for n in names if n in last)

    categories = [
        Patch(
            facecolor=palette[i % len(palette)],
            edgecolor=(0, 0, 0, 0.4),
            hatch=HATCHES[i % len(HATCHES)],
            label=f'{name} ({last_count(name)})',
        )
        for i, name in enumerate(names)
    ]
    others = [
        Patch(facecolor=color, label=f'{status} ({status_count(status)})')
        for status, color in STATUSES.items()
        if color
    ]
    ax.legend(
        handles=categories[::-1] + others[::-1],
        loc='center left',
        bbox_to_anchor=(1.01, 0.5),
        frameon=False,
        title=f'tests in last run ({runs[-1][1]})',
    )
    ax.set_xlim(0, max(len(runs) - 1, 1))
    ax.set_xticks(positions, [c for _, c in runs], rotation=90, fontsize=7)
    first_of_day = {}
    for i, (time, _) in enumerate(runs):
        first_of_day.setdefault(datetime.fromisoformat(time).date(), i)
    dates = ax.secondary_xaxis('top')
    dates.set_xticks(
        list(first_of_day.values()),
        [d.isoformat() for d in first_of_day],
        fontsize=8,
    )
    for i in list(first_of_day.values())[1:]:
        ax.axvline(i, color='black', alpha=0.25, linestyle=':', linewidth=1)
    fig.savefig(output, dpi=120, bbox_inches='tight')
    print(f'wrote {output}')


if __name__ == '__main__':
    main(*sys.argv[1:4])

#!/usr/bin/env python3
"""Write a summary badge (SVG) from the latest run in the test history CSV.

Usage: test-badge.py TEST_HISTORY.csv OUT.svg

Grey: "tests" and the total number of tests. Red: the number of failed and
errored tests, left out when there are none.
"""

import csv
import sys
from xml.sax.saxutils import escape

GREY, LIGHT_GREY, RED = '#555', '#9f9f9f', '#e05d44'
HEIGHT = 20


def badge(segments):
    """A flat two or three part badge from [(text, colour), ...]."""
    widths = [round(10 + 6.6 * len(text)) for text, _ in segments]
    label = ' '.join(text for text, _ in segments)
    parts, x = [], 0
    for (text, color), width in zip(segments, widths):
        middle = x + width / 2
        parts.append(
            f'<rect x="{x}" width="{width}" height="{HEIGHT}" fill="{color}"/>'
            f'<text x="{middle}" y="15" fill="#010101" fill-opacity=".3">'
            f'{escape(text)}</text>'
            f'<text x="{middle}" y="14">{escape(text)}</text>'
        )
        x += width
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{x}" '
        f'height="{HEIGHT}" role="img" aria-label="{escape(label)}">'
        f'<clipPath id="r"><rect width="{x}" height="{HEIGHT}" rx="3"/>'
        '</clipPath>'
        '<g clip-path="url(#r)" fill="#fff" text-anchor="middle" '
        'font-family="Verdana,DejaVu Sans,sans-serif" font-size="11">'
        + ''.join(parts)
        + '</g></svg>\n'
    )


def main(history, output):
    with open(history, newline='') as f:
        total = [r for r in csv.DictReader(f) if r['category'] == 'TOTAL'][-1]
    failing = int(total['failed']) + int(total['error'])
    segments = [('tests', GREY), (f"{total['total']} total", LIGHT_GREY)]
    if failing:
        segments.append((str(failing), RED))
    with open(output, 'w') as f:
        f.write(badge(segments))
    print(f'wrote {output}')


if __name__ == '__main__':
    main(*sys.argv[1:3])

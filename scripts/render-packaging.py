#!/usr/bin/env python3
"""Render the package manifests from packaging/package.yaml.

The templates in packaging/templates/ (PKGBUILD, debian/, the rpm spec and
the distro variables for the Makefile) are rendered into OUT, together with
matrix.json, the list of distros for the CI matrix. The version comes from
meson.build, the release notes from doc/CHANGELOG.md and the date from
SOURCE_DATE_EPOCH or the HEAD commit, so nothing is written down twice.

Usage: scripts/render-packaging.py [--out OUT] [--sha256 SUM]
       scripts/render-packaging.py --sync | --check

With --sha256 the PKGBUILD gets the checksum of the release tarball instead
of SKIP. With --sync the version in meson.build, pyproject.toml and uv.lock
and the distro table in doc/installing.md are rewritten; with --check nothing
is written and the exit status is 1 if any of them is out of date.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
from email.utils import format_datetime
from pathlib import Path

import jinja2
import yaml

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / 'packaging'
TEMPLATES = PACKAGING / 'templates'
INSTALLING = ROOT / 'doc' / 'installing.md'
TABLE = re.compile(
    r'(<!-- BEGIN distro-table -->\n\n).*?(\n<!-- END distro-table -->)',
    re.S,
)
# templates that are not part of the manifests
DOC_TEMPLATES = 'docs'


# files that hold a copy of the version, and the pattern of the line to change:
# group 1 is everything before the version, group 2 what follows it
VERSION_FILES = {
    'meson.build': r"(\A.*?^  version: ')[^']*(')",
    'pyproject.toml': r'(^\[project\].*?^version = ")[^"]*(")',
    'uv.lock': r'(^name = "playerctl-tests"\nversion = ")[^"]*(")',
}


def changelog_entries(version):
    """The bullets of the section of VERSION in doc/CHANGELOG.md."""
    entries = []
    found = False
    for line in (ROOT / 'doc' / 'CHANGELOG.md').read_text().splitlines():
        if line.startswith('## '):
            found = line == f'## Version {version}'
        elif found and line.startswith('- '):
            entries.append(line[2:].strip())
    if not entries:
        sys.exit(f'no "## Version {version}" section in doc/CHANGELOG.md')
    return entries


def release_date():
    epoch = os.environ.get('SOURCE_DATE_EPOCH')
    if epoch is None:
        epoch = subprocess.run(
            ['git', 'log', '-1', '--format=%ct'],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    return datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc)


def meson_flags(options):
    values = {True: 'true', False: 'false'}
    return ' '.join(
        f'-D{key}={values.get(value, value)}' for key, value in options.items()
    )


def wrap(text, width, indent=''):
    return textwrap.fill(
        text, width, initial_indent=indent, subsequent_indent=indent
    )


def environment():
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters['upfirst'] = lambda text: text[:1].upper() + text[1:]
    env.filters['wrap'] = wrap
    return env


def load_context(sha256=None):
    with open(PACKAGING / 'package.yaml') as f:
        ctx = yaml.safe_load(f)
    version = str(ctx['version'])
    major = version.split('.')[0]
    date = release_date()
    distros = []
    for key, distro in ctx['distros'].items():
        glob = ctx['package_globs'][distro['type']]
        distros.append(
            {
                'id': key,
                'title': distro['title'],
                'type': distro['type'],
                'images': distro['image'],
                'install_cmd': f'`{distro["install"]} ./{key}_{glob}`',
            }
        )
    ctx.update(
        # libplayerctl.so.<soversion> and Playerctl-<api_version>.typelib
        soversion=major,
        api_version=f'{major}.0',
        date_rfc2822=format_datetime(date),
        date_rpm=date.strftime('%a %b %d %Y'),
        meson_flags=meson_flags(ctx['meson_options']),
        sha256=sha256 and f"'{sha256}'",
        distros=distros,
    )
    return ctx


def render_manifests(out, ctx):
    ctx = {**ctx, 'changelog': changelog_entries(ctx['version'])}
    env = environment()
    # file names carry no template syntax, only these tokens
    name_tokens = {
        '_soversion': ctx['soversion'],
        '_api_version': '-' + ctx['api_version'],
    }
    if out.exists():
        shutil.rmtree(out)
    for template in sorted(TEMPLATES.rglob('*.j2')):
        relative = template.relative_to(TEMPLATES)
        if relative.parts[0] == DOC_TEMPLATES:
            continue
        name = relative.as_posix()[: -len('.j2')]
        for token, value in name_tokens.items():
            name = name.replace(token, value)
        target = out / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(env.get_template(relative.as_posix()).render(ctx))
        target.chmod(template.stat().st_mode & 0o777)
    matrix = [d['id'] for d in ctx['distros']]
    (out / 'matrix.json').write_text(json.dumps(matrix) + '\n')


def render_table(ctx):
    distros = ctx['distros']
    return (
        environment()
        .get_template(f'{DOC_TEMPLATES}/installing-table.md.j2')
        .render(
            distros=distros,
            w_title=max(
                len(d['title']) for d in distros + [{'title': 'Distribution'}]
            ),
            w_cmd=max(len(d['install_cmd']) for d in distros),
        )
    )


def sync(ctx, check):
    """Update the copies of generated content; with CHECK only report."""
    stale = False
    for name in [*VERSION_FILES, 'doc/installing.md']:
        path = ROOT / name
        text = path.read_text()
        if name == 'doc/installing.md':
            if not TABLE.search(text):
                sys.exit(f'{name}: no distro-table markers')
            new = TABLE.sub(
                lambda m: m.group(1) + render_table(ctx) + m.group(2), text
            )
        else:
            new, count = re.subn(
                VERSION_FILES[name],
                lambda m: m.group(1) + str(ctx['version']) + m.group(2),
                text,
                count=1,
                flags=re.S | re.M,
            )
            if not count:
                sys.exit(f'{name}: no version found')
        if new == text:
            continue
        if check:
            stale = True
            sys.stdout.writelines(
                difflib.unified_diff(
                    text.splitlines(True), new.splitlines(True), name, 'new'
                )
            )
        else:
            path.write_text(new)
    if stale:
        print('out of date, run make manifests-sync', file=sys.stderr)
    return int(stale)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--out', type=Path, default=ROOT / 'build/packaging')
    parser.add_argument('--sha256')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--sync', action='store_true')
    group.add_argument('--check', action='store_true')
    args = parser.parse_args()

    ctx = load_context(args.sha256)
    if args.sync or args.check:
        return sync(ctx, args.check)
    render_manifests(args.out, ctx)
    return 0


if __name__ == '__main__':
    sys.exit(main())

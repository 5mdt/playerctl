#!/usr/bin/env python3
"""Add contributors to the C code found in the git history to CONTRIBUTORS.md.

Only commits touching C sources (*.c, *.h) count. Authors and
Co-authored-by trailers are collected (respecting .mailmap).
People already listed are matched by email or by name and left as they are.
The whole list is re-sorted on last names on every run; existing records are
never removed.

Usage: scripts/update-contributors.py [--check | --duplicates]

With --check nothing is written; the exit status is 1 if anyone is missing
or the list is not sorted.
With --duplicates nothing is written; identities that look like the same
person (in CONTRIBUTORS.md or the git history) are listed, and the exit status
is 1 if there are any. Merge them with a .mailmap entry.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTRIBUTORS = ROOT / 'CONTRIBUTORS.md'

# only commits touching these paths make someone a contributor
C_SOURCES = ['*.c', '*.h']

# trailing words that are not part of the last name when sorting
NAME_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'phd', 'md'}
NOREPLY = re.compile(
    r'^(?:\d+\+)?(?P<user>[^@]+)@users\.noreply\.github\.com$', re.I
)

BULLET = re.compile(r'^[-*]\s+')
# `Name <email>` in git output; `- Name email` in CONTRIBUTORS.md (markdownfmt
# drops the angle brackets of an autolink)
ENTRY = re.compile(
    r'^(?:[-*]\s+)?(?P<name>.+?)\s+<?(?P<email>[^\s<>@]+@[^\s<>]+)>?\s*$'
)
TRAILER = re.compile(r'^co-authored-by:\s*(.+)$', re.IGNORECASE)

# not people: the repository itself, tooling and AI assistants
IGNORED_EMAILS = {'noreply@github.com'}
IGNORED_EMAIL_DOMAINS = (
    '@anthropic.com',
    '@openai.com',
    '@cursor.com',
    '@codeium.com',
    '@windsurf.com',
    '@aider.chat',
    '@devin.ai',
    '@sourcegraph.com',
    '@replit.com',
    '@tabnine.com',
    '@qodo.ai',
    '@x.ai',
    '@mistral.ai',
    '@deepseek.com',
)
IGNORED_NAMES = re.compile(
    r'\[bot\]'
    r'|^(github-actions|dependabot|renovate)\b'
    r'|^(claude|chatgpt|codex|copilot|github copilot|gemini|cursor( agent)?'
    r'|aider|devin|windsurf|codeium|cody|amazon q|q developer|jules'
    r'|openhands|continue|grok|mistral|deepseek|qwen|llama|tabnine|qodo|sourcery|replit)\b',
    re.IGNORECASE,
)


def git_log():
    # %aN/%aE honour .mailmap; the body is searched for Co-authored-by
    out = subprocess.run(
        ['git', 'log', '--format=%aN <%aE>%n%b%x00', '--', *C_SOURCES],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for commit in out.split('\0'):
        lines = commit.strip().splitlines()
        if not lines:
            continue
        yield lines[0]
        for line in lines[1:]:
            match = TRAILER.match(line.strip())
            if match:
                yield match.group(1)


def parse(person):
    match = ENTRY.match(person.strip())
    if not match:
        return None
    name, email = match.group('name').strip(), match.group('email').strip()
    if (
        email.lower() in IGNORED_EMAILS
        or email.lower().endswith(IGNORED_EMAIL_DOMAINS)
        or IGNORED_NAMES.search(name)
    ):
        return None
    return name, email


def last_name(name):
    words = name.split()
    while len(words) > 1 and words[-1].strip('.,').casefold() in NAME_SUFFIXES:
        words.pop()
    return words[-1].casefold()


def sort_key(entry):
    name = entry[0]
    return (last_name(name), name.casefold())


def squash(text):
    """Compare names regardless of case, spacing and punctuation."""
    return re.sub(r'[\W_]+', '', text.casefold())


def identity_keys(name, email):
    keys = {('email', email.casefold()), ('name', squash(name))}
    noreply = NOREPLY.match(email)
    if noreply:
        # a GitHub noreply address names the account, which may be the
        # handle someone else used as their git name
        keys.add(('name', squash(noreply.group('user'))))
    return keys


def find_duplicates(identities):
    """Group (name, email, where) identities that share an email or a name."""
    parent = list(range(len(identities)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen = {}
    for i, (name, email, _) in enumerate(identities):
        for key in identity_keys(name, email):
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i

    groups = {}
    for i, identity in enumerate(identities):
        groups.setdefault(find(i), []).append(identity)
    return [
        sorted(group, key=lambda g: (sort_key(g), g[1].casefold()))
        for group in groups.values()
        if len({(name, email.casefold()) for name, email, _ in group}) > 1
    ]


def report_duplicates(entries):
    identities = [(n, e, 'CONTRIBUTORS.md') for n, e in entries]
    identities += [
        (n, e, 'git history')
        for n, e in sorted(
            {p for p in map(parse, git_log()) if p}, key=sort_key
        )
    ]
    # the same identity in the file and in the history is not a duplicate
    unique = {}
    for name, email, where in identities:
        unique.setdefault((name, email.casefold()), (name, email, where))
    groups = find_duplicates(list(unique.values()))
    for group in sorted(groups, key=lambda g: sort_key(g[0])):
        print('possible duplicates:')
        for name, email, where in group:
            print(f'  {name} <{email}> ({where})')
    if not groups:
        print('no duplicates found')
    return 1 if groups else 0


def read_file():
    """Split the file into the text before the list, the list and the rest."""
    lines = CONTRIBUTORS.read_text().splitlines()
    parsed = [parse(BULLET.sub('', line)) for line in lines]
    found = [i for i, person in enumerate(parsed) if person]
    if not found:
        return lines, [], []
    first, last = found[0], found[-1]
    entries = [parsed[i] for i in found]
    return lines[:first], entries, lines[last + 1 :]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument(
        '--check',
        action='store_true',
        help='do not write; exit 1 if contributors are missing',
    )
    parser.add_argument(
        '--duplicates',
        action='store_true',
        help='do not write; list identities that look like the same person',
    )
    args = parser.parse_args()

    header, entries, footer = read_file()
    if args.duplicates:
        return report_duplicates(entries)
    emails = {email.casefold() for _, email in entries}
    names = {name.casefold() for name, _ in entries}

    missing = []
    for person in map(parse, git_log()):
        if person is None:
            continue
        name, email = person
        if email.casefold() in emails or name.casefold() in names:
            continue
        emails.add(email.casefold())
        names.add(name.casefold())
        missing.append(person)

    for name, email in sorted(missing, key=sort_key):
        print(f'{"missing" if args.check else "adding"}: {name} <{email}>')

    entries = sorted(entries + missing, key=sort_key)
    # markdownfmt drops the angle brackets, so write what it would
    lines = header + [f'- {name} {email}' for name, email in entries] + footer
    text = '\n'.join(lines) + '\n'
    unsorted = text != CONTRIBUTORS.read_text()

    if not missing and not unsorted:
        print('CONTRIBUTORS.md is up to date')
        return 0
    if args.check:
        if unsorted and not missing:
            print('CONTRIBUTORS.md is not sorted')
        return 1
    if unsorted and not missing:
        print('sorting CONTRIBUTORS.md')
    CONTRIBUTORS.write_text(text)
    return 0


if __name__ == '__main__':
    sys.exit(main())

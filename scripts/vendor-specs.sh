#!/usr/bin/env bash
# Re-download every vendored specification document at its pinned revision into
# doc/specs/ and write a SOURCE file next to each set. Run `make vendor-specs`.
#
# To update a spec: change the pinned revision below, run the script, review
# `git diff doc/specs`, and update doc/specs/README.md.
set -euo pipefail

# --- pinned revisions --------------------------------------------------------
MPRIS_REV=84d2ccffdf8f5395f34e1ca2ce4ffeb42f196900   # 2026-02-24, spec v2.3 (unreleased)
DBUS_REV=166d90ba6aab797bc0c32b7576cd9c76eeec5c7f    # 2026-09-21, spec v0.43
METADATA_URL=https://www.freedesktop.org/wiki/Specifications/mpris-spec/metadata/

MPRIS_FILES=(
  all.xml
  org.mpris.MediaPlayer2.xml
  org.mpris.MediaPlayer2.Player.xml
  org.mpris.MediaPlayer2.TrackList.xml
  org.mpris.MediaPlayer2.Playlists.xml
)

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
tmp="$root/build/specs-tmp"
dest="$root/doc/specs"

rm -rf "$tmp"
mkdir -p "$tmp/mpris" "$tmp/dbus" "$tmp/mpris-metadata"

fetch() { curl --fail --silent --show-error --location --output "$2" "$1"; }

mpris_raw=https://gitlab.freedesktop.org/mpris/mpris-spec/-/raw/$MPRIS_REV
dbus_raw=https://gitlab.freedesktop.org/dbus/dbus/-/raw/$DBUS_REV

for f in "${MPRIS_FILES[@]}"; do
  fetch "$mpris_raw/spec/$f" "$tmp/mpris/$f"
done
fetch "$mpris_raw/COPYING" "$tmp/mpris/COPYING"

fetch "$dbus_raw/doc/dbus-specification.xml" "$tmp/dbus/dbus-specification.xml"
fetch "$dbus_raw/COPYING" "$tmp/dbus/COPYING"

# The wiki page is a snapshot of a living document: prepend a source comment.
{
  printf '<!-- Source: %s -->\n' "$METADATA_URL"
  curl --fail --silent --show-error --location "$METADATA_URL"
} > "$tmp/mpris-metadata/metadata.html"

cat > "$tmp/mpris/SOURCE" <<EOF
Document: MPRIS D-Bus Interface Specification (spec/*.xml, COPYING)
Source:   https://gitlab.freedesktop.org/mpris/mpris-spec/-/tree/$MPRIS_REV/spec
Revision: $MPRIS_REV (2026-02-24, spec version 2.3, unreleased)
License:  LGPL-2.1-or-later (see COPYING)
Files are byte-identical to upstream. Update with scripts/vendor-specs.sh.
EOF

cat > "$tmp/dbus/SOURCE" <<EOF
Document: D-Bus Specification (doc/dbus-specification.xml, COPYING)
Source:   https://gitlab.freedesktop.org/dbus/dbus/-/blob/$DBUS_REV/doc/dbus-specification.xml
Revision: $DBUS_REV (2026-09-21, spec version 0.43)
License:  AFL-2.1 OR GPL-2.0-or-later (see COPYING)
Files are byte-identical to upstream. Update with scripts/vendor-specs.sh.
EOF

cat > "$tmp/mpris-metadata/SOURCE" <<EOF
Document: MPRIS v2 metadata guidelines (Xesam / mpris: keys)
Source:   $METADATA_URL
Fetched:  $(date -u +%Y-%m-%d)
License:  freedesktop.org wiki content (no license stated upstream)
The page is a snapshot with a source comment prepended. Update with scripts/vendor-specs.sh.
EOF

mkdir -p "$dest"
for d in mpris dbus mpris-metadata; do
  rm -rf "${dest:?}/$d"
  cp -r "$tmp/$d" "$dest/$d"
done

python3 "$root/scripts/gen-mpris-interface.py"

git -C "$root" diff --stat -- doc/specs data || true

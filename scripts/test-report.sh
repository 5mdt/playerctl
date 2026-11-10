#!/bin/bash
# Usage: test-report.sh BUILD_DIR [pytest args]
#
# Runs inside the playerctl-test image: the C unit tests (meson test in
# BUILD_DIR) and the pytest suite, then a per-category outcome table from their
# JUnit XML. The XML files and the table go to /out. With RECORD_HISTORY set the
# run is also appended to test/test_history.csv (tracked in git, mounted rw; the
# Makefile restores it from HEAD first, so a commit holds one run).
set -u
build=$1
shift
status=0
meson test -C "$build" --print-errorlogs || status=1
cp "$build/meson-logs/testlog.junit.xml" /out/meson.xml || status=1
dbus-daemon --nopidfile --system
dbus-run-session python3 -m pytest -q -p no:cacheprovider --junitxml=/out/pytest.xml -o junit_family=xunit2 "$@" || status=1
uv run --no-project --with junitparser python3 scripts/junit-summary.py --csv "${RECORD_HISTORY:+test/test_history.csv}" /out/pytest.xml /out/meson.xml | tee /out/summary.txt
exit $status

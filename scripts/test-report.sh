#!/bin/bash
# Usage: test-report.sh BUILD_DIR [pytest args]
#
# Runs inside the playerctl-test image (repo mounted in the working directory): the C unit tests (meson test in
# BUILD_DIR, built here if needed) and the pytest suite, then a per-category outcome table from their
# JUnit XML. The XML files and the table go to /out. With RECORD_HISTORY set the
# run is also appended to test/test_history.csv (tracked in git, mounted rw; the
# Makefile restores it from HEAD first, so a commit holds one run).
set -u
build=$1
shift
status=0
# build (incrementally) when the caller has not, see test-build.sh
. scripts/test-build.sh
test_build "$build" || exit 1
meson test -C "$build" --print-errorlogs || status=1
cp "$build/meson-logs/testlog.junit.xml" /out/meson.xml || status=1
dbus-daemon --nopidfile --system
# The tests are independent (each has its own session bus), so they run in
# parallel: PYTEST_WORKERS (default 4; 0 = no xdist; more workers make the timing
# sensitive tests flaky on an 8 CPU machine). The ones
# marked "serial" (memory and timing measurements) run alone afterwards.
pytest=(python3 -m pytest -q -p no:cacheprovider -o junit_family=xunit2)
if [ "${PYTEST_WORKERS:-4}" = 0 ]; then
	dbus-run-session "${pytest[@]}" --junitxml=/out/pytest.xml "$@" || status=1
	xml=(/out/pytest.xml)
else
	dbus-run-session "${pytest[@]}" -n "${PYTEST_WORKERS:-4}" -m 'not serial' --junitxml=/out/pytest.xml "$@" || status=1
	dbus-run-session "${pytest[@]}" -m serial --junitxml=/out/pytest-serial.xml "$@"
	rc=$?
	# 5: nothing selected (the arguments left out every serial test)
	[ "$rc" -eq 0 ] || [ "$rc" -eq 5 ] || status=1
	xml=(/out/pytest.xml /out/pytest-serial.xml)
fi
uv run --no-project --with junitparser python3 scripts/junit-summary.py --csv "${RECORD_HISTORY:+test/test_history.csv}" "${xml[@]}" /out/meson.xml | tee /out/summary.txt
exit $status

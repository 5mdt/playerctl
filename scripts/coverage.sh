#!/bin/bash
# Runs inside the playerctl-test image: rebuild with gcov instrumentation,
# install over the stock build, run the suite and write gcovr reports to
# /out (mounted from build/coverage on the host).
set -u
rm -rf build-cov
meson setup --prefix=/usr -Db_coverage=true build-cov >/dev/null
ninja -C build-cov >/dev/null
ninja -C build-cov install >/dev/null
# C unit tests (test/c): run first so gcov sees them; failures must not stop the reports but still fail the script
status=0
meson test -C build-cov --print-errorlogs || status=1
dbus-daemon --nopidfile --system
dbus-run-session python3 -m pytest -q -p no:cacheprovider "$@" || status=1
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --txt --txt-metric branch -o /out/report-branch.txt
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --txt -o /out/report.txt
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --html-details -o /out/report.html
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --cobertura -o /out/coverage.xml
cat /out/report.txt
exit $status

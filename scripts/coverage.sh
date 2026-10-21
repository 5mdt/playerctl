#!/bin/bash
# Runs inside the playerctl-test image: rebuild with gcov instrumentation,
# install over the stock build, run the suite and write gcovr reports to
# /out (mounted from build/coverage on the host).
set -u
rm -rf build-cov
meson setup --prefix=/usr -Db_coverage=true build-cov >/dev/null
ninja -C build-cov >/dev/null
ninja -C build-cov install >/dev/null
# C unit tests first so gcov sees them; failures must not stop the reports but still fail the script
status=0
bash scripts/test-report.sh build-cov "$@" || status=1
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --txt --txt-metric branch -o /out/report-branch.txt
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --txt -o /out/report.txt
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --html-details -o /out/report.html
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --cobertura -o /out/coverage.xml
uv run --no-project --with gcovr gcovr -r . --object-directory build-cov \
	--filter 'playerctl/.*' --json-summary /out/coverage-summary.json
[ -n "${RECORD_HISTORY:-}" ] && python3 scripts/coverage-history.py /out/coverage-summary.json test/coverage_history.csv
cat /out/report.txt
exit $status

#!/bin/bash
# Runs inside the playerctl-test image: build with gcov instrumentation
# (incrementally, in build/test/cov), install it, run the suite and write gcovr reports to
# /out (mounted from build/coverage on the host).
set -u
cov=build/test/cov
. scripts/test-build.sh
test_build "$cov" -Db_coverage=true || exit 1
# the build is kept between runs: drop the counters of the last one
find "$cov" -name '*.gcda' -delete
# C unit tests first so gcov sees them; failures must not stop the reports but still fail the script
status=0
bash scripts/test-report.sh "$cov" "$@" || status=1
uv run --no-project --with gcovr gcovr -r . --object-directory "$cov" \
	--filter 'playerctl/.*' --txt --txt-metric branch -o /out/report-branch.txt
uv run --no-project --with gcovr gcovr -r . --object-directory "$cov" \
	--filter 'playerctl/.*' --txt -o /out/report.txt
uv run --no-project --with gcovr gcovr -r . --object-directory "$cov" \
	--filter 'playerctl/.*' --html-details -o /out/report.html
uv run --no-project --with gcovr gcovr -r . --object-directory "$cov" \
	--filter 'playerctl/.*' --cobertura -o /out/coverage.xml
uv run --no-project --with gcovr gcovr -r . --object-directory "$cov" \
	--filter 'playerctl/.*' --json-summary /out/coverage-summary.json
[ -n "${RECORD_HISTORY:-}" ] && python3 scripts/coverage-history.py /out/coverage-summary.json test/coverage_history.csv
cat /out/report.txt
exit $status

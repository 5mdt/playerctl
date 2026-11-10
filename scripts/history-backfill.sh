#!/bin/bash
# Usage: history-backfill.sh [N]
#
# Measures the last N first-parent commits (default 8) with the current report
# harness, one after the other in the playerctl-test image, and rewrites
# test/test_history.csv and test/coverage_history.csv with those runs, oldest
# first. Rows carry the commit and its commit date. Snapshots and logs are in
# build/backfill/<commit>. A commit whose tests fail is recorded like any other.
set -u
count=${1:-8}
engine=${CONTAINER_ENGINE:-podman}
out=build/backfill
rm -rf "$out"
shas=$(git rev-list --first-parent -n "$count" HEAD | tac)
for sha in $shas; do
	dir=$out/$sha
	mkdir -p "$dir/src" "$dir/out"
	git archive "$sha" | tar -x -C "$dir/src"
	rm -f "$dir/src/test/test_history.csv" "$dir/src/test/coverage_history.csv"
	cp scripts/test-report.sh scripts/coverage.sh scripts/junit-summary.py scripts/coverage-history.py "$dir/src/scripts/"
	sed -i "s/test(name, exe, suite: 'c', timeout: 60)/test(name, exe, args: ['--tap'], protocol: 'tap', suite: 'c', timeout: 60)/" "$dir/src/test/c/meson.build"
	time=$(date -u -d "@$(git show -s --format=%ct "$sha")" +%Y-%m-%dT%H:%M:%S+00:00)
	echo "== $sha $time"
	"$engine" run --rm -v "$PWD/$dir/src:/work:Z" -v "$PWD/$dir/out:/out:Z" -w /work \
		-e GIT_COMMIT="$(git rev-parse --short "$sha")" -e HISTORY_TIME="$time" -e RECORD_HISTORY=1 \
		playerctl-test bash scripts/coverage.sh >"$dir/log.txt" 2>&1
	echo "exit $?"
done
for name in test_history coverage_history; do
	rm -f "test/$name.csv"
	for sha in $shas; do
		file=$out/$sha/src/test/$name.csv
		[ -f "$file" ] || continue
		[ -f "test/$name.csv" ] || head -n1 "$file" >"test/$name.csv"
		tail -n +2 "$file" >>"test/$name.csv"
	done
done

#!/bin/bash
# Runs inside the playerctl-test image: build with AddressSanitizer and
# UBSan, then run the C unit tests and the pytest suites that drive the
# instrumented playerctl and playerctld binaries. Sanitizer reports go to
# /out (mounted from build/asan on the host; the build is kept in build/test/asan). The library (GI) tests are
# skipped: they load libplayerctl into an uninstrumented Python.
set -u
asan=build/test/asan
. scripts/test-build.sh
test_build "$asan" -Dtests=true -Db_sanitize=address,undefined -Db_lundef=false || exit 1
# the sanitizer settings only apply to the runs, not to the build
export ASAN_OPTIONS="detect_leaks=1:halt_on_error=1:print_summary=1:log_path=/out/asan"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1:log_path=/out/ubsan"
export LSAN_OPTIONS="suppressions=$PWD/test/data/lsan.supp"
export G_SLICE=always-malloc
status=0
bash scripts/test-report.sh "$asan" --ignore=test/us11_library "$@" || status=1
echo "sanitizer reports: $(find /out -name 'asan.*' -o -name 'ubsan.*' | wc -l) file(s) in build/asan"
exit $status

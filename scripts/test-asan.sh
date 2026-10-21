#!/bin/bash
# Runs inside the playerctl-test image: build with AddressSanitizer and
# UBSan, then run the C unit tests and the pytest suites that drive the
# instrumented playerctl and playerctld binaries. Sanitizer reports go to
# /out (mounted from build/asan on the host). The library (GI) tests are
# skipped: they load libplayerctl into an uninstrumented Python.
set -u
rm -rf build-asan
meson setup -Dtests=true -Db_sanitize=address,undefined -Db_lundef=false build-asan >/dev/null
ninja -C build-asan >/dev/null
export ASAN_OPTIONS="detect_leaks=1:halt_on_error=1:print_summary=1:log_path=/out/asan"
export UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1:log_path=/out/ubsan"
export LSAN_OPTIONS="suppressions=/app/test/data/lsan.supp"
export G_SLICE=always-malloc
export PATH=/app/build-asan/playerctl:$PATH
export LD_LIBRARY_PATH=/app/build-asan/playerctl
status=0
bash scripts/test-report.sh build-asan --ignore=test/us11_library "$@" || status=1
echo "sanitizer reports: $(find /out -name 'asan.*' -o -name 'ubsan.*' | wc -l) file(s) in build/asan"
exit $status

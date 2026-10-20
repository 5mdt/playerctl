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
status=0
meson test -C build-asan --print-errorlogs || status=1
export PATH=/app/build-asan/playerctl:$PATH
export LD_LIBRARY_PATH=/app/build-asan/playerctl
dbus-daemon --nopidfile --system
dbus-run-session python3 -m pytest -q -p no:cacheprovider --ignore=test/us11_library "$@" || status=1
echo "sanitizer reports: $(find /out -type f | wc -l) file(s) in build/asan"
exit $status

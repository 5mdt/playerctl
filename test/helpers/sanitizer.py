"""Detect a sanitizer-instrumented run (scripts/test-asan.sh exports ASAN_OPTIONS)."""

import os

import pytest


def skip_rss_check_under_asan():
    """Skip a test that asserts on process memory growth when run under ASan.

    ASan keeps freed blocks in a quarantine (and pads allocations), so the
    resident size of the instrumented playerctl/playerctld grows by tens of MB
    without any leak. The leak itself is covered by LeakSanitizer.
    """
    if os.environ.get('ASAN_OPTIONS'):
        pytest.skip('RSS growth is dominated by the ASan quarantine')


def under_asan():
    return bool(os.environ.get('ASAN_OPTIONS'))


def xfail_under_asan(request, reason):
    """Mark the running test as a strict xfail only in a sanitizer run.

    For defects that are undefined behaviour: the plain build wraps or ignores
    them silently (test passes), while UBSan aborts the process.
    """
    if under_asan():
        request.applymarker(pytest.mark.xfail(strict=True, reason=reason))

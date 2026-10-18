"""US-1.3: As a user, I want a player to be skipped when it reports it can't do
the action (`CanPlay`, `CanPause`, `CanGoNext`, ...)."""

import pytest


@pytest.mark.skip(reason='US-1.3: not covered yet')
def test_player_skipped_when_it_cannot(): ...

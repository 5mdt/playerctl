"""US-11.6: As a Python/Lua/JS developer, I want GObject-Introspection
bindings (meson option `introspection`)."""

SYMBOLS = (
    'Player',
    'PlayerManager',
    'PlayerName',
    'Source',
    'LoopStatus',
    'PlaybackStatus',
    'list_players',
)


async def test_typelib_exposes_the_api(gi_run):
    result = await gi_run(f"""
        for symbol in {SYMBOLS!r}:
            out(symbol, hasattr(Playerctl, symbol))
    """)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [f'{s} True' for s in SYMBOLS]

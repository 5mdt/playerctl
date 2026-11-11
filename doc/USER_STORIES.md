# playerctl — application described as user stories

## How to read this

Each story ID has one test file under `test/usNN_<section>/test_usNN_MM_<slug>.py`, shared setup lives in `test/helpers/` (plain code) and `conftest.py` files (fixtures).
- Tests come from the pytest suite in `test/`, which drives the CLI against mock MPRIS players (`test/helpers/mpris.py`) and the library through PyGObject.
- A story with no test has a skip-marked stub in its file.

## What the app is

playerctl controls media players that implement MPRIS (the D-Bus interface Linux media apps use for remote control). It ships three things:
- **`playerctl`**: a command-line tool
- **`playerctld`**: a daemon that tracks which player was active most recently
- **`libplayerctl`**: a GObject library with GObject-Introspection bindings

Personas: **user** (desktop/hotkeys), **bar author** (polybar/waybar scripts), **developer** (uses the library).

---

## 1. Playback control

- <a id="us-1-1"></a>[1.1](#us-1-1) As a user, I want `play`, `pause`, `play-pause` and `stop` so I can control playback from a hotkey
  - [test_us01_01_play_pause_stop.py](../test/us01_playback/test_us01_01_play_pause_stop.py)
- <a id="us-1-2"></a>[1.2](#us-1-2) As a user, I want `next` and `previous` to change track
  - [test_us01_02_next_previous.py](../test/us01_playback/test_us01_02_next_previous.py)
- <a id="us-1-3"></a>[1.3](#us-1-3) As a user, I want a player to be skipped when it reports it can't do the action (`CanPlay`, `CanPause`, `CanGoNext`, …)
  - [test_us01_03_skip_when_cannot.py](../test/us01_playback/test_us01_03_skip_when_cannot.py) — each command vs its gating `Can*` (play/pause/stop/play-pause/next/previous); exit 1 + message, `-s`, fallback to capable player, `-a`
- <a id="us-1-4"></a>[1.4](#us-1-4) As a user, I want `open URI` to open a local file (converted to `file://`) or a remote URL
  - [test_us01_04_open_uri.py](../test/us01_playback/test_us01_04_open_uri.py) — local path to `file://` (escaped), remote/scheme URIs and missing paths as-is, skipped when `CanControl` is false
- <a id="us-1-5"></a>[1.5](#us-1-5) As a scripter, I want a D-Bus error from the player on a command to be reported as "Could not execute command: ..." with exit code 1
  - [test_us01_05_player_error.py](../test/us01_playback/test_us01_05_player_error.py) — mock player raises a D-Bus error on every transport/seek/open/volume/loop/shuffle command; message is shown even with `-s`
- <a id="us-1-6"></a>[1.6](#us-1-6) As a scripter, I want a command to fail cleanly with exit code 1 when the player vanishes mid-command, and to wait for a slow player
  - [test_us01_06_player_vanishes.py](../test/us01_playback/test_us01_06_player_vanishes.py) — every control command with the player's reply held and then the player disconnecting; slow replies still succeed; a player vanishing while it is being connected to
- <a id="us-1-7"></a>[1.7](#us-1-7) As a scripter, I want `play`, `pause`, `play-pause`, `stop`, `next`, `previous` and `open` to reach a player that is slow to answer `Properties.GetAll` at once (issue #10)
  - [test_us01_07_slow_get_all.py](../test/us01_playback/test_us01_07_slow_get_all.py) — a player that never answers `GetAll`; each command still honours its gating `Can*`, skips a player whose `Get` fails or has the wrong type, falls back to a capable player; `status` still waits for a slow player
- <a id="us-1-8"></a>[1.8](#us-1-8) As a scripter, I want a hostile or broken player (lying `Can*`, odd D-Bus errors, missing interfaces or properties, one that dies or never answers, odd bus names, extreme Position/Seeked) to make a command fail with exit 1 at worst, never crash, hang or print GLib CRITICAL noise
  - [test_us01_08_evil_player.py](../test/us01_playback/test_us01_08_evil_player.py) — known failure BUG-E3: a call to a player that never replies is not time-limited

## 2. Seeking and position

- <a id="us-2-1"></a>[2.1](#us-2-1) As a user, I want `position` to print the current position in seconds
  - [test_us02_01_query.py](../test/us02_position/test_us02_01_query.py)
- <a id="us-2-2"></a>[2.2](#us-2-2) As a user, I want `position 30` to jump to an absolute position
  - [test_us02_02_set_absolute.py](../test/us02_position/test_us02_02_set_absolute.py) — absolute `SetPosition` in microseconds with the current trackid (fractions, 0), skipped when `CanSeek` is false, fails without a trackid; also reached by [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py)
- <a id="us-2-3"></a>[2.3](#us-2-3) As a user, I want `position 10+` / `10-` to seek relative to the current position (requires `CanSeek`)
  - [test_us02_03_seek_relative.py](../test/us02_position/test_us02_03_seek_relative.py) — `N+`/`N-` call `Seek` with +/- microseconds (fractions), skipped with exit 1 when `CanSeek` is false, falls back to a seekable player
- <a id="us-2-4"></a>[2.4](#us-2-4) As a user, I want input that isn't a number to be rejected with an error
  - [test_us02_04_invalid_input.py](../test/us02_position/test_us02_04_invalid_input.py) — non-numeric input (`abc`, `x+`, lone sign) exits 1 with "Could not parse position as a number", no D-Bus call
- <a id="us-2-6"></a>[2.6](#us-2-6) As a scripter, I want `position` to follow the documented grammar or reject the input with exit 1 and leave the player untouched, whatever the argument holds
  - [test_us02_06_position_fuzz.py](../test/us02_position/test_us02_06_position_fuzz.py)

## 3. Volume

- <a id="us-3-1"></a>[3.1](#us-3-1) As a user, I want `volume` to print the level (0.0–1.0)
  - [test_us03_01_query.py](../test/us03_volume/test_us03_01_query.py)
- <a id="us-3-2"></a>[3.2](#us-3-2) As a user, I want `volume 0.5` to set the level
  - [test_us03_02_set.py](../test/us03_volume/test_us03_02_set.py)
- <a id="us-3-3"></a>[3.3](#us-3-3) As a user, I want `volume 0.1+` / `0.1-` to change the level relative to the current one
  - [test_us03_03_adjust_relative.py](../test/us03_volume/test_us03_03_adjust_relative.py) — `N+`/`N-` add/subtract from the current level, repeated adjustments, invalid input exits 1 with "could not parse volume as a number" and leaves the level unchanged, `-a` adjusts every player; **known failure:** no clamping to 0.0-1.0 (CLI sends current+delta as-is)
- <a id="us-3-5"></a>[3.5](#us-3-5) As a scripter, I want `volume` clamped to 0.0..1.0 and any non-number rejected with exit 1 and the volume unchanged
  - [test_us03_05_volume_fuzz.py](../test/us03_volume/test_us03_05_volume_fuzz.py)

## 4. Status, loop, shuffle

- <a id="us-4-1"></a>[4.1](#us-4-1) As a bar author, I want `status` to print `Playing`, `Paused` or `Stopped`
  - [test_us04_01_status.py](../test/us04_status_loop_shuffle/test_us04_01_status.py) — all three states (Playing/Paused/Stopped) printed
- <a id="us-4-2"></a>[4.2](#us-4-2) As a user, I want `loop` to print the loop status and `loop None`, `loop Track` or `loop Playlist` to set it
  - [test_us04_02_loop.py](../test/us04_status_loop_shuffle/test_us04_02_loop.py)
- <a id="us-4-3"></a>[4.3](#us-4-3) As a user, I want `shuffle` to print `On`/`Off` and `shuffle on`, `shuffle off` or `shuffle toggle` to set it (case-insensitive)
  - [test_us04_03_shuffle.py](../test/us04_status_loop_shuffle/test_us04_03_shuffle.py)
- <a id="us-4-4"></a>[4.4](#us-4-4) As a scripter, I want `loop` and `shuffle` to accept only their documented words (any case) and reject all else with exit 1
  - [test_us04_04_loop_shuffle_fuzz.py](../test/us04_status_loop_shuffle/test_us04_04_loop_shuffle_fuzz.py)

## 5. Metadata

- <a id="us-5-1"></a>[5.1](#us-5-1) As a bar author, I want `metadata` to print every metadata key
  - [test_us05_01_all_keys.py](../test/us05_metadata/test_us05_01_all_keys.py) — `player key value` columns, list-valued keys (one line per item), several players with `-a`, empty metadata prints nothing. Object-path values (`mpris:trackid`) are printed without quotes
- <a id="us-5-2"></a>[5.2](#us-5-2) As a bar author, I want `metadata artist title album` or any raw key (such as `mpris:length`) to print only those values
  - [test_us05_02_selected_keys.py](../test/us05_metadata/test_us05_02_selected_keys.py) — shortcuts, raw keys, missing keys print nothing, multiple keys. with several keys one line is printed per key in the requested order, a missing key is skipped, and all keys come from the first player that has metadata
- <a id="us-5-3"></a>[5.3](#us-5-3) As a bar author, I want properties of the wrong type or an absurd value (status, loop, shuffle, volume, position, metadata, `Can*`) never to crash playerctl on a read command
  - [test_us05_03_evil_properties.py](../test/us05_metadata/test_us05_03_evil_properties.py) — known failures BUG-E1, BUG-E2 (SIGABRT on non-`a{sv}` Metadata), BUG-E4 (Position overflow)
- <a id="us-5-4"></a>[5.4](#us-5-4) As a bar author, I want hostile metadata (control/ANSI/RTL/emoji text, MB-sized values, thousands of keys or artists, wrong value types, absurd length or trackid) printed or rejected without a crash or hang
  - [test_us05_04_evil_metadata.py](../test/us05_metadata/test_us05_04_evil_metadata.py)
- <a id="us-5-5"></a>[5.5](#us-5-5) As a bar author running `--follow`, I want garbage `PropertiesChanged` and `Seeked` signals ignored: the follower keeps running, stays quiet and shows the next valid change
  - [test_us05_05_evil_signals.py](../test/us05_metadata/test_us05_05_evil_signals.py) — known failure BUG-E1 (GIO warning on stderr)

## 6. Player selection

- <a id="us-6-1"></a>[6.1](#us-6-1) As a user, I want playerctl to act on the first available player by default
  - [test_us06_01_default_first.py](../test/us06_selection/test_us06_01_default_first.py) — one player acted on when several exist, and it is the first one in `--list-all`; also reached by the no-players loop in [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py)
- <a id="us-6-2"></a>[6.2](#us-6-2) As a user, I want `-p a,b` to choose players in my order of priority; `vlc` also matches `vlc.instance123`
  - [test_us06_02_priority_order.py](../test/us06_selection/test_us06_02_priority_order.py)
- <a id="us-6-3"></a>[6.3](#us-6-3) As a user, I want a `%any` placeholder in the `-p` list to rank players before and after "everything else"
  - [test_us06_03_any_placeholder.py](../test/us06_selection/test_us06_03_any_placeholder.py)
- <a id="us-6-4"></a>[6.4](#us-6-4) As a user, I want `-i/--ignore-player` to exclude players (ignore always wins over select)
  - [test_us06_04_ignore_player.py](../test/us06_selection/test_us06_04_ignore_player.py) — short/long flag, ignore beats select, comma lists, ignoring `name` also ignores `name.instance`, combined with `-a`, `-p` and `-l`
- <a id="us-6-5"></a>[6.5](#us-6-5) As a user, I want `-a/--all-players` to send the command to every matching player
  - [test_us06_05_all_players.py](../test/us06_selection/test_us06_05_all_players.py)
- <a id="us-6-6"></a>[6.6](#us-6-6) As a user, I want `-l/--list-all` to list players, respecting `-p` order
  - [test_us06_06_list_all.py](../test/us06_selection/test_us06_06_list_all.py)
- <a id="us-6-7"></a>[6.7](#us-6-7) As a user, I want players on both the session bus and the system bus to be found
  - [test_us06_07_session_and_system_bus.py](../test/us06_selection/test_us06_07_session_and_system_bus.py)
- <a id="us-6-8"></a>[6.8](#us-6-8) As a user, I want `-p playerctld` to start the daemon through D-Bus activation if it isn't running
  - [test_us06_08_daemon_autostart.py](../test/us06_selection/test_us06_08_daemon_autostart.py) — relies on the installed D-Bus activation file (Exec=playerctld) picked up by the test bus; checks the daemon is started on demand, proxies players, and is not started without `-p playerctld` or when ignored
- <a id="us-6-9"></a>[6.9](#us-6-9) As a user, I want players with unusual bus names (dashes, underscores, dots, digits, instance suffixes) to be listed and selectable
  - [test_us06_09_unusual_names.py](../test/us06_selection/test_us06_09_unusual_names.py) — `-l`, `-p`, `-i` with such names
- <a id="us-6-10"></a>[6.10](#us-6-10) As a scripter, I want hostile `--player` and `--ignore-player` lists (blanks, repeats, `%any` twice, 10k entries) handled without a crash or hang
  - [test_us06_10_player_list_fuzz.py](../test/us06_selection/test_us06_10_player_list_fuzz.py)

## 7. Formatted output (`-f`)

- <a id="us-7-1"></a>[7.1](#us-7-1) As a bar author, I want `-f '{{artist}} - {{title}}'` templates on query commands
  - [test_us07_01_templates.py](../test/us07_format/test_us07_01_templates.py)
- <a id="us-7-2"></a>[7.2](#us-7-2) As a user, I want `-f` rejected on commands that change state
  - [test_us07_02_reject_on_control_commands.py](../test/us07_format/test_us07_02_reject_on_control_commands.py) — rejected with exit code 1 on `play`, `pause`, `play-pause`, `stop`, `next`, `previous`, `open`, `position`, `volume`; also `position`, `volume`, `loop` and `shuffle` with an argument
- <a id="us-7-3"></a>[7.3](#us-7-3) As a bar author, I want template variables: raw metadata keys (`mpris:length`), shortcuts `artist`/`title`/`album`, plus `playerName`, `playerInstance`, `status`, `loop`, `shuffle`, `volume`, `position`
  - [test_us07_03_variables.py](../test/us07_format/test_us07_03_variables.py)
- <a id="us-7-4"></a>[7.4](#us-7-4) As a bar author, I want the helpers `lc`, `uc`, `markup_escape`, `default`, `emoji` (status, loop, shuffle, volume), `trunc`, `json_escape`, `round`, `int`, `replace`, `join`, `pad`, `uri_decode`
  - [test_us07_04_helper_functions.py](../test/us07_format/test_us07_04_helper_functions.py)
- <a id="us-7-5"></a>[7.5](#us-7-5) As a bar author, I want a `duration()` helper (time formatting)
  - [test_us07_05_duration.py](../test/us07_format/test_us07_05_duration.py)
- <a id="us-7-6"></a>[7.6](#us-7-6) As a bar author, I want arithmetic (`+ - * /`, parentheses, unary minus) and string literals
  - [test_us07_06_arithmetic_literals.py](../test/us07_format/test_us07_06_arithmetic_literals.py)
- <a id="us-7-7"></a>[7.7](#us-7-7) As a user, I want template errors to fail with exit code 1
  - [test_us07_07_template_errors.py](../test/us07_format/test_us07_07_template_errors.py) — bad `emoji` arguments, syntax errors, unknown functions and wrong argument counts
- <a id="us-7-8"></a>[7.8](#us-7-8) As a bar author, I want oversized templates (format over 1027 chars, more than 32 function arguments) rejected with a clear error
  - [test_us07_08_format_limits.py](../test/us07_format/test_us07_08_format_limits.py)
- <a id="us-7-9"></a>[7.9](#us-7-9) As a bar author, I want arithmetic on int64, uint64, double and missing values to compute correctly or fail with a clear error
  - [test_us07_09_arithmetic_edge_cases.py](../test/us07_format/test_us07_09_arithmetic_edge_cases.py) — divide by zero, overflow and type errors pass; failing: int64×int64 `*` reports a false overflow, unary `-` rejects uint64, and missing operands in `* / unary` emit GLib CRITICAL warnings
- <a id="us-7-10"></a>[7.10](#us-7-10) As a bar author, I want `json_escape` and `markup_escape` to stay valid for any title, and extreme numbers or unknown statuses never to crash the formatter
  - [test_us07_10_evil_player_data.py](../test/us07_format/test_us07_10_evil_player_data.py) — known failures BUG-E2, BUG-E5 (`uri_decode` of invalid UTF-8 logs a CRITICAL)

## 8. Follow mode (`-F`)

- <a id="us-8-1"></a>[8.1](#us-8-1) As a bar author, I want `-F` to print a new line whenever the queried property changes
  - [test_us08_01_property_changes.py](../test/us08_follow/test_us08_01_property_changes.py) — `metadata`, `status`, `volume`, `loop`, `shuffle` and `position` (via `Seeked`)
- <a id="us-8-2"></a>[8.2](#us-8-2) As a bar author, I want follow mode to track the player that updated most recently
  - [test_us08_02_latest_player.py](../test/us08_follow/test_us08_02_latest_player.py)
- <a id="us-8-3"></a>[8.3](#us-8-3) As a bar author, I want players appearing and disappearing to be handled, with an empty line when none are left
  - [test_us08_03_appear_vanish.py](../test/us08_follow/test_us08_03_appear_vanish.py)
- <a id="us-8-4"></a>[8.4](#us-8-4) As a bar author, I want duplicate lines suppressed
  - [test_us08_04_suppress_duplicates.py](../test/us08_follow/test_us08_04_suppress_duplicates.py) — explicit test that identical rendered lines print once
- <a id="us-8-5"></a>[8.5](#us-8-5) As a bar author, I want a format that uses `position` to refresh every second
  - [test_us08_05_position_tick.py](../test/us08_follow/test_us08_05_position_tick.py) — playing position advances on the 1s tick; paused output is suppressed; no tick without `position`
- <a id="us-8-6"></a>[8.6](#us-8-6) As a bar author, I want the template re-rendered when any property it uses changes
  - [test_us08_06_rerender_on_used_property.py](../test/us08_follow/test_us08_06_rerender_on_used_property.py) — template re-renders on changes of any used property, not on unused ones
- <a id="us-8-7"></a>[8.7](#us-8-7) As a user, I want `-F` rejected on control commands
  - [test_us08_07_reject_on_control_commands.py](../test/us08_follow/test_us08_07_reject_on_control_commands.py) — `play`, `next`, `open` etc. are rejected; `position`/`volume`/`loop`/`shuffle` with an argument are rejected too
- <a id="us-8-8"></a>[8.8](#us-8-8) As a bar author, I want a template that fails while rendering during `-F` to stop follow mode with exit code 1
  - [test_us08_08_runtime_errors.py](../test/us08_follow/test_us08_08_runtime_errors.py) — division by zero after a property change should exit 1 with `Error while executing command` (FAILS: `managed_player_properties_callback` discards the error, so follow keeps running; only the tick callback reports it) Extra cases: a template using `position` does report the error through the tick (passes); errors for a player that appears, for the player left after another vanished, and for one present at start are reported with exit 1
- <a id="us-8-9"></a>[8.9](#us-8-9) As a bar author, I want `-F` to honour `-i/--ignore-player` and the `-p` selection for players that appear later
  - [test_us08_09_ignore_and_select.py](../test/us08_follow/test_us08_09_ignore_and_select.py)
- <a id="us-8-10"></a>[8.10](#us-8-10) As a bar author, I want follow mode to cope with a player name that is released and re-acquired quickly, taken over by another owner, queued behind the owner, or served on both buses
  - [test_us08_10_reacquired_names.py](../test/us08_follow/test_us08_10_reacquired_names.py) — also: with the same name on both buses, the vanishing system-bus player leaves the session-bus player
- <a id="us-8-11"></a>[8.11](#us-8-11) As a bar author, I want follow mode to keep the `-p` priority order (instances, `%any`) while players update, appear and vanish, and to use the most recent update with `-a`
  - [test_us08_11_player_ordering.py](../test/us08_follow/test_us08_11_player_ordering.py) — also: `-p name.instance1,name` puts the instance first
- <a id="us-8-12"></a>[8.12](#us-8-12) As a bar author, I want follow mode to cope with players that answer slowly or vanish while they are being connected
  - [test_us08_12_slow_and_vanishing_players.py](../test/us08_follow/test_us08_12_slow_and_vanishing_players.py)
- <a id="us-8-13"></a>[8.13](#us-8-13) As a bar author, I want follow mode to handle players that have no metadata yet and to re-render (and tick) for players that appear after it started
  - [test_us08_13_players_without_data.py](../test/us08_follow/test_us08_13_players_without_data.py)
- <a id="us-8-15"></a>[8.15](#us-8-15) As a bar author, I want follow mode to stay correct and quiet under name churn, 50 players and 1000-signal bursts (converges, no repeated line, no warnings, bounded memory and CPU)
  - [test_us08_15_churn_and_storms.py](../test/us08_follow/test_us08_15_churn_and_storms.py)
- <a id="us-8-16"></a>[8.16](#us-8-16) As a bar author, I want hostile metadata (1 MB, unicode, ANSI, newlines) rendered verbatim, and no-op updates (other interface, empty, invalidated-only, `Seeked`, status flips, re-registered names, swapping players) handled
  - [test_us08_16_hostile_and_odd_updates.py](../test/us08_follow/test_us08_16_hostile_and_odd_updates.py)
- <a id="us-8-17"></a>[8.17](#us-8-17) As a bar author, I want follow mode to exit when stdout closes, end cleanly on signals and bus death, and survive SIGSTOP and a slow consumer
  - [test_us08_17_signals_pipes_and_bus.py](../test/us08_follow/test_us08_17_signals_pipes_and_bus.py) — known failure BUG-W1: a closed stdout is never noticed, so `playerctl -F
- <a id="us-8-18"></a>[8.18](#us-8-18) As a bar author, I want position ticks only while playing, exactly one empty line when the last player leaves, and render errors to stop follow mode (also with playerctld)
  - [test_us08_18_ticks_empty_lines_and_errors.py](../test/us08_follow/test_us08_18_ticks_empty_lines_and_errors.py)

## 9. Diagnostics and exit codes

- <a id="us-9-1"></a>[9.1](#us-9-1) As a scripter, I want exit code 1 and "No players found" when no players are running
  - [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py)
- <a id="us-9-2"></a>[9.2](#us-9-2) As a scripter, I want exit code 1 and "No player could handle this command" when no player can run the command
  - [test_us09_02_cannot_handle.py](../test/us09_diagnostics/test_us09_02_cannot_handle.py)
- <a id="us-9-3"></a>[9.3](#us-9-3) As a scripter, I want `-s/--no-messages` to hide these messages
  - [test_us09_03_no_messages.py](../test/us09_diagnostics/test_us09_03_no_messages.py)
- <a id="us-9-4"></a>[9.4](#us-9-4) As a user, I want `--help`/`--version` (and help when no command is given)
  - [test_us09_04_help_version.py](../test/us09_diagnostics/test_us09_04_help_version.py)
- <a id="us-9-5"></a>[9.5](#us-9-5) As a scripter, I want an unknown option or an option missing its value to fail with a message and exit code 1
  - [test_us09_05_invalid_options.py](../test/us09_diagnostics/test_us09_05_invalid_options.py)
- <a id="us-9-6"></a>[9.6](#us-9-6) As a scripter, I want option abuse (repeats, missing values, `--`, combined flags, `-f`/`-F` with control commands, oversized formats, `-v`/`-h` combos) to end in exit 0 or 1 with a clean message
  - [test_us09_06_option_abuse.py](../test/us09_diagnostics/test_us09_06_option_abuse.py)
- <a id="us-9-7"></a>[9.7](#us-9-7) As a scripter, I want every command with every hostile argument to exit 0 or 1, print valid UTF-8, log no CRITICAL and leave the player uncorrupted
  - [test_us09_07_argv_matrix.py](../test/us09_diagnostics/test_us09_07_argv_matrix.py)
- <a id="us-9-8"></a>[9.8](#us-9-8) As a scripter, I want `open ''` rejected and a failed stdout write to exit 1
  - [test_us09_08_cli_bugs.py](../test/us09_diagnostics/test_us09_08_cli_bugs.py) — known failures BUG-C1 (`open ''` opens the working directory), BUG-C2 (output to `/dev/full` exits 0)

## 10. playerctld daemon

- <a id="us-10-1"></a>[10.1](#us-10-1) As a user, I want playerctld to make the player with the most recent property change the active one
  - [test_us10_01_active_player.py](../test/us10_daemon/test_us10_01_active_player.py) — also: a `Position`-only or unchanged `PropertiesChanged` does not switch the active player, `Seeked` from another player does, an inactive player vanishing emits nothing and keeps the order, a name owner replaced without a gap stays managed
- <a id="us-10-2"></a>[10.2](#us-10-2) As a user, I want playerctld to appear as an MPRIS player that forwards calls, properties and signals to the active player
  - [test_us10_02_mpris_proxy.py](../test/us10_daemon/test_us10_02_mpris_proxy.py) — `play`, metadata follow, error forwarding, Seeked, and TrackList/Playlists calls and properties are tested. `TrackAdded` and `PlaylistChanged` are forwarded too — also: Root `Raise`/`Quit`, `Properties.Get/GetAll/Set` on Player/Root, `GetAll` on `org._5mdt.playerctld`, CLI commands through the daemon
- <a id="us-10-3"></a>[10.3](#us-10-3) As a user, I want `playerctld shift` / `unshift` to cycle the active player, with exit code 1 when there is none
  - [test_us10_03_shift_unshift.py](../test/us10_daemon/test_us10_03_shift_unshift.py) — also: single player (no signals), "Cannot shift/unshift: ..." message on failure. **Known failure:** `--follow` without `-p` does not print the new player after `shift` (the follower manages every player and does not watch the order playerctld announces)
- <a id="us-10-4"></a>[10.4](#us-10-4) As an integrator, I want a `PlayerNames` property on `org._5mdt.playerctld`
  - [test_us10_04_player_names.py](../test/us10_daemon/test_us10_04_player_names.py) — also: `-p mpv` picks `mpv` before `mpv.instance123` even when the instance was active last
- <a id="us-10-5"></a>[10.5](#us-10-5) As an integrator, I want `ActivePlayerChangeBegin`/`End` signals
  - [test_us10_05_active_player_change_signals.py](../test/us10_daemon/test_us10_05_active_player_change_signals.py) — also: full `PropertiesChanged` (Player/Root/TrackList/Playlists) + `Seeked` for the new active player, correct interface names in the invalidation when the last player leaves. a TrackList/Playlists interface the new active player lacks is invalidated if the previous one announced it. A new player's TrackList/Playlists are requested before Player/Root so they are part of its announcement, and a late reply is announced on its own
- <a id="us-10-6"></a>[10.6](#us-10-6) As an existing user, I want the legacy `com.github.altdesktop.playerctld` interface to keep working and be marked deprecated
  - [test_us10_06_legacy_interface.py](../test/us10_daemon/test_us10_06_legacy_interface.py)
- <a id="us-10-7"></a>[10.7](#us-10-7) As an existing user, I want a one-time warning when the legacy interface is used, and a fallback to it in `shift`/`unshift` for older daemons
  - [test_us10_07_legacy_warning_fallback.py](../test/us10_daemon/test_us10_07_legacy_warning_fallback.py)
- <a id="us-10-8"></a>[10.8](#us-10-8) As a user, I want `playerctld daemon` to start the service through D-Bus activation
  - [test_us10_08_daemon_command.py](../test/us10_daemon/test_us10_08_daemon_command.py) — also: exit 1 with ServiceUnknown when the bus has no activation file
- <a id="us-10-9"></a>[10.9](#us-10-9) As a user, I want playerctld to survive a player returning an error with an empty body
  - [test_us10_09_proxy_error_empty_body.py](../test/us10_daemon/test_us10_09_proxy_error_empty_body.py)
- <a id="us-10-10"></a>[10.10](#us-10-10) As a user, I want playerctld to pick up the players that were already running before it started
  - [test_us10_10_startup_enumeration.py](../test/us10_daemon/test_us10_10_startup_enumeration.py) — order follows the bus name list (last listed is active), players lacking the mandatory Player/Root interfaces are dropped, those lacking TrackList/Playlists are kept
- <a id="us-10-11"></a>[10.11](#us-10-11) As a scripter, I want the error message of a player to reach me through playerctld
  - [test_us10_11_proxy_error_message.py](../test/us10_daemon/test_us10_11_proxy_error_message.py) — **known failure:** `proxy_method_call_async_callback` reads the message from child 1 of the error body (only child 0 exists), so it always answers "Failed to call method"
- <a id="us-10-12"></a>[10.12](#us-10-12) As a user, I want playerctld to refuse unknown commands and a second instance with a clear message and exit code 1
  - [test_us10_12_command_line.py](../test/us10_daemon/test_us10_12_command_line.py)
- <a id="us-10-13"></a>[10.13](#us-10-13) As a user, I want playerctld to wait for a new player's initial property reply before using it, so that a slow player never shows up half initialised
  - [test_us10_13_pending_player.py](../test/us10_daemon/test_us10_13_pending_player.py) — a player whose Player/Root `GetAll` reply is withheld is absent from `PlayerNames`, does not displace the active player, has its signals ignored, and is promoted and announced when the reply arrives. a withheld TrackList/Playlists reply does not hold back the promotion, and the late reply does not push the player behind the others
- <a id="us-10-14"></a>[10.14](#us-10-14) As a user, I want playerctld to never use a player that cannot answer its initial property request, so that a broken player cannot take over or crash the daemon
  - [test_us10_14_failed_properties_reply.py](../test/us10_daemon/test_us10_14_failed_properties_reply.py) — a failing Player or Root `GetAll` leaves the player pending forever; it may vanish quietly. **Known failure:** once another player appeared, a `PropertiesChanged` from the failed one makes it active with NULL root properties and playerctld dies with SIGSEGV (`player_signal_proxy_callback` only drops signals of `pending_active`)
- <a id="us-10-15"></a>[10.15](#us-10-15) As a user, I want playerctld to follow players that quit, come back or hand their name over, so that the active player is always one that is actually running
  - [test_us10_15_name_owner_events.py](../test/us10_daemon/test_us10_15_name_owner_events.py) — release and re-acquire, owner swap of an inactive player, old owner quitting after a swap, active player vanishing while another is pending, pending player vanishing before its reply
- <a id="us-10-16"></a>[10.16](#us-10-16) As a user, I want property changes on a player's TrackList and Playlists interfaces to be tracked by playerctld like the Player ones, so that players gaining those interfaces keep working and are not reported as misbehaving
  - [test_us10_16_optional_interface_changes.py](../test/us10_daemon/test_us10_16_optional_interface_changes.py) — TrackList/Playlists changes activate the player; unsupported interfaces are warned about. a player that appears later or gains TrackList later is announced with it and not warned about
- <a id="us-10-17"></a>[10.17](#us-10-17) As a scripter, I want playerctld to answer invalid or unanswerable requests with a D-Bus error instead of hanging or crashing
  - [test_us10_17_proxy_error_paths.py](../test/us10_daemon/test_us10_17_proxy_error_paths.py) — unknown method/interface/property, read-only `Set`, property calls with no active player, a player that sits on a call does not block the daemon, a player vanishing during a call yields an error
- <a id="us-10-18"></a>[10.18](#us-10-18) As an integrator, I want playerctld to follow the MPRIS spec when it announces optional interfaces and to survive players that disappear while it is still initialising them
  - [test_us10_18_audit_findings.py](../test/us10_daemon/test_us10_18_audit_findings.py) — invalidated optional properties name their interface, a late player announces its optional interfaces, a player vanishing during initialisation, wrongly typed `Position`
- <a id="us-10-19"></a>[10.19](#us-10-19) As an integrator, I want playerctld to announce the MPRIS interfaces exactly as the specification defines them
  - [test_us10_19_spec_introspection.py](../test/us10_daemon/test_us10_19_spec_introspection.py) — methods, signals, properties and annotations of the four interfaces equal `data/mpris-dbus-interface.xml`; `GetArtworkFd` (passes a file descriptor) is not announced
- <a id="us-10-20"></a>[10.20](#us-10-20) As a maintainer, I want the build to refuse to generate introspection data that excludes a member the specification does not have
  - [test_us10_20_introspection_generator.py](../test/us10_daemon/test_us10_20_introspection_generator.py) — the generated header round-trips the XML, escapes quotes and backslashes, drops excluded members, and fails on an unknown member or interface
- <a id="us-10-21"></a>[10.21](#us-10-21) As an integrator, I want playerctld's D-Bus interface shipped as an XML file, and playerctld to announce exactly that interface, under the legacy name too, marked as deprecated there
  - [test_us10_21_playerctld_interface_file.py](../test/us10_daemon/test_us10_21_playerctld_interface_file.py) — `data/org._5mdt.playerctld.xml` is the source of the announced interface; the legacy name is a copy carrying `org.freedesktop.DBus.Deprecated`
- <a id="us-10-22"></a>[10.22](#us-10-22) As a user with several clients, I want shift/unshift storms to keep `PlayerNames` a permutation of the live players and `ActivePlayerChange` signals paired
  - [test_us10_22_shift_storms.py](../test/us10_daemon/test_us10_22_shift_storms.py)
- <a id="us-10-23"></a>[10.23](#us-10-23) As a user, I want nobody to take over the daemon's bus name or confuse its player list, and a second instance to exit 1
  - [test_us10_23_name_stealing.py](../test/us10_daemon/test_us10_23_name_stealing.py) — known failure BUG-D2: players named `playerctldX` are never managed
- <a id="us-10-24"></a>[10.24](#us-10-24) As a user, I want a misbehaving player (floods, malformed signals, vanishing) never to break playerctld
  - [test_us10_24_hostile_player.py](../test/us10_daemon/test_us10_24_hostile_player.py) — known failures BUG-D3, BUG-D4 (GLib CRITICALs on malformed bodies)
- <a id="us-10-25"></a>[10.25](#us-10-25) As a scripter, I want every malformed call to get a reply or a D-Bus error
  - [test_us10_25_malformed_calls.py](../test/us10_daemon/test_us10_25_malformed_calls.py) — known failures BUG-D5 (fd-passing `GetPlaylistIconFd` still forwarded), BUG-D6 (wrong-typed `Get` reply never answered)
- <a id="us-10-26"></a>[10.26](#us-10-26) As a user, I want slow, blocked or dying players not to hold up other clients
  - [test_us10_26_slow_and_dying_players.py](../test/us10_daemon/test_us10_26_slow_and_dying_players.py) — known failure BUG-D7: a blocking `Get(Position)` on the main loop stalls the daemon
- <a id="us-10-27"></a>[10.27](#us-10-27) As an operator, I want clean command line, signal, crash and restart behaviour while clients follow
  - [test_us10_27_process_lifecycle.py](../test/us10_daemon/test_us10_27_process_lifecycle.py)
- <a id="us-10-28"></a>[10.28](#us-10-28) As a user, I want daemon state to match a reference model under seeded random operations, with flat memory
  - [test_us10_28_model_based.py](../test/us10_daemon/test_us10_28_model_based.py)
- <a id="us-10-29"></a>[10.29](#us-10-29) As a client, I want truthful signals (`PlayerNames` changes, only the active player forwarded, no warning noise)
  - [test_us10_29_state_consistency.py](../test/us10_daemon/test_us10_29_state_consistency.py) — known failures BUG-D1, BUG-D8, BUG-D9

## 11. Library (libplayerctl)

- <a id="us-11-1"></a>[11.1](#us-11-1) As a developer, I want `playerctl_list_players()` to cover both buses
  - [test_us11_01_list_players.py](../test/us11_library/test_us11_01_list_players.py)
- <a id="us-11-2"></a>[11.2](#us-11-2) As a developer, I want to create a `PlayerctlPlayer` by name, by name plus source, or from a `PlayerctlPlayerName`
  - [test_us11_02_create_player.py](../test/us11_library/test_us11_02_create_player.py) — **known failure:** `Player.new('create')` does not find `create.instance123` (`pctl_player_name_instance_compare` passes its arguments to `pctl_player_name_string_instance_compare` the wrong way round)
- <a id="us-11-3"></a>[11.3](#us-11-3) As a developer, I want control methods and cached GObject properties
  - [test_us11_03_control_and_properties.py](../test/us11_library/test_us11_03_control_and_properties.py)
- <a id="us-11-4"></a>[11.4](#us-11-4) As a developer, I want GObject signals (`playback-status`, `play`, `pause`, `stop`, `metadata`, `seeked`, `volume`, `exit`, …)
  - [test_us11_04_player_signals.py](../test/us11_library/test_us11_04_player_signals.py)
- <a id="us-11-5"></a>[11.5](#us-11-5) As a developer, I want `PlayerctlPlayerManager` to emit appeared/vanished signals and keep a sortable player list
  - [test_us11_05_player_manager.py](../test/us11_library/test_us11_05_player_manager.py)
- <a id="us-11-6"></a>[11.6](#us-11-6) As a Python/Lua/JS developer, I want GObject-Introspection bindings (meson option `introspection`)
  - [test_us11_06_introspection_bindings.py](../test/us11_library/test_us11_06_introspection_bindings.py)
- <a id="us-11-7"></a>[11.7](#us-11-7) As a developer, I want the `position` property to be extrapolated while playing, frozen while paused and reset on stop, track change or seek
  - [test_us11_07_position_cache.py](../test/us11_library/test_us11_07_position_cache.py) — **known failure:** the `stop` handler still sees a non-zero position because `cached_status` is only updated after the signals are emitted (`playerctl_player_properties_changed_callback`)
- <a id="us-11-8"></a>[11.8](#us-11-8) As a developer, I want errors from the player to surface as `GLib.Error` and the setters to work for players on the system bus
  - [test_us11_08_errors_and_system_bus.py](../test/us11_library/test_us11_08_errors_and_system_bus.py) — **known failure:** `set_volume`, `set_loop_status` and `set_shuffle` call `g_bus_get_sync(G_BUS_TYPE_SESSION)` so they cannot reach a system-bus player
- <a id="us-11-9"></a>[11.9](#us-11-9) As a developer, I want the library to cope with players that send PropertiesChanged inconsistently (Spotify-style cache bypass, invalidated properties, missing track ids, wrong types, unknown status strings)
  - [test_us11_09_inconsistent_properties.py](../test/us11_library/test_us11_09_inconsistent_properties.py) — **known failures:** properties listed as invalidated are dropped from the proxy cache and never re-fetched (`Volume`, `Shuffle`, `CanPlay` read as defaults); `Volume`/`Shuffle`/`Metadata` changes with a wrong D-Bus type still emit signals with garbage values (`playerctl_player_properties_changed_callback` does no type check); `cached_track_id` is not initialised at startup so the first Metadata change with the same track resets the position; a missing or unknown initial `PlaybackStatus` leaves `cached_status` at 0 (`PLAYING`)
- <a id="us-11-10"></a>[11.10](#us-11-10) As a developer, I want the library to survive players that vanish mid-call or answer slowly, failing or not at all
  - [test_us11_10_vanishing_players.py](../test/us11_library/test_us11_10_vanishing_players.py) — **known failure:** `get_title`/`get_artist`/`get_album` pass `NULL` instead of their `err` to `playerctl_player_print_metadata_prop`, so a failed metadata call returns `None` with no `GLib.Error`
- <a id="us-11-11"></a>[11.11](#us-11-11) As a developer, I want `PlayerctlPlayerManager` to track names and players through re-appearing names, instances, both buses, many players and a sort function
  - [test_us11_11_manager_lifecycle.py](../test/us11_library/test_us11_11_manager_lifecycle.py) — also: a vanishing system-bus name leaves the session-bus player of the same name
- <a id="us-11-12"></a>[11.12](#us-11-12) As a developer, I want to connect to a player with `load-properties` off so that a slow player does not delay me
  - [test_us11_12_load_properties.py](../test/us11_library/test_us11_12_load_properties.py) — default on, creation does not wait for `GetAll`, each `can-*` is read from the player on every read (never stale), a failed `Get` reads as false
- <a id="us-11-13"></a>[11.13](#us-11-13) As a developer, I want the library to handle instance-only players, failing metadata fetches and wrongly typed property changes without aborting my program
  - [test_us11_13_audit_findings.py](../test/us11_library/test_us11_13_audit_findings.py) — instance-only player names, failing metadata fetch, metadata getter errors, wrongly typed property change, property changes do not leak, new names while managing
- <a id="us-11-14"></a>[11.14](#us-11-14) As a maintainer, I want the mock players the tests use to follow the MPRIS specification, so that no test passes against behaviour a real player cannot have
  - [test_us11_14_mock_players_follow_spec.py](../test/us11_library/test_us11_14_mock_players_follow_spec.py) — the mock Root, Player, TrackList, Playlists and playerctld have only members of the specification and all its required ones
- <a id="us-11-15"></a>[11.15](#us-11-15) As a developer, I want hostile or nonsensical player names, sources and `PlayerctlPlayerName` values to give me a `GLib.Error`, never a crash or a GLib CRITICAL
  - [test_us11_15_create_abuse.py](../test/us11_library/test_us11_15_create_abuse.py) — known failure BUG-L1: `new_from_name()` with an instance that is no valid D-Bus name logs GLib-GIO-CRITICALs
- <a id="us-11-16"></a>[11.16](#us-11-16) As a developer, I want every call and property read on a player whose bus name vanished to fail with a `GLib.Error` (or read a stale value), never crash or log a CRITICAL
  - [test_us11_16_use_after_vanish.py](../test/us11_library/test_us11_16_use_after_vanish.py)
- <a id="us-11-17"></a>[11.17](#us-11-17) As a developer, I want the control methods and writable properties to take extreme values (NaN, infinity, 64-bit limits, invalid enums, huge URIs) and pass them on or fail with a `GLib.Error`
  - [test_us11_17_setter_abuse.py](../test/us11_library/test_us11_17_setter_abuse.py)
- <a id="us-11-18"></a>[11.18](#us-11-18) As a developer, I want hostile metadata, `PropertiesChanged` and `Seeked` data (wrong types, junk, storms) to leave my program alive
  - [test_us11_18_hostile_player_data.py](../test/us11_library/test_us11_18_hostile_player_data.py)
- <a id="us-11-19"></a>[11.19](#us-11-19) As a developer, I want `PlayerctlPlayerManager` to survive misuse (NULL or hostile sort functions, double manage, unmanaged move, 50 managers, destruction with live players)
  - [test_us11_19_manager_abuse.py](../test/us11_library/test_us11_19_manager_abuse.py) — known failures BUG-L2 (`set_sort_func(NULL)` segfaults with 2+ players), BUG-L3 (sort notify never called), BUG-L4 (a player managed after it vanished stays forever)
- <a id="us-11-20"></a>[11.20](#us-11-20) As a developer, I want libplayerctl to stay correct and leak-free with hundreds of players or objects and calls from several threads
  - [test_us11_20_scale_leaks_threads.py](../test/us11_library/test_us11_20_scale_leaks_threads.py)

## Coverage summary
- **Stories:** 84 (57 original + 25 added in rounds 2 and 3 + 2 for issue #10).
- **Tested:** every story has a test file.
- **pytest suite:** 991 pass, 14 fail (1 of them flaky, us08_05). Every failure is a suspected bug in the C code.
- **C unit tests (`test/c`, `make test-c`):** 80 `g_test` cases for formatter, common helpers and player-name internals; all pass with `make test-c`, 2 (`/formatter/fn/default`, `/formatter/expand/format-direct`) fail under `make test-asan`.
- **Line coverage (gcov, `make coverage`):** 86% overall (65% at baseline), branches 77%. cli 93%, common 96%, formatter 99%, player-name 100%, manager 87%, player 78%, daemon 73%. Follow-mode `playerctl` and `playerctld` are stopped with SIGTERM, so their gcov data may be partly lost and those numbers are understated. Reports: `build/coverage/report.html`.
- **QA sweep (adversarial tests, 2026-11-10):** about 4,300 new tests in sections 1-11 (stories 1.8, 2.6, 3.5, 4.4, 5.3-5.5, 6.10, 7.10, 8.15-8.18, 9.6-9.8, 10.22-10.29, 11.15-11.20) and 5 new C executables (`test_formatter_adversarial`, `test_cli_util`, `test_daemon_player`, `test_daemon_context`, `test_player_internal`). Defects they found are pinned as strict `xfail` tests (pytest) or `# TODO BUG-*` cases (C), 26 distinct bugs in all, merged in `build/qa/BUG_REPORT.md`; the rows above name them as known failures.
- **Known failing tests (suspected C bugs):**
  - CLI: volume not clamped or validated (3.2, 3.3); `position` accepts trailing garbage and negative absolutes (2.2, 2.4); bad CLI option exits 0 (9.5); `-f` accepted on `loop Track`/`shuffle On` (7.2); `-F` accepted on `position`/`volume`/`loop`/`shuffle` with an argument (8.7); runtime format errors in follow mode are swallowed (8.8).
  - Formatter: int64 x int64 multiplication reports overflow, int64 add overflow check misses MIN+MIN, unary minus on uint64 rejected, missing operands trigger GLib criticals, `duration` argument-count error says "uc" (7.9, C tests).
  - Common: `pctl_print_gvariant(NULL)` criticals; `find_instance` argument order reversed (11.2, C tests).
  - Daemon: proxied error message lost (10.11); `--follow` without `-p` ignores `playerctld shift` (10.3); a player whose Root `GetAll` failed can become active and crash playerctld with SIGSEGV (10.14).
  - Library: `Player.new('name')` does not match `name.instanceN` (11.2); setters use the session bus for system-bus players (11.8); position not reset before the `stop` handler runs (11.7); invalidated properties never re-fetched, changed properties not type-checked, `cached_track_id` uninitialised, missing initial PlaybackStatus treated as Playing, `get_title`/`get_artist`/`get_album` swallow errors (11.9).
- **Audit tests (`build/c-code-audit.md`):** written before the fixes, they fail until the bug is fixed: `us02_05` and `us03_04` (out of range, non-finite and empty numbers), `us08_14` (follow signal connected once), `us10_18` (wrongly typed `Position`, player vanishing during `GetAll`; the invalidation interface names and late player interfaces are fixed), `us11_13` (instance-only match, failing metadata fetch, errors from `get_artist`/`get_title`/`get_album`, wrongly typed changes, `PropertiesChanged` leak) and the new formatter cases in `test/c/test_formatter.c` (`trunc`, `duration` range, `INT64_MIN` negation and division, the 1027 limit message).
- **Not testable:** `PlayerManager.manage_player(None)` and manager `set_property` through GI; internal `g_error` invariants and `assert(false)` branches; the fatal `g_error` reading the `metadata` property after a failed Get; startup scan against a player withholding a reply (25 s D-Bus timeout vs the 5 s test limit); a `Get` that never answers in the CLI (same timeout); `get_player_command` error in `player_appeared_callback`.

## Running the tests

Run `make help` for all targets. They run in the container.

- `make test`: C unit tests and the whole pytest suite, with a per-category table (XML and `summary.txt` in `build/test-report`).
- `make test-c`: only the C unit tests in `test/c` (internals the CLI cannot reach).
- `make test-asan`: AddressSanitizer and UBSan build, C tests plus every pytest suite except `test/us11_library`; reports in `build/asan`. It finds leaks and out-of-bounds reads that plain pytest cannot see.
- `make coverage`: gcov-instrumented run; reports in `build/coverage`.
- `make pre-commit`: formatters, linters and the checks above, then records the run in `test/test_history.csv` and `test/coverage_history.csv` and redraws `doc/test-history.png` and `doc/test-badge.svg`. Commit those files too.
- `make test-history-chart`: draws the history as a stacked area per category, one position per test run, in `build/test-history.png`.
- The library stories (`test/us11_library`) need PyGObject (`uv sync --group gi`) and skip without it.

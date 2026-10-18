# playerctl — application described as user stories

## How to read this
Each story ID has one test file under `test/usNN_<section>/test_usNN_MM_<slug>.py`, shared
setup lives in `test/helpers/` (plain code) and `conftest.py` files (fixtures).
- **Implemented** status comes from reading `playerctl/*.c`.
- **Tested** status comes from the pytest suite in `test/`, which drives the CLI against mock
  MPRIS players (`test/helpers/mpris.py`) and the library through PyGObject.
- A story with no test has a skip-marked stub in its file.

**Legend:** `[x]` = yes · `[~]` = partly (see note) · `[ ]` = no

## What the app is
playerctl controls media players that implement MPRIS (the D-Bus interface Linux media apps use
for remote control). It ships three things:
- **`playerctl`**: a command-line tool
- **`playerctld`**: a daemon that tracks which player was active most recently
- **`libplayerctl`**: a GObject library with GObject-Introspection bindings

Personas: **user** (desktop/hotkeys), **bar author** (polybar/waybar scripts), **developer** (uses the library).

---

## 1. Playback control
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 1.1 | As a user, I want `play`, `pause`, `play-pause` and `stop` so I can control playback from a hotkey | [x] | [x] | [test_us01_01_play_pause_stop.py](../test/us01_playback/test_us01_01_play_pause_stop.py) |
| 1.2 | As a user, I want `next` and `previous` to change track | [x] | [x] | [test_us01_02_next_previous.py](../test/us01_playback/test_us01_02_next_previous.py) |
| 1.3 | As a user, I want a player to be skipped when it reports it can't do the action (`CanPlay`, `CanPause`, `CanGoNext`, …) | [x] | [x] | [test_us01_03_skip_when_cannot.py](../test/us01_playback/test_us01_03_skip_when_cannot.py) — each command vs its gating `Can*` (play/pause/stop/play-pause/next/previous); exit 1 + message, `-s`, fallback to capable player, `-a` |
| 1.4 | As a user, I want `open URI` to open a local file (converted to `file://`) or a remote URL | [x] | [x] | [test_us01_04_open_uri.py](../test/us01_playback/test_us01_04_open_uri.py) — local path to `file://` (escaped), remote/scheme URIs and missing paths as-is, skipped when `CanControl` is false |
| 1.5 | As a scripter, I want a D-Bus error from the player on a command to be reported as "Could not execute command: ..." with exit code 1 | [x] | [x] | [test_us01_05_player_error.py](../test/us01_playback/test_us01_05_player_error.py) — mock player raises a D-Bus error on every transport/seek/open/volume/loop/shuffle command; message is shown even with `-s` |
| 1.6 | As a scripter, I want a command to fail cleanly with exit code 1 when the player vanishes mid-command, and to wait for a slow player | [x] | [x] | [test_us01_06_player_vanishes.py](../test/us01_playback/test_us01_06_player_vanishes.py) — every control command with the player's reply held and then the player disconnecting; slow replies still succeed; a player vanishing while it is being connected to |

## 2. Seeking and position
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 2.1 | As a user, I want `position` to print the current position in seconds | [x] | [x] | [test_us02_01_query.py](../test/us02_position/test_us02_01_query.py) |
| 2.2 | As a user, I want `position 30` to jump to an absolute position | [x] | [x] | [test_us02_02_set_absolute.py](../test/us02_position/test_us02_02_set_absolute.py) — absolute `SetPosition` in microseconds with the current trackid (fractions, 0), skipped when `CanSeek` is false, fails without a trackid; also reached by [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 2.3 | As a user, I want `position 10+` / `10-` to seek relative to the current position (requires `CanSeek`) | [x] | [x] | [test_us02_03_seek_relative.py](../test/us02_position/test_us02_03_seek_relative.py) — `N+`/`N-` call `Seek` with +/- microseconds (fractions), skipped with exit 1 when `CanSeek` is false, falls back to a seekable player |
| 2.4 | As a user, I want input that isn't a number to be rejected with an error | [x] | [x] | [test_us02_04_invalid_input.py](../test/us02_position/test_us02_04_invalid_input.py) — non-numeric input (`abc`, `x+`, lone sign) exits 1 with "Could not parse position as a number", no D-Bus call |

## 3. Volume
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 3.1 | As a user, I want `volume` to print the level (0.0–1.0) | [x] | [x] | [test_us03_01_query.py](../test/us03_volume/test_us03_01_query.py) |
| 3.2 | As a user, I want `volume 0.5` to set the level | [x] | [x] | [test_us03_02_set.py](../test/us03_volume/test_us03_02_set.py) |
| 3.3 | As a user, I want `volume 0.1+` / `0.1-` to change the level relative to the current one | [x] | [x] | [test_us03_03_adjust_relative.py](../test/us03_volume/test_us03_03_adjust_relative.py) — `N+`/`N-` add/subtract from the current level, repeated adjustments, invalid input exits 1 with "could not parse volume as a number" and leaves the level unchanged, `-a` adjusts every player; **known failure:** no clamping to 0.0-1.0 (CLI sends current+delta as-is) |

## 4. Status, loop, shuffle
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 4.1 | As a bar author, I want `status` to print `Playing`, `Paused` or `Stopped` | [x] | [x] | [test_us04_01_status.py](../test/us04_status_loop_shuffle/test_us04_01_status.py) — all three states (Playing/Paused/Stopped) printed |
| 4.2 | As a user, I want `loop` to print the loop status and `loop None\|Track\|Playlist` to set it | [x] | [x] | [test_us04_02_loop.py](../test/us04_status_loop_shuffle/test_us04_02_loop.py) — query for None/Track/Playlist, set each value (case-insensitive), invalid value exits 1 with "unknown loop status" and leaves the state unchanged |
| 4.3 | As a user, I want `shuffle` to print `On`/`Off` and `shuffle on\|off\|toggle` to set it (case-insensitive) | [x] | [x] | [test_us04_03_shuffle.py](../test/us04_status_loop_shuffle/test_us04_03_shuffle.py) — `on`/`off`/`toggle` (both directions), case-insensitive (ON/Off/Toggle), invalid values exit 1 with "unknown shuffle status" and leave state unchanged, query prints `On`/`Off` |

## 5. Metadata
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 5.1 | As a bar author, I want `metadata` to print every metadata key | [x] | [x] | [test_us05_01_all_keys.py](../test/us05_metadata/test_us05_01_all_keys.py) — `player key value` columns, list-valued keys (one line per item), several players with `-a`, empty metadata prints nothing. Known failure: object-path values (`mpris:trackid`) are printed with quotes (`'/track/1'`) |
| 5.2 | As a bar author, I want `metadata artist title album` or any raw key (such as `mpris:length`) to print only those values | [x] | [~] | [test_us05_02_selected_keys.py](../test/us05_metadata/test_us05_02_selected_keys.py) — shortcuts, raw keys, missing keys print nothing, multiple keys. Known failures: with several keys only the last value is printed (`*output` is overwritten in the loop), a missing key aborts the remaining keys, and `mpris:trackid` is quoted |

## 6. Player selection
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 6.1 | As a user, I want playerctl to act on the first available player by default | [x] | [x] | [test_us06_01_default_first.py](../test/us06_selection/test_us06_01_default_first.py) — one player acted on when several exist, and it is the first one in `--list-all`; also reached by the no-players loop in [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 6.2 | As a user, I want `-p a,b` to choose players in my order of priority; `vlc` also matches `vlc.instance123` | [x] | [x] | [test_us06_02_priority_order.py](../test/us06_selection/test_us06_02_priority_order.py) |
| 6.3 | As a user, I want a `%any` placeholder in the `-p` list to rank players before and after "everything else" | [x] | [x] | [test_us06_03_any_placeholder.py](../test/us06_selection/test_us06_03_any_placeholder.py) |
| 6.4 | As a user, I want `-i/--ignore-player` to exclude players (ignore always wins over select) | [x] | [x] | [test_us06_04_ignore_player.py](../test/us06_selection/test_us06_04_ignore_player.py) — short/long flag, ignore beats select, comma lists, ignoring `name` also ignores `name.instance`, combined with `-a`, `-p` and `-l` |
| 6.5 | As a user, I want `-a/--all-players` to send the command to every matching player | [x] | [x] | [test_us06_05_all_players.py](../test/us06_selection/test_us06_05_all_players.py) |
| 6.6 | As a user, I want `-l/--list-all` to list players, respecting `-p` order | [x] | [x] | [test_us06_06_list_all.py](../test/us06_selection/test_us06_06_list_all.py) |
| 6.7 | As a user, I want players on both the session bus and the system bus to be found | [x] | [x] | [test_us06_07_session_and_system_bus.py](../test/us06_selection/test_us06_07_session_and_system_bus.py) |
| 6.8 | As a user, I want `-p playerctld` to start the daemon through D-Bus activation if it isn't running | [x] | [x] | [test_us06_08_daemon_autostart.py](../test/us06_selection/test_us06_08_daemon_autostart.py) — relies on the installed D-Bus activation file (Exec=playerctld) picked up by the test bus; checks the daemon is started on demand, proxies players, and is not started without `-p playerctld` or when ignored |
| 6.9 | As a user, I want players with unusual bus names (dashes, underscores, dots, digits, instance suffixes) to be listed and selectable | [x] | [x] | [test_us06_09_unusual_names.py](../test/us06_selection/test_us06_09_unusual_names.py) — `-l`, `-p`, `-i` with such names |

## 7. Formatted output (`-f`)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 7.1 | As a bar author, I want `-f '{{artist}} - {{title}}'` templates on query commands | [x] | [x] | [test_us07_01_templates.py](../test/us07_format/test_us07_01_templates.py) |
| 7.2 | As a user, I want `-f` rejected on commands that change state | [x] | [~] | [test_us07_02_reject_on_control_commands.py](../test/us07_format/test_us07_02_reject_on_control_commands.py) — rejected with exit code 1 on `play`, `pause`, `play-pause`, `stop`, `next`, `previous`, `open`, `position`, `volume`; `loop <state>` and `shuffle <state>` are NOT rejected (tests fail, `supports_format` is TRUE for them) |
| 7.3 | As a bar author, I want template variables: raw metadata keys (`mpris:length`), shortcuts `artist`/`title`/`album`, plus `playerName`, `playerInstance`, `status`, `loop`, `shuffle`, `volume`, `position` | [x] | [x] | [test_us07_03_variables.py](../test/us07_format/test_us07_03_variables.py) |
| 7.4 | As a bar author, I want the helpers `lc`, `uc`, `markup_escape`, `default`, `emoji`, `trunc` | [x] | [x] | [test_us07_04_helper_functions.py](../test/us07_format/test_us07_04_helper_functions.py) |
| 7.5 | As a bar author, I want a `duration()` helper (time formatting) | [x] | [x] | [test_us07_05_duration.py](../test/us07_format/test_us07_05_duration.py) |
| 7.6 | As a bar author, I want arithmetic (`+ - * /`, parentheses, unary minus) and string literals | [x] | [x] | [test_us07_06_arithmetic_literals.py](../test/us07_format/test_us07_06_arithmetic_literals.py) |
| 7.7 | As a user, I want template errors to fail with exit code 1 | [x] | [x] | [test_us07_07_template_errors.py](../test/us07_format/test_us07_07_template_errors.py) — bad `emoji` arguments, syntax errors, unknown functions and wrong argument counts |
| 7.8 | As a bar author, I want oversized templates (format over 1027 chars, more than 32 function arguments) rejected with a clear error | [x] | [x] | [test_us07_08_format_limits.py](../test/us07_format/test_us07_08_format_limits.py) |
| 7.9 | As a bar author, I want arithmetic on int64, uint64, double and missing values to compute correctly or fail with a clear error | [x] | [~] | [test_us07_09_arithmetic_edge_cases.py](../test/us07_format/test_us07_09_arithmetic_edge_cases.py) — divide by zero, overflow and type errors pass; failing: int64×int64 `*` reports a false overflow, unary `-` rejects uint64, and missing operands in `* / unary` emit GLib CRITICAL warnings |

## 8. Follow mode (`-F`)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 8.1 | As a bar author, I want `-F` to print a new line whenever the queried property changes | [x] | [x] | [test_us08_01_property_changes.py](../test/us08_follow/test_us08_01_property_changes.py) — `metadata`, `status`, `volume`, `loop`, `shuffle` and `position` (via `Seeked`) |
| 8.2 | As a bar author, I want follow mode to track the player that updated most recently | [x] | [x] | [test_us08_02_latest_player.py](../test/us08_follow/test_us08_02_latest_player.py) |
| 8.3 | As a bar author, I want players appearing and disappearing to be handled, with an empty line when none are left | [x] | [x] | [test_us08_03_appear_vanish.py](../test/us08_follow/test_us08_03_appear_vanish.py) |
| 8.4 | As a bar author, I want duplicate lines suppressed | [x] | [x] | [test_us08_04_suppress_duplicates.py](../test/us08_follow/test_us08_04_suppress_duplicates.py) — explicit test that identical rendered lines print once |
| 8.5 | As a bar author, I want a format that uses `position` to refresh every second | [x] | [x] | [test_us08_05_position_tick.py](../test/us08_follow/test_us08_05_position_tick.py) — playing position advances on the 1s tick; paused output is suppressed; no tick without `position` |
| 8.6 | As a bar author, I want the template re-rendered when any property it uses changes | [x] | [x] | [test_us08_06_rerender_on_used_property.py](../test/us08_follow/test_us08_06_rerender_on_used_property.py) — template re-renders on changes of any used property, not on unused ones |
| 8.7 | As a user, I want `-F` rejected on control commands | [x] | [~] | [test_us08_07_reject_on_control_commands.py](../test/us08_follow/test_us08_07_reject_on_control_commands.py) — `play`, `next`, `open` etc. are rejected; `position`/`volume`/`loop`/`shuffle` with an argument are not (FAILS: `get_player_command` only checks `follow_signal`, so `-F volume 0.5` keeps running) |
| 8.8 | As a bar author, I want a template that fails while rendering during `-F` to stop follow mode with exit code 1 | [x] | [~] | [test_us08_08_runtime_errors.py](../test/us08_follow/test_us08_08_runtime_errors.py) — division by zero after a property change should exit 1 with `Error while executing command` (FAILS: `managed_player_properties_callback` discards the error, so follow keeps running; only the tick callback reports it) Extra cases: a template using `position` does report the error through the tick (passes); errors for a player that appears, for the player left after another vanished, and for one present at start are reported with exit 1 |
| 8.9 | As a bar author, I want `-F` to honour `-i/--ignore-player` and the `-p` selection for players that appear later | [x] | [x] | [test_us08_09_ignore_and_select.py](../test/us08_follow/test_us08_09_ignore_and_select.py) |
| 8.10 | As a bar author, I want follow mode to cope with a player name that is released and re-acquired quickly, taken over by another owner, queued behind the owner, or served on both buses | [x] | [~] | [test_us08_10_reacquired_names.py](../test/us08_follow/test_us08_10_reacquired_names.py) — **known failure:** with the same name on both buses, the vanishing system-bus player removes the session-bus player (`manager_remove_managed_player_by_name` ignores the bus type) |
| 8.11 | As a bar author, I want follow mode to keep the `-p` priority order (instances, `%any`) while players update, appear and vanish, and to use the most recent update with `-a` | [x] | [~] | [test_us08_11_player_ordering.py](../test/us08_follow/test_us08_11_player_ordering.py) — **known failure:** `player_compare_func` ranks by the `player-name` property, which has no instance suffix, so `-p name.instance1,name` does not put the instance first |
| 8.12 | As a bar author, I want follow mode to cope with players that answer slowly or vanish while they are being connected | [x] | [x] | [test_us08_12_slow_and_vanishing_players.py](../test/us08_follow/test_us08_12_slow_and_vanishing_players.py) |
| 8.13 | As a bar author, I want follow mode to handle players that have no metadata yet and to re-render (and tick) for players that appear after it started | [x] | [x] | [test_us08_13_players_without_data.py](../test/us08_follow/test_us08_13_players_without_data.py) |

## 9. Diagnostics and exit codes
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 9.1 | As a scripter, I want exit code 1 and "No players found" when no players are running | [x] | [x] | [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 9.2 | As a scripter, I want exit code 1 and "No player could handle this command" when no player can run the command | [x] | [x] | [test_us09_02_cannot_handle.py](../test/us09_diagnostics/test_us09_02_cannot_handle.py) |
| 9.3 | As a scripter, I want `-s/--no-messages` to hide these messages | [x] | [x] | [test_us09_03_no_messages.py](../test/us09_diagnostics/test_us09_03_no_messages.py) |
| 9.4 | As a user, I want `--help`/`--version` (and help when no command is given) | [x] | [x] | [test_us09_04_help_version.py](../test/us09_diagnostics/test_us09_04_help_version.py) |
| 9.5 | As a scripter, I want an unknown option or an option missing its value to fail with a message and exit code 1 | [x] | [x] | [test_us09_05_invalid_options.py](../test/us09_diagnostics/test_us09_05_invalid_options.py) — **known failure:** `main` calls `exit(0)` when `parse_setup_options` fails, so the message is printed but the exit code is 0 |

## 10. playerctld daemon
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 10.1 | As a user, I want playerctld to make the player with the most recent property change the active one | [x] | [x] | [test_us10_01_active_player.py](../test/us10_daemon/test_us10_01_active_player.py) — also: a `Position`-only or unchanged `PropertiesChanged` does not switch the active player, `Seeked` from another player does, an inactive player vanishing emits nothing and keeps the order, a name owner replaced without a gap stays managed |
| 10.2 | As a user, I want playerctld to appear as an MPRIS player that forwards calls, properties and signals to the active player | [x] | [x] | [test_us10_02_mpris_proxy.py](../test/us10_daemon/test_us10_02_mpris_proxy.py) — `play`, metadata follow, error forwarding, Seeked, and TrackList/Playlists calls and properties are tested. `TrackAdded` and `PlaylistChanged` are not forwarded: `player_signal_proxy_callback` drops every signal outside the Player and Properties interfaces (the two tests fail) — also: Root `Raise`/`Quit`, `Properties.Get/GetAll/Set` on Player/Root, `GetAll` on `org._5mdt.playerctld`, CLI commands through the daemon |
| 10.3 | As a user, I want `playerctld shift` / `unshift` to cycle the active player, with exit code 1 when there is none | [x] | [x] | [test_us10_03_shift_unshift.py](../test/us10_daemon/test_us10_03_shift_unshift.py) — also: single player (no signals), "Cannot shift/unshift: ..." message on failure |
| 10.4 | As an integrator, I want a `PlayerNames` property on `org._5mdt.playerctld` | [x] | [x] | [test_us10_04_player_names.py](../test/us10_daemon/test_us10_04_player_names.py) |
| 10.5 | As an integrator, I want `ActivePlayerChangeBegin`/`End` signals | [x] | [x] | [test_us10_05_active_player_change_signals.py](../test/us10_daemon/test_us10_05_active_player_change_signals.py) — also: full `PropertiesChanged` (Player/Root/TrackList/Playlists) + `Seeked` for the new active player, correct interface names in the invalidation when the last player leaves. **Known failures:** a player that appears while playerctld runs never gets `tracklist/playlists.supported` set (only the startup scan does), so its TrackList/Playlists properties are not announced; `context_emit_active_player_changed` names the Root interface in the TrackList and Playlists invalidations |
| 10.6 | As an existing user, I want the legacy `com.github.altdesktop.playerctld` interface to keep working and be marked deprecated | [x] | [x] | [test_us10_06_legacy_interface.py](../test/us10_daemon/test_us10_06_legacy_interface.py) |
| 10.7 | As an existing user, I want a one-time warning when the legacy interface is used, and a fallback to it in `shift`/`unshift` for older daemons | [x] | [x] | [test_us10_07_legacy_warning_fallback.py](../test/us10_daemon/test_us10_07_legacy_warning_fallback.py) |
| 10.8 | As a user, I want `playerctld daemon` to start the service through D-Bus activation | [x] | [x] | [test_us10_08_daemon_command.py](../test/us10_daemon/test_us10_08_daemon_command.py) — also: exit 1 with ServiceUnknown when the bus has no activation file |
| 10.9 | As a user, I want playerctld to survive a player returning an error with an empty body | [x] | [x] | [test_us10_09_proxy_error_empty_body.py](../test/us10_daemon/test_us10_09_proxy_error_empty_body.py) |
| 10.10 | As a user, I want playerctld to pick up the players that were already running before it started | [x] | [x] | [test_us10_10_startup_enumeration.py](../test/us10_daemon/test_us10_10_startup_enumeration.py) — order follows the bus name list (last listed is active), players lacking the mandatory Player/Root interfaces are dropped, those lacking TrackList/Playlists are kept |
| 10.11 | As a scripter, I want the error message of a player to reach me through playerctld | [x] | [x] | [test_us10_11_proxy_error_message.py](../test/us10_daemon/test_us10_11_proxy_error_message.py) — **known failure:** `proxy_method_call_async_callback` reads the message from child 1 of the error body (only child 0 exists), so it always answers "Failed to call method" |
| 10.12 | As a user, I want playerctld to refuse unknown commands and a second instance with a clear message and exit code 1 | [x] | [x] | [test_us10_12_command_line.py](../test/us10_daemon/test_us10_12_command_line.py) |
| 10.13 | As a user, I want playerctld to wait for a new player's initial property reply before using it, so that a slow player never shows up half initialised | [x] | [x] | [test_us10_13_pending_player.py](../test/us10_daemon/test_us10_13_pending_player.py) — a player whose Player/Root `GetAll` reply is withheld is absent from `PlayerNames`, does not displace the active player, has its signals ignored, and is promoted and announced when the reply arrives. **Known failure:** the late TrackList/Playlists replies call `context_add_player`, which moves the already promoted player to the tail of the queue |
| 10.14 | As a user, I want playerctld to never use a player that cannot answer its initial property request, so that a broken player cannot take over or crash the daemon | [x] | [x] | [test_us10_14_failed_properties_reply.py](../test/us10_daemon/test_us10_14_failed_properties_reply.py) — a failing Player or Root `GetAll` leaves the player pending forever; it may vanish quietly. **Known failure:** once another player appeared, a `PropertiesChanged` from the failed one makes it active with NULL root properties and playerctld dies with SIGSEGV (`player_signal_proxy_callback` only drops signals of `pending_active`) |
| 10.15 | As a user, I want playerctld to follow players that quit, come back or hand their name over, so that the active player is always one that is actually running | [x] | [x] | [test_us10_15_name_owner_events.py](../test/us10_daemon/test_us10_15_name_owner_events.py) — release and re-acquire, owner swap of an inactive player, old owner quitting after a swap, active player vanishing while another is pending, pending player vanishing before its reply |
| 10.16 | As a user, I want property changes on a player's TrackList and Playlists interfaces to be tracked by playerctld like the Player ones, so that players gaining those interfaces keep working and are not reported as misbehaving | [x] | [x] | [test_us10_16_optional_interface_changes.py](../test/us10_daemon/test_us10_16_optional_interface_changes.py) — TrackList/Playlists changes activate the player; unsupported interfaces are warned about. **Known failures:** the TrackList branch of `player_update_properties` tests `playlists.supported` instead of `tracklist.supported`, so a TrackList-only player gets a bogus warning and a Playlists-only player none; a player that appears later never has `supported` set so every change warns, and a player that gains TrackList later is never announced with it |
| 10.17 | As a scripter, I want playerctld to answer invalid or unanswerable requests with a D-Bus error instead of hanging or crashing | [x] | [x] | [test_us10_17_proxy_error_paths.py](../test/us10_daemon/test_us10_17_proxy_error_paths.py) — unknown method/interface/property, read-only `Set`, property calls with no active player, a player that sits on a call does not block the daemon, a player vanishing during a call yields an error |

## 11. Library (libplayerctl)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 11.1 | As a developer, I want `playerctl_list_players()` to cover both buses | [x] | [x] | [test_us11_01_list_players.py](../test/us11_library/test_us11_01_list_players.py) |
| 11.2 | As a developer, I want to create a `PlayerctlPlayer` by name, by name plus source, or from a `PlayerctlPlayerName` | [x] | [x] | [test_us11_02_create_player.py](../test/us11_library/test_us11_02_create_player.py) — **known failure:** `Player.new('create')` does not find `create.instance123` (`pctl_player_name_instance_compare` passes its arguments to `pctl_player_name_string_instance_compare` the wrong way round) |
| 11.3 | As a developer, I want control methods and cached GObject properties | [x] | [x] | [test_us11_03_control_and_properties.py](../test/us11_library/test_us11_03_control_and_properties.py) |
| 11.4 | As a developer, I want GObject signals (`playback-status`, `play`, `pause`, `stop`, `metadata`, `seeked`, `volume`, `exit`, …) | [x] | [x] | [test_us11_04_player_signals.py](../test/us11_library/test_us11_04_player_signals.py) |
| 11.5 | As a developer, I want `PlayerctlPlayerManager` to emit appeared/vanished signals and keep a sortable player list | [x] | [x] | [test_us11_05_player_manager.py](../test/us11_library/test_us11_05_player_manager.py) |
| 11.6 | As a Python/Lua/JS developer, I want GObject-Introspection bindings (meson option `introspection`) | [x] | [x] | [test_us11_06_introspection_bindings.py](../test/us11_library/test_us11_06_introspection_bindings.py) |
| 11.7 | As a developer, I want the `position` property to be extrapolated while playing, frozen while paused and reset on stop, track change or seek | [x] | [x] | [test_us11_07_position_cache.py](../test/us11_library/test_us11_07_position_cache.py) — **known failure:** the `stop` handler still sees a non-zero position because `cached_status` is only updated after the signals are emitted (`playerctl_player_properties_changed_callback`) |
| 11.8 | As a developer, I want errors from the player to surface as `GLib.Error` and the setters to work for players on the system bus | [x] | [x] | [test_us11_08_errors_and_system_bus.py](../test/us11_library/test_us11_08_errors_and_system_bus.py) — **known failure:** `set_volume`, `set_loop_status` and `set_shuffle` call `g_bus_get_sync(G_BUS_TYPE_SESSION)` so they cannot reach a system-bus player |
| 11.9 | As a developer, I want the library to cope with players that send PropertiesChanged inconsistently (Spotify-style cache bypass, invalidated properties, missing track ids, wrong types, unknown status strings) | [x] | [x] | [test_us11_09_inconsistent_properties.py](../test/us11_library/test_us11_09_inconsistent_properties.py) — **known failures:** properties listed as invalidated are dropped from the proxy cache and never re-fetched (`Volume`, `Shuffle`, `CanPlay` read as defaults); `Volume`/`Shuffle`/`Metadata` changes with a wrong D-Bus type still emit signals with garbage values (`playerctl_player_properties_changed_callback` does no type check); `cached_track_id` is not initialised at startup so the first Metadata change with the same track resets the position; a missing or unknown initial `PlaybackStatus` leaves `cached_status` at 0 (`PLAYING`) |
| 11.10 | As a developer, I want the library to survive players that vanish mid-call or answer slowly, failing or not at all | [x] | [x] | [test_us11_10_vanishing_players.py](../test/us11_library/test_us11_10_vanishing_players.py) — **known failure:** `get_title`/`get_artist`/`get_album` pass `NULL` instead of their `err` to `playerctl_player_print_metadata_prop`, so a failed metadata call returns `None` with no `GLib.Error` |
| 11.11 | As a developer, I want `PlayerctlPlayerManager` to track names and players through re-appearing names, instances, both buses, many players and a sort function | [x] | [x] | [test_us11_11_manager_lifecycle.py](../test/us11_library/test_us11_11_manager_lifecycle.py) — **known failure:** `manager_remove_managed_player_by_name` ignores the bus type (`TODO match bus type`), so a vanishing system-bus name removes the session-bus player of the same name |

---

## Coverage summary
- **Stories:** 82 (57 original + 25 added in rounds 2 and 3).
- **Tested:** 75 fully, 7 partly (5.2, 7.2, 7.9, 8.7, 8.8, 8.10, 8.11), none missing.
- **pytest suite:** 756 pass, 74 fail, 1 xfail (10.9). Every failure is a suspected bug in the C code.
- **C unit tests (`test/c`, `make test-c`):** 73 `g_test` cases for formatter, common helpers and
  player-name internals; 64 pass, 9 fail on suspected bugs (see below).
- **Line coverage (gcov, `make coverage`):** 85% overall (65% at baseline), branches 76%.
  cli 93%, common 96%, formatter 99%, player-name 100%, manager 88%, player 74%, daemon 73%.
  Follow-mode `playerctl` and `playerctld` are stopped with SIGTERM, so their gcov data may be
  partly lost and those numbers are understated. Reports: `build/coverage/report.html`.
- **Known failing tests (suspected C bugs):**
  - CLI: volume not clamped or validated (3.2, 3.3); `position` accepts trailing garbage and
    negative absolutes (2.2, 2.4); bad CLI option exits 0 (9.5); `metadata` with several keys,
    missing key, object paths quoted (5.1, 5.2); `-f` accepted on `loop Track`/`shuffle On`
    (7.2); `-F` accepted on `position`/`volume`/`loop`/`shuffle` with an argument (8.7);
    runtime format errors in follow mode are swallowed (8.8); follow ranks `-p name.instance`
    by player name instead of instance (8.11).
  - Formatter: int64 x int64 multiplication reports overflow, int64 add overflow check misses
    MIN+MIN, unary minus on uint64 rejected, missing operands trigger GLib criticals,
    `duration` argument-count error says "uc" (7.9, C tests).
  - Common: `pctl_print_gvariant(NULL)` criticals; `find_instance` argument order reversed
    (11.2, C tests).
  - Daemon: TrackList/Playlists signals dropped (10.2); proxied error message lost (10.11);
    wrong interface names in invalidations when the last player leaves, and TrackList/Playlists
    not announced for players that appear later (10.5, 10.16); late TrackList/Playlists replies
    demote the new active player (10.13); a player whose Root `GetAll` failed can become active
    and crash playerctld with SIGSEGV (10.14).
  - Library: `Player.new('name')` does not match `name.instanceN` (11.2); setters use the
    session bus for system-bus players (11.8); position not reset before the `stop` handler runs
    (11.7); invalidated properties never re-fetched, changed properties not type-checked,
    `cached_track_id` uninitialised, missing initial PlaybackStatus treated as Playing,
    `get_title`/`get_artist`/`get_album` swallow errors (11.9); manager removes the wrong
    player when the same name vanishes on the other bus (11.11, 8.10).
- **Not testable:** `PlayerManager.manage_player(None)` and manager `set_property` through GI;
  internal `g_error` invariants and `assert(false)` branches; the fatal `g_error` reading the
  `metadata` property after a failed Get; startup scan against a player withholding a reply
  (25 s D-Bus timeout vs the 5 s test limit); `Get` errors and timeouts in the CLI (it only
  reads the property cache); `get_player_command` error in `player_appeared_callback`.

## Running the tests
- `make coverage` runs the suite against a gcov-instrumented build in the container and writes reports to `build/coverage`.
- `make test-c` builds and runs the C unit tests in `test/c` (GLib `g_test`, internals the CLI cannot reach) with `meson test` in the container.
- `make test` runs the suite in a container (`make test-local` builds with meson on the host first).
- The library stories (`test/us11_library`) need PyGObject (`uv sync --group gi`) and skip without it.

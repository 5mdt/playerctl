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
| 1.3 | As a user, I want a player to be skipped when it reports it can't do the action (`CanPlay`, `CanPause`, `CanGoNext`, …) | [x] | [ ] | [test_us01_03_skip_when_cannot.py](../test/us01_playback/test_us01_03_skip_when_cannot.py) — no test sets any `Can*` to false |
| 1.4 | As a user, I want `open URI` to open a local file (converted to `file://`) or a remote URL | [x] | [ ] | [test_us01_04_open_uri.py](../test/us01_playback/test_us01_04_open_uri.py) — only reached by the no-players loop in [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |

## 2. Seeking and position
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 2.1 | As a user, I want `position` to print the current position in seconds | [x] | [x] | [test_us02_01_query.py](../test/us02_position/test_us02_01_query.py) |
| 2.2 | As a user, I want `position 30` to jump to an absolute position | [x] | [ ] | [test_us02_02_set_absolute.py](../test/us02_position/test_us02_02_set_absolute.py) — only reached by the no-players loop in [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 2.3 | As a user, I want `position 10+` / `10-` to seek relative to the current position (requires `CanSeek`) | [x] | [ ] | [test_us02_03_seek_relative.py](../test/us02_position/test_us02_03_seek_relative.py) |
| 2.4 | As a user, I want input that isn't a number to be rejected with an error | [x] | [ ] | [test_us02_04_invalid_input.py](../test/us02_position/test_us02_04_invalid_input.py) |

## 3. Volume
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 3.1 | As a user, I want `volume` to print the level (0.0–1.0) | [x] | [x] | [test_us03_01_query.py](../test/us03_volume/test_us03_01_query.py) |
| 3.2 | As a user, I want `volume 0.5` to set the level | [x] | [x] | [test_us03_02_set.py](../test/us03_volume/test_us03_02_set.py) |
| 3.3 | As a user, I want `volume 0.1+` / `0.1-` to change the level relative to the current one | [x] | [ ] | [test_us03_03_adjust_relative.py](../test/us03_volume/test_us03_03_adjust_relative.py) |

## 4. Status, loop, shuffle
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 4.1 | As a bar author, I want `status` to print `Playing`, `Paused` or `Stopped` | [x] | [x] | [test_us04_01_status.py](../test/us04_status_loop_shuffle/test_us04_01_status.py) |
| 4.2 | As a user, I want `loop` to print the loop status and `loop None\|Track\|Playlist` to set it | [x] | [x] | [test_us04_02_loop.py](../test/us04_status_loop_shuffle/test_us04_02_loop.py) |
| 4.3 | As a user, I want `shuffle` to print `On`/`Off` and `shuffle on\|off\|toggle` to set it (case-insensitive) | [x] | [~] | [test_us04_03_shuffle.py](../test/us04_status_loop_shuffle/test_us04_03_shuffle.py) — `on` and `toggle` tested; `off` and invalid values are not |

## 5. Metadata
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 5.1 | As a bar author, I want `metadata` to print every metadata key | [x] | [ ] | [test_us05_01_all_keys.py](../test/us05_metadata/test_us05_01_all_keys.py) — the plain `metadata` output is never checked |
| 5.2 | As a bar author, I want `metadata artist title album` or any raw key (such as `mpris:length`) to print only those values | [x] | [ ] | [test_us05_02_selected_keys.py](../test/us05_metadata/test_us05_02_selected_keys.py) |

## 6. Player selection
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 6.1 | As a user, I want playerctl to act on the first available player by default | [x] | [ ] | [test_us06_01_default_first.py](../test/us06_selection/test_us06_01_default_first.py) — only reached by the no-players loop in [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 6.2 | As a user, I want `-p a,b` to choose players in my order of priority; `vlc` also matches `vlc.instance123` | [x] | [x] | [test_us06_02_priority_order.py](../test/us06_selection/test_us06_02_priority_order.py) |
| 6.3 | As a user, I want a `%any` placeholder in the `-p` list to rank players before and after "everything else" | [x] | [x] | [test_us06_03_any_placeholder.py](../test/us06_selection/test_us06_03_any_placeholder.py) |
| 6.4 | As a user, I want `-i/--ignore-player` to exclude players (ignore always wins over select) | [x] | [ ] | [test_us06_04_ignore_player.py](../test/us06_selection/test_us06_04_ignore_player.py) — no test yet; the `--ignore-player` flag itself is used by the `list()` helper in [playerctl.py](../test/helpers/playerctl.py) |
| 6.5 | As a user, I want `-a/--all-players` to send the command to every matching player | [x] | [x] | [test_us06_05_all_players.py](../test/us06_selection/test_us06_05_all_players.py) |
| 6.6 | As a user, I want `-l/--list-all` to list players, respecting `-p` order | [x] | [x] | [test_us06_06_list_all.py](../test/us06_selection/test_us06_06_list_all.py) |
| 6.7 | As a user, I want players on both the session bus and the system bus to be found | [x] | [x] | [test_us06_07_session_and_system_bus.py](../test/us06_selection/test_us06_07_session_and_system_bus.py) |
| 6.8 | As a user, I want `-p playerctld` to start the daemon through D-Bus activation if it isn't running | [x] | [ ] | [test_us06_08_daemon_autostart.py](../test/us06_selection/test_us06_08_daemon_autostart.py) — the tests start playerctld themselves |

## 7. Formatted output (`-f`)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 7.1 | As a bar author, I want `-f '{{artist}} - {{title}}'` templates on query commands | [x] | [x] | [test_us07_01_templates.py](../test/us07_format/test_us07_01_templates.py) |
| 7.2 | As a user, I want `-f` rejected on commands that change state | [x] | [ ] | [test_us07_02_reject_on_control_commands.py](../test/us07_format/test_us07_02_reject_on_control_commands.py) |
| 7.3 | As a bar author, I want template variables: raw metadata keys (`mpris:length`), shortcuts `artist`/`title`/`album`, plus `playerName`, `playerInstance`, `status`, `loop`, `shuffle`, `volume`, `position` | [x] | [~] | [test_us07_03_variables.py](../test/us07_format/test_us07_03_variables.py) — the raw keys, the shortcuts, `playerName`, `playerInstance`, `volume` and `status` are tested; `loop`, `shuffle` and `position` are not |
| 7.4 | As a bar author, I want the helpers `lc`, `uc`, `markup_escape`, `default`, `emoji`, `trunc` | [x] | [x] | [test_us07_04_helper_functions.py](../test/us07_format/test_us07_04_helper_functions.py) |
| 7.5 | As a bar author, I want a `duration()` helper (time formatting) | [x] | [ ] | [test_us07_05_duration.py](../test/us07_format/test_us07_05_duration.py) |
| 7.6 | As a bar author, I want arithmetic (`+ - * /`, parentheses, unary minus) and string literals | [x] | [x] | [test_us07_06_arithmetic_literals.py](../test/us07_format/test_us07_06_arithmetic_literals.py) |
| 7.7 | As a user, I want template errors to fail with exit code 1 | [x] | [~] | [test_us07_07_template_errors.py](../test/us07_format/test_us07_07_template_errors.py) — bad `emoji` arguments tested; syntax errors and unknown functions are not (TODO: "missing function does not segv") |

## 8. Follow mode (`-F`)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 8.1 | As a bar author, I want `-F` to print a new line whenever the queried property changes | [x] | [~] | [test_us08_01_property_changes.py](../test/us08_follow/test_us08_01_property_changes.py) — only `metadata` is tested; `status`, `volume`, `loop`, `shuffle` and `position` are not |
| 8.2 | As a bar author, I want follow mode to track the player that updated most recently | [x] | [x] | [test_us08_02_latest_player.py](../test/us08_follow/test_us08_02_latest_player.py) |
| 8.3 | As a bar author, I want players appearing and disappearing to be handled, with an empty line when none are left | [x] | [x] | [test_us08_03_appear_vanish.py](../test/us08_follow/test_us08_03_appear_vanish.py) |
| 8.4 | As a bar author, I want duplicate lines suppressed | [x] | [~] | [test_us08_04_suppress_duplicates.py](../test/us08_follow/test_us08_04_suppress_duplicates.py) — covered implicitly by the `queue.empty()` checks |
| 8.5 | As a bar author, I want a format that uses `position` to refresh every second | [x] | [ ] | [test_us08_05_position_tick.py](../test/us08_follow/test_us08_05_position_tick.py) |
| 8.6 | As a bar author, I want the template re-rendered when any property it uses changes | [x] | [ ] | [test_us08_06_rerender_on_used_property.py](../test/us08_follow/test_us08_06_rerender_on_used_property.py) |
| 8.7 | As a user, I want `-F` rejected on control commands | [x] | [ ] | [test_us08_07_reject_on_control_commands.py](../test/us08_follow/test_us08_07_reject_on_control_commands.py) |

## 9. Diagnostics and exit codes
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 9.1 | As a scripter, I want exit code 1 and "No players found" when no players are running | [x] | [x] | [test_us09_01_no_players.py](../test/us09_diagnostics/test_us09_01_no_players.py) |
| 9.2 | As a scripter, I want exit code 1 and "No player could handle this command" when no player can run the command | [x] | [x] | [test_us09_02_cannot_handle.py](../test/us09_diagnostics/test_us09_02_cannot_handle.py) |
| 9.3 | As a scripter, I want `-s/--no-messages` to hide these messages | [x] | [ ] | [test_us09_03_no_messages.py](../test/us09_diagnostics/test_us09_03_no_messages.py) |
| 9.4 | As a user, I want `--help`/`--version` (and help when no command is given) | [x] | [~] | [test_us09_04_help_version.py](../test/us09_diagnostics/test_us09_04_help_version.py) — `--help` and `--version` tested; running with no command is not |

## 10. playerctld daemon
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 10.1 | As a user, I want playerctld to make the player with the most recent property change the active one | [x] | [x] | [test_us10_01_active_player.py](../test/us10_daemon/test_us10_01_active_player.py) |
| 10.2 | As a user, I want playerctld to appear as an MPRIS player that forwards calls, properties and signals to the active player | [x] | [~] | [test_us10_02_mpris_proxy.py](../test/us10_daemon/test_us10_02_mpris_proxy.py) — `play`, metadata follow and error forwarding are tested; Seeked, TrackList and Playlists are not |
| 10.3 | As a user, I want `playerctld shift` / `unshift` to cycle the active player, with exit code 1 when there is none | [x] | [x] | [test_us10_03_shift_unshift.py](../test/us10_daemon/test_us10_03_shift_unshift.py) |
| 10.4 | As an integrator, I want a `PlayerNames` property on `org._5mdt.playerctld` | [x] | [x] | [test_us10_04_player_names.py](../test/us10_daemon/test_us10_04_player_names.py) |
| 10.5 | As an integrator, I want `ActivePlayerChangeBegin`/`End` signals | [x] | [ ] | [test_us10_05_active_player_change_signals.py](../test/us10_daemon/test_us10_05_active_player_change_signals.py) |
| 10.6 | As an existing user, I want the legacy `com.github.altdesktop.playerctld` interface to keep working and be marked deprecated | [x] | [x] | [test_us10_06_legacy_interface.py](../test/us10_daemon/test_us10_06_legacy_interface.py) |
| 10.7 | As an existing user, I want a one-time warning when the legacy interface is used, and a fallback to it in `shift`/`unshift` for older daemons | [x] | [ ] | [test_us10_07_legacy_warning_fallback.py](../test/us10_daemon/test_us10_07_legacy_warning_fallback.py) |
| 10.8 | As a user, I want `playerctld daemon` to start the service through D-Bus activation | [x] | [ ] | [test_us10_08_daemon_command.py](../test/us10_daemon/test_us10_08_daemon_command.py) |
| 10.9 | As a user, I want playerctld to survive a player returning an error with an empty body | [x] | [x] | [test_us10_09_proxy_error_empty_body.py](../test/us10_daemon/test_us10_09_proxy_error_empty_body.py) |

## 11. Library (libplayerctl)
| ID | Story | Impl | Tested | Notes / test |
|---|---|---|---|---|
| 11.1 | As a developer, I want `playerctl_list_players()` to cover both buses | [x] | [x] | [test_us11_01_list_players.py](../test/us11_library/test_us11_01_list_players.py) |
| 11.2 | As a developer, I want to create a `PlayerctlPlayer` by name, by name plus source, or from a `PlayerctlPlayerName` | [x] | [x] | [test_us11_02_create_player.py](../test/us11_library/test_us11_02_create_player.py) |
| 11.3 | As a developer, I want control methods and cached GObject properties | [x] | [x] | [test_us11_03_control_and_properties.py](../test/us11_library/test_us11_03_control_and_properties.py) |
| 11.4 | As a developer, I want GObject signals (`playback-status`, `play`, `pause`, `stop`, `metadata`, `seeked`, `volume`, `exit`, …) | [x] | [x] | [test_us11_04_player_signals.py](../test/us11_library/test_us11_04_player_signals.py) |
| 11.5 | As a developer, I want `PlayerctlPlayerManager` to emit appeared/vanished signals and keep a sortable player list | [x] | [x] | [test_us11_05_player_manager.py](../test/us11_library/test_us11_05_player_manager.py) |
| 11.6 | As a Python/Lua/JS developer, I want GObject-Introspection bindings (meson option `introspection`) | [x] | [x] | [test_us11_06_introspection_bindings.py](../test/us11_library/test_us11_06_introspection_bindings.py) |

---

## Coverage summary
- **Implemented:** all 57 stories.
- **Tested:** 30 fully, 7 partly, 20 not at all (skip-marked stubs, one file each).
- **Biggest gaps:** relative seek and volume changes, `Can*` skipping, `--ignore-player`, `-s`,
  `duration()`, rejection of `-f`/`-F` on control commands, follow mode for properties other than
  metadata, the position tick, playerctld autostart and the `ActivePlayerChange*` signals.

## Running the tests
- `make test` runs the suite in a container (`make test-local` builds with meson on the host first).
- The library stories (`test/us11_library`) need PyGObject (`uv sync --group gi`) and skip without it.

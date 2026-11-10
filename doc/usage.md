# Using the CLI

```
playerctl [--version] [--list-all] [--all-players] [--player=NAME] [--ignore-player=IGNORE] [--format=FORMAT] [--no-messages] COMMAND
```

Here is a list of available commands:

| Command                      | Description                                                                                                                             |
|:----------------------------:|-----------------------------------------------------------------------------------------------------------------------------------------|
|          **`play`**          | Command the player to play.                                                                                                             |
|         **`pause`**          | Command the player to pause                                                                                                             |
|       **`play-pause`**       | Command the player to toggle between play/pause.                                                                                        |
|          **`stop`**          | Command the player to stop.                                                                                                             |
|          **`next`**          | Command the player to skip to the next track.                                                                                           |
|        **`previous`**        | Command the player to skip to the previous track.                                                                                       |
| **`position [OFFSET][+/-]`** | Command the player to go to the position or seek forward or backward OFFSET in seconds.                                                 |
|  **`volume [LEVEL][+/-]`**   | Print or set the volume to LEVEL from 0.0 to 1.0, clamped to that range.                                                                |
|         **`status`**         | Get the play status of the player. Either "Playing", "Paused", or "Stopped".                                                            |
|   **`metadata [KEY...]`**    | Print the metadata for the current track. If KEY is passed, print only those values from the metadata, one per line in the order given. |
|       **`open [URI]`**       | Command for the player to open a given URI. Can be either a file path or a remote URL.                                                  |
|     **`loop [STATUS]`**      | Print or set the loop status. Either "None", "Track", or "Playlist".                                                                    |
|    **`shuffle [STATUS]`**    | Print or set the shuffle status. Either "On", "Off", or "Toggle".                                                                       |

## Selecting Players to Control

Without specifying any players to control, Playerctl will act on the first player it can find.

Playerctl comes with a service called `playerctld` that monitors the activity of media players in the background. If `playerctld` is running, Playerctl will act on players in order of their last activity. To start `playerctld`, add the following command to your system startup script:

```
playerctld daemon
```

You can list the names of players that are available to control that are running on the system with `playerctl --list-all`.

An empty list is a valid result, not an error, so `--list-all` exits with 0 even when no player is running (it only prints `No players found` to stderr). The other commands exit with 1 in that case because they could not act on a player. To run a command only when a player exists, test the output of `--list-all`: `-s` silences the message and `grep -q .` exits with 1 on empty input.

```
playerctl --list-all -s | grep -q . && playerctl metadata title
```

If you'd only like to control certain players, you can pass the names of those players separated by commas with the `--player` flag. Playerctl will select the first instance of a player in that list that supports the command. To control all players in the list, you can use the `--all-players` flag.

Similarly, you can ignore players by passing their names with the `--ignore-player` flag.

The special player name `%any` can be used in the list of selected players once to match any player not in the list. This can be used to prioritize or deprioritize players.

Examples:

```bash
# Command the first instance of VLC to play
playerctl --player=vlc play

# Command all players to stop
playerctl --all-players stop

# Command VLC to go to the next track if it's running. If it's not, send the
# command to Spotify.
playerctl --player=vlc,spotify next

# Get the status of the first player that is not Gwenview.
playerctl --ignore-player=Gwenview status

# Command any player to play, but select Chromium last
playerctl --player=%any,chromium play

# Command any player to play, but select VLC first
playerctl --player=vlc,%any play
```

## Printing Properties and Metadata

You can pass a format string with the `--format` argument to print properties in a specific format. Pass the variable you want to print in the format string between double braces like `{{ VARIABLE }}`. The variables available are either the name of the query command, or anything in the metadata map which can be viewed with `playerctl metadata`. You can use this to integrate playerctl into a statusline generator.

For a simple "now playing" banner:

```bash
playerctl metadata --format "Now playing: {{ artist }} - {{ album }} - {{ title }}"
# prints 'Now playing: Lana Del Rey - Born To Die - Video Games'
```

Included in the template language are some built-in variables and helper functions for common formatting that you can call on template variables. It can also do basic math operations on numbers.

```bash
# Prints 'Total length: 3:23'
playerctl metadata --format "Total length: {{ duration(mpris:length) }}"

# Prints 'At position: 1:16'
playerctl position --format "At position: {{ duration(position) }}"

# Prints 'Artist in lowercase: lana del rey'
playerctl metadata --format "Artist in lowercase: {{ lc(artist) }}"

# Prints 'STATUS: PLAYING'
playerctl status --format "STATUS: {{ uc(status) }}"

# Prints the time remaining in the track (e.g, 'Time remaining: 2:07')
playerctl metadata --format "Time remaining: {{ duration(mpris:length - position) }}"

# Prints volume from 0 - 100
playerctl metadata --format "Volume: {{ volume * 100 }}"
```

| Function        | Argument         | Description                                                       |
|-----------------|------------------|-------------------------------------------------------------------|
| `lc`            | string           | Convert the string to lowercase.                                  |
| `uc`            | string           | Convert the string to uppercase.                                  |
| `duration`      | int              | Convert the duration to hh:mm:ss format.                          |
| `markup_escape` | string           | Escape XML markup characters in the string.                       |
| `default`       | any, any         | Print the first value if it is present, or else print the second. |
| `emoji`         | status or volume | Try to convert the variable to an emoji representation.           |
| `trunc`         | string, int      | Truncate string to a maximum length.                              |

| Variable         | Description                                       |
|------------------|---------------------------------------------------|
| `playerName`     | The name of the current player.                   |
| `playerInstance` | The instance name of the current player.          |
| `position`       | The position of the current track in microseconds |
| `status`         | The playback status of the current player         |
| `loop`           | The loop status of the current player             |
| `shuffle`        | Whether shuffle is enabled for the current player |
| `volume`         | The volume from 0.0 to 1.0                        |
| `album`          | The album of the current track.                   |
| `artist`         | The artist of the current track.                  |
| `title`          | The title of the current track.                   |

## Following changes

You can pass the `--follow` flag to query commands to block, wait for players to connect, and print the query whenever it changes. If players are passed with `--player`, players earlier in the list will be preferred in the order they appear unless `--all-players` is passed. When no player can support the query, such as when all the players exit, a newline will be printed. For example, to be notified of information about the latest currently playing track for your media players, use:

```bash
playerctl metadata --format '{{ playerName }}: {{ artist }} - {{ title }} {{ duration(position) }}|{{ duration(mpris:length) }}' --follow
```

## Changing the position of the track

You can seek to a position in the track or skip forward and back.

```bash
# Go back 30 seconds
playerctl position 30-

# Go forward 30 seconds
playerctl position 30+

# Seek to the position at 30 seconds
playerctl position 30
```

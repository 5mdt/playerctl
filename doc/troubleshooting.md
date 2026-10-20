# Troubleshooting

## Debug Logging

To enable debug logging, set the environment variable `G_MESSAGES_DEBUG=playerctl`. It's helpful to include a debug log when you report issues.

## No Players Found

Some players like Spotify require certain DBus environment variables to be set which are normally set within the session manager. If you're not using a session manager or it does not set these variables automatically (like `xinit`), launch your desktop environment wrapped in a `dbus-launch` command. For example, in your `.xinitrc` file, use this to start your WM:

```
exec dbus-launch --autolaunch=$(cat /var/lib/dbus/machine-id) i3
```

Some players may require installation of a plugin or other configuration.

In Quod Libet open the window File -> Plugins and select the plugin called *MPRIS D-Bus Support*.

## Commands Take Seconds

Some players, spotifyd for one, are slow to answer the request for all of their properties that playerctl makes when it connects. A player that never answers makes a command wait for the 25 second D-Bus timeout.

`play`, `pause`, `play-pause`, `stop`, `next`, `previous` and `open` do not make that request, they read the few properties they need one at a time. Commands that read the state of the player (`status`, `metadata`, `position`, `volume`, `loop`, `shuffle`) and `--follow` still need all the properties and wait for a slow player.

To see where the time goes, watch the session bus while you run the command:

```
dbus-monitor --session "type='method_call'" "type='method_return'"
```

A long gap between a `GetAll` call and its reply is the player being slow, not playerctl.

## Playerctld Autostart Issues

If `playerctld` does not autostart and you use `xinit` and systemd, you might need this fix to enable DBus activation to work correctly:

```
systemctl --user import-environment DISPLAY XAUTHORITY

if which dbus-update-activation-environment >/dev/null 2>&1; then
        dbus-update-activation-environment DISPLAY XAUTHORITY
fi
```

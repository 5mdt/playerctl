# Using the Library

To use a scripting library, find your favorite language from [this list](https://wiki.gnome.org/Projects/GObjectIntrospection/Users) and install the bindings library. The generated [API documentation](https://5mdt.github.io/playerctl/) describes every class and signal.

Playerctl provides an [introspectable](https://wiki.gnome.org/Projects/GObjectIntrospection) library available in your favorite scripting language that allows detailed control, like subscribing to media player events or getting metadata such as artist and title for the playing track.

## Examples

The [examples](../examples) folder uses the [Python bindings](https://pygobject.gnome.org/):

- [basic-example.py](../examples/basic-example.py) - control one player, subscribe to its play, pause and metadata events, and print the current track.
- [player-manager.py](../examples/player-manager.py) - use `PlayerManager` to react to players starting and exiting.
- [notify.py](../examples/notify.py) - show a desktop notification when the track changes.

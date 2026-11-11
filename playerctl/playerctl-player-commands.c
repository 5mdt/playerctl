/*
 * This file is part of playerctl.
 *
 * playerctl is free software: you can redistribute it and/or modify it under
 * the terms of the GNU Lesser General Public License as published by the Free
 * Software Foundation, either version 3 of the License, or (at your option)
 * any later version.
 *
 * playerctl is distributed in the hope that it will be useful, but WITHOUT ANY
 * WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
 * FOR A PARTICULAR PURPOSE.  See the GNU Lesser General Public License for
 * more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with playerctl If not, see <http://www.gnu.org/licenses/>.
 *
 * Copyright © 2014, Tony Crisci and contributors
 */

#include "playerctl-player.h"

#include <gio/gio.h>
#include <glib-object.h>
#include <playerctl/playerctl-enum-types.h>
#include <playerctl/playerctl-player-manager.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <time.h>

#include "playerctl-common.h"
#include "playerctl-generated.h"
#include "playerctl-player-internal.h"

/**
 * playerctl_player_on:
 * @self: a #PlayerctlPlayer
 * @event: the event to subscribe to
 * @callback: the callback to run on the event
 * @err:(allow-none): the location of a GError or NULL
 *
 * A convenience function for bindings to subscribe to an event with a callback
 *
 * Deprecated:2.0.0: Use g_object_connect() to listen to events.
 */
void
playerctl_player_on (PlayerctlPlayer *self, const gchar *event,
                     GClosure *callback, GError **err)
{
  /* XXX: SUSPICIOUS: g_return_if_fail (self != NULL) also accepts a wrong
     object type; PLAYERCTL_IS_PLAYER (self) would catch it (here and in the
     other public functions). */
  g_return_if_fail (self != NULL);
  g_return_if_fail (event != NULL);
  g_return_if_fail (callback != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  g_closure_ref (callback);
  g_closure_sink (callback);

  g_signal_connect_closure (self, event, callback, TRUE);
}

typedef gboolean (*PlayerCommandCall) (OrgMprisMediaPlayer2Player *proxy,
                                       GCancellable *cancellable,
                                       GError **error);

static void
player_run_command (PlayerctlPlayer *self, PlayerCommandCall call,
                    GError **err)
{
  GError *tmp_error = NULL;

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  call (self->priv->proxy, NULL, &tmp_error);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
    }
}

/**
 * playerctl_player_play_pause:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to play if it is paused or pause if it is playing
 */
void
playerctl_player_play_pause (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (
      self, org_mpris_media_player2_player_call_play_pause_sync, err);
}

/**
 * playerctl_player_open:
 * @self: a #PlayerctlPlayer
 * @uri: the URI to open, either a file name or an external URL
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to open given URI
 */
/* STYLE: uri is not modified; should be const gchar * (public API, so an
   API decision). */
void
playerctl_player_open (PlayerctlPlayer *self, gchar *uri, GError **err)
{
  GError *tmp_error = NULL;

  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }
  org_mpris_media_player2_player_call_open_uri_sync (self->priv->proxy, uri,
                                                     NULL, &tmp_error);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
    }
}

/**
 * playerctl_player_play:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to play
 */
void
playerctl_player_play (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (self, org_mpris_media_player2_player_call_play_sync,
                      err);
}

/**
 * playerctl_player_pause:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to pause
 */
void
playerctl_player_pause (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (self, org_mpris_media_player2_player_call_pause_sync,
                      err);
}

/**
 * playerctl_player_stop:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to stop
 */
void
playerctl_player_stop (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (self, org_mpris_media_player2_player_call_stop_sync,
                      err);
}

/**
 * playerctl_player_seek:
 * @self: a #PlayerctlPlayer
 * @offset: the offset to seek forward to in microseconds
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to seek forward by offset given in microseconds.
 */
void
playerctl_player_seek (PlayerctlPlayer *self, gint64 offset, GError **err)
{
  GError *tmp_error = NULL;

  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  org_mpris_media_player2_player_call_seek_sync (self->priv->proxy, offset,
                                                 NULL, &tmp_error);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
    }
}

/**
 * playerctl_player_next:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to go to the next track
 */
void
playerctl_player_next (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (self, org_mpris_media_player2_player_call_next_sync,
                      err);
}

/**
 * playerctl_player_previous:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Command the player to go to the previous track
 */
void
playerctl_player_previous (PlayerctlPlayer *self, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  player_run_command (self, org_mpris_media_player2_player_call_previous_sync,
                      err);
}

/* STYLE: player_name is not modified; take const gchar *. */
static gchar *
print_metadata_table (GVariant *metadata, gchar *player_name)
{
  GVariantIter iter;
  GVariant *child;
  const gchar *fmt = "%-5s %-25s %s\n";

  if (g_strcmp0 (g_variant_get_type_string (metadata), "a{sv}") != 0)
    {
      return NULL;
    }

  GString *table = g_string_new ("");

  g_variant_iter_init (&iter, metadata);
  while ((child = g_variant_iter_next_value (&iter)))
    {
      GVariant *key_variant = g_variant_get_child_value (child, 0);
      /* STYLE: pass NULL, not 0, for the length pointer. */
      const gchar *key = g_variant_get_string (key_variant, 0);
      /* XXX: KISS: the value is looked up again by key although child
         already holds it (g_variant_get_child_value (child, 1)); this is
         quadratic for large metadata and picks the wrong value for
         duplicate keys. */
      GVariant *value_variant = g_variant_lookup_value (metadata, key, NULL);

      if (g_variant_is_container (value_variant))
        {
          // only go depth 1
          int len = g_variant_n_children (value_variant);
          for (int i = 0; i < len; ++i)
            {
              GVariant *child_value
                  = g_variant_get_child_value (value_variant, i);
              gchar *child_value_str = pctl_print_gvariant (child_value);
              g_string_append_printf (table, fmt, player_name, key,
                                      child_value_str);
              g_free (child_value_str);
              g_variant_unref (child_value);
            }
        }
      else
        {
          gchar *value = pctl_print_gvariant (value_variant);
          g_string_append_printf (table, fmt, player_name, key, value);
          g_free (value);
        }

      g_variant_unref (child);
      g_variant_unref (key_variant);
      g_variant_unref (value_variant);
    }

  if (table->len == 0)
    {
      g_string_free (table, TRUE);
      return NULL;
    }
  // cut off the last newline
  g_string_truncate (table, table->len - 1);

  return g_string_free (table, FALSE);
}

/**
 * playerctl_player_print_metadata_prop:
 * @self: a #PlayerctlPlayer
 * @property:(allow-none): the property from the metadata to print
 * @err:(allow-none): the location of a GError or NULL
 *
 * Gets the given property from the metadata of the current track. If property
 * is null, prints all the metadata properties. Returns NULL if no track is
 * playing.
 *
 * Returns:(transfer full): The value of the given property from the metadata
 * of the current track, or all the metadata properties if property is NULL
 */
gchar *
playerctl_player_print_metadata_prop (PlayerctlPlayer *self,
                                      const gchar *property, GError **err)
{
  GError *tmp_error = NULL;

  g_return_val_if_fail (self != NULL, NULL);
  g_return_val_if_fail (err == NULL || *err == NULL, NULL);

  if (player_propagate_init_error (self, err))
    {
      return NULL;
    }

  GVariant *metadata = playerctl_player_get_metadata (self, &tmp_error);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return NULL;
    }

  if (!metadata)
    {
      return NULL;
    }

  if (!property)
    {
      gchar *res = print_metadata_table (metadata, self->priv->player_name);
      g_variant_unref (metadata);
      return res;
    }

  GVariant *prop_variant = g_variant_lookup_value (metadata, property, NULL);
  g_variant_unref (metadata);

  if (!prop_variant)
    {
      return NULL;
    }

  gchar *prop = pctl_print_gvariant (prop_variant);
  g_variant_unref (prop_variant);
  return prop;
}

static gchar *
player_get_metadata_string (PlayerctlPlayer *self, const gchar *key,
                            GError **err)
{
  g_return_val_if_fail (self != NULL, NULL);
  g_return_val_if_fail (err == NULL || *err == NULL, NULL);

  return playerctl_player_print_metadata_prop (self, key, err);
}

/**
 * playerctl_player_get_artist:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Gets the artist from the metadata of the current track, or NULL if no
 * track is playing.
 *
 * Returns:(transfer full): The artist from the metadata of the current track
 */
/* XXX: SUSPICIOUS: xesam:artist is an array of strings in MPRIS; the doc
   says "the artist" but the result is a printed list. */
gchar *
playerctl_player_get_artist (PlayerctlPlayer *self, GError **err)
{
  return player_get_metadata_string (self, "xesam:artist", err);
}

/**
 * playerctl_player_get_title:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Gets the title from the metadata of the current track, or NULL if
 * no track is playing.
 *
 * Returns:(transfer full): The title from the metadata of the current track
 */
gchar *
playerctl_player_get_title (PlayerctlPlayer *self, GError **err)
{
  return player_get_metadata_string (self, "xesam:title", err);
}

/**
 * playerctl_player_get_album:
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Gets the album from the metadata of the current track, or NULL if
 * no track is playing.
 *
 * Returns:(transfer full): The album from the metadata of the current track
 */
gchar *
playerctl_player_get_album (PlayerctlPlayer *self, GError **err)
{
  return player_get_metadata_string (self, "xesam:album", err);
}

/* Sets a property of the player interface on the bus of the player and
 * updates the property cache, as players such as cmus do not announce the
 * change. */
static void
player_set_mpris_property (PlayerctlPlayer *self, const gchar *name,
                           GVariant *value, GError **err)
{
  GError *tmp_error = NULL;
  GDBusProxy *proxy = G_DBUS_PROXY (self->priv->proxy);

  g_variant_ref_sink (value);
  GVariant *result = g_dbus_connection_call_sync (
      g_dbus_proxy_get_connection (proxy), self->priv->bus_name, MPRIS_PATH,
      PROPERTIES_IFACE, SET_MEMBER,
      g_variant_new ("(ssv)", PLAYER_IFACE, name, value), NULL,
      G_DBUS_CALL_FLAGS_NONE, -1, NULL, &tmp_error);
  if (result != NULL)
    {
      g_variant_unref (result);
      g_dbus_proxy_set_cached_property (proxy, name, value);
    }
  g_variant_unref (value);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
    }
}

/* STYLE: the gtk-doc identifier line has no trailing colon (also on other
   functions), so gtk-doc ignores these comments. */
/**
 * playerctl_player_set_volume
 * @self: a #PlayerctlPlayer
 * @volume: the volume level from 0.0 to 1.0
 * @err:(allow-none): the location of a GError or NULL
 *
 * Sets the volume level for the player from 0.0 for no volume to 1.0 for
 * maximum volume. Passing negative numbers should set the volume to 0.0.
 */
void
playerctl_player_set_volume (PlayerctlPlayer *self, gdouble volume,
                             GError **err)
{
  /* STYLE: blank line after the opening brace. */

  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  /* XXX: SUSPICIOUS: the doc promises that negative values set 0.0, but
     nothing clamps; it is left to the player. */
  player_set_mpris_property (self, "Volume", g_variant_new ("d", volume), err);
}

/**
 * playerctl_player_get_position
 * @self: a #PlayerctlPlayer
 * @err:(allow-none): the location of a GError or NULL
 *
 * Gets the position of the current track in microseconds ignoring the property
 * cache.
 */
gint64
playerctl_player_get_position (PlayerctlPlayer *self, GError **err)
{
  GError *tmp_error = NULL;

  g_return_val_if_fail (self != NULL, 0);
  g_return_val_if_fail (err == NULL || *err == NULL, 0);

  if (self->priv->init_error != NULL)
    {
      g_propagate_error (err, g_error_copy (self->priv->init_error));
      return 0;
    }

  GVariant *call_reply = g_dbus_proxy_call_sync (
      G_DBUS_PROXY (self->priv->proxy), "org.freedesktop.DBus.Properties.Get",
      g_variant_new ("(ss)", PLAYER_IFACE, "Position"), G_DBUS_CALL_FLAGS_NONE,
      -1, NULL, &tmp_error);
  if (tmp_error)
    {
      g_propagate_error (err, tmp_error);
      return 0;
    }

  GVariant *call_reply_unboxed = properties_get_reply_value (call_reply);
  g_variant_unref (call_reply);

  if (call_reply_unboxed == NULL
      || !g_variant_is_of_type (call_reply_unboxed, G_VARIANT_TYPE_INT64))
    {
      if (call_reply_unboxed != NULL)
        {
          g_variant_unref (call_reply_unboxed);
        }
      g_set_error (err, playerctl_player_error_quark (), 3,
                   "Player sent an invalid reply for the Position property");
      return 0;
    }

  gint64 position = g_variant_get_int64 (call_reply_unboxed);
  g_variant_unref (call_reply_unboxed);

  return position;
}

/**
 * playerctl_player_set_position
 * @self: a #PlayerctlPlayer
 * @position: The absolute position in the track to set as the position
 * @err:(allow-none): the location of a GError or NULL
 *
 * Sets the absolute position of the current track to the given position in
 * microseconds.
 */
void
playerctl_player_set_position (PlayerctlPlayer *self, gint64 position,
                               GError **err)
{
  GError *tmp_error = NULL;

  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  // calling the function requires the track id
  GVariant *metadata = playerctl_player_get_metadata (self, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return;
    }

  gchar *track_id = metadata_get_track_id (metadata);
  g_variant_unref (metadata);

  if (track_id == NULL)
    {
      tmp_error = g_error_new (playerctl_player_error_quark (), 2,
                               "Could not get track id to set position");
      g_propagate_error (err, tmp_error);
      return;
    }

  org_mpris_media_player2_player_call_set_position_sync (
      self->priv->proxy, track_id, position, NULL, &tmp_error);
  g_free (track_id);
  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
    }
}

/**
 * playerctl_player_set_loop_status:
 * @self: a #PlayerctlPlayer
 * @status: the requested #PlayerctlLoopStatus to set the player to
 * @err:(allow-none): the location of a GError or NULL
 *
 * Set the loop status of the player. Can be set to either None, Track, or
 * Playlist.
 */
void
playerctl_player_set_loop_status (PlayerctlPlayer *self,
                                  PlayerctlLoopStatus status, GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  const gchar *status_str = pctl_loop_status_to_string (status);
  g_return_if_fail (status_str != NULL);

  player_set_mpris_property (self, "LoopStatus",
                             g_variant_new ("s", status_str), err);
}

/**
 * playerctl_player_set_shuffle:
 * @self: a #PlayerctlPlayer
 * @shuffle: whether to enable shuffle
 * @err:(allow-none): the location of a GError or NULL
 *
 * Request to set the shuffle state of the player, either on or off.
 */
void
playerctl_player_set_shuffle (PlayerctlPlayer *self, gboolean shuffle,
                              GError **err)
{
  g_return_if_fail (self != NULL);
  g_return_if_fail (err == NULL || *err == NULL);

  if (player_propagate_init_error (self, err))
    {
      return;
    }

  player_set_mpris_property (self, "Shuffle", g_variant_new ("b", shuffle),
                             err);
}

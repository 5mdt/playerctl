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

enum
{
  PROP_0,

  PROP_PLAYER_NAME,
  PROP_PLAYER_INSTANCE,
  PROP_SOURCE,
  PROP_PLAYBACK_STATUS,
  PROP_LOOP_STATUS,
  PROP_SHUFFLE,
  /* STYLE: // comments are used throughout the tree (about 160 of them);
     GNU style uses block comments. Not repeated below. */
  PROP_STATUS, // deprecated
  PROP_VOLUME,
  PROP_METADATA,
  PROP_POSITION,
  PROP_LOAD_PROPERTIES,

  PROP_CAN_CONTROL,
  PROP_CAN_PLAY,
  PROP_CAN_PAUSE,
  PROP_CAN_SEEK,
  PROP_CAN_GO_NEXT,
  PROP_CAN_GO_PREVIOUS,

  N_PROPERTIES
};

enum
{
  PLAYBACK_STATUS,
  LOOP_STATUS,
  SHUFFLE,
  PLAY,  // deprecated
  PAUSE, // deprecated
  STOP,  // deprecated
  METADATA,
  VOLUME,
  SEEKED,
  EXIT,
  LAST_SIGNAL
};

static GParamSpec *obj_properties[N_PROPERTIES] = {
  NULL,
};

static guint connection_signals[LAST_SIGNAL] = { 0 };

static inline int64_t
timespec_to_usec (const struct timespec *a)
{
  return (int64_t)a->tv_sec * 1000000 + a->tv_nsec / 1000;
}

/* STYLE: position_monotonic is never written; make it const struct timespec
   *. */
static gint64
calculate_cached_position (PlayerctlPlaybackStatus status,
                           struct timespec *position_monotonic,
                           gint64 position)
{
  gint64 offset = 0;
  struct timespec current_time;

  switch (status)
    {
    case PLAYERCTL_PLAYBACK_STATUS_PLAYING:
      clock_gettime (CLOCK_MONOTONIC, &current_time);
      offset = timespec_to_usec (&current_time)
               - timespec_to_usec (position_monotonic);
      return position + offset;
    case PLAYERCTL_PLAYBACK_STATUS_PAUSED:
      return position;
    default:
      return 0;
    }
}

// Unwraps the "(v)" reply of org.freedesktop.DBus.Properties.Get. Some players
// reply with a different type, which must not abort the client. Returns a new
// reference to the property value or NULL.
GVariant *
properties_get_reply_value (GVariant *reply)
{
  if (!g_variant_is_of_type (reply, G_VARIANT_TYPE ("(v)")))
    {
      g_debug ("unexpected reply to Properties.Get: %s",
               g_variant_get_type_string (reply));
      return NULL;
    }

  GVariant *box = g_variant_get_child_value (reply, 0);
  GVariant *value = g_variant_get_variant (box);
  g_variant_unref (box);
  return value;
}

gchar *
metadata_get_track_id (GVariant *metadata)
{
  GVariant *track_id_variant = g_variant_lookup_value (
      metadata, "mpris:trackid", G_VARIANT_TYPE_OBJECT_PATH);
  if (track_id_variant == NULL)
    {
      // XXX some players set this as a string, which is against the protocol,
      // but a lot of them do it and I don't feel like fixing it on all the
      // players in the world.
      g_debug ("mpris:trackid is a string, not a D-Bus object reference");
      track_id_variant = g_variant_lookup_value (metadata, "mpris:trackid",
                                                 G_VARIANT_TYPE_STRING);
    }

  if (track_id_variant != NULL)
    {
      const gchar *track_id = g_variant_get_string (track_id_variant, NULL);
      gchar *result = NULL;
      // players like Totem send ids that are not valid object paths, which
      // would abort when building the SetPosition call
      if (g_variant_is_object_path (track_id))
        {
          result = g_strdup (track_id);
        }
      else
        {
          g_debug ("mpris:trackid is not a valid object path: %s", track_id);
        }
      g_variant_unref (track_id_variant);
      return result;
    }

  return NULL;
}

/* Looks up a changed property; a value of the wrong type is ignored. */
static GVariant *
lookup_property (GVariant *properties, const gchar *key,
                 const GVariantType *type, const gchar *instance)
{
  GVariant *value = g_variant_lookup_value (properties, key, NULL);
  if (value != NULL && !g_variant_is_of_type (value, type))
    {
      g_debug ("%s: ignoring %s of type %s", instance, key,
               g_variant_get_type_string (value));
      g_variant_unref (value);
      return NULL;
    }
  return value;
}

static void
playerctl_player_properties_changed_callback (
    GDBusProxy *_proxy, GVariant *changed_properties,
    const gchar *const *invalidated_properties, gpointer user_data)
{
  PlayerctlPlayer *self = user_data;
  gchar *instance = self->priv->instance;
  g_debug ("%s: properties changed", instance);

  GVariant *metadata = lookup_property (changed_properties, "Metadata",
                                        G_VARIANT_TYPE_VARDICT, instance);
  GVariant *playback_status = lookup_property (
      changed_properties, "PlaybackStatus", G_VARIANT_TYPE_STRING, instance);
  GVariant *loop_status = lookup_property (changed_properties, "LoopStatus",
                                           G_VARIANT_TYPE_STRING, instance);
  GVariant *volume = lookup_property (changed_properties, "Volume",
                                      G_VARIANT_TYPE_DOUBLE, instance);
  GVariant *shuffle = lookup_property (changed_properties, "Shuffle",
                                       G_VARIANT_TYPE_BOOLEAN, instance);

  if (shuffle != NULL)
    {
      gboolean shuffle_value = g_variant_get_boolean (shuffle);
      g_debug ("%s: shuffle value set to %s", instance,
               shuffle_value ? "true" : "false");
      g_signal_emit (self, connection_signals[SHUFFLE], 0, shuffle_value);
      g_variant_unref (shuffle);
    }

  if (volume != NULL)
    {
      gdouble volume_value = g_variant_get_double (volume);
      g_debug ("%s: volume set to %f", instance, volume_value);
      g_signal_emit (self, connection_signals[VOLUME], 0, volume_value);
      g_variant_unref (volume);
    }

  gboolean track_id_invalidated = FALSE;
  if (metadata != NULL)
    {
      // update the cached track id
      gchar *track_id = metadata_get_track_id (metadata);
      if (g_strcmp0 (track_id, self->priv->cached_track_id) != 0)
        {
          g_free (self->priv->cached_track_id);
          g_debug ("%s: track id updated to %s", instance, track_id);
          self->priv->cached_track_id = track_id;
          track_id_invalidated = TRUE;
          // reset before the handlers of the signal below read the position
          self->priv->cached_position = 0;
          clock_gettime (CLOCK_MONOTONIC,
                         &self->priv->cached_position_monotonic);
        }
      else
        {
          g_free (track_id);
        }

      g_debug ("%s: metadata changed", instance);
      g_signal_emit (self, connection_signals[METADATA], 0, metadata);
      g_variant_unref (metadata);
    }

  if (playback_status == NULL && track_id_invalidated)
    {
      // XXX: Lots of player aren't setting status correctly when the track
      // changes so we have to get it from the interface. We should
      // definitely go fix this bug on the players.
      g_debug ("Playback status not set on track change; getting status from "
               "interface instead");
      /* FIXME: blocking g_dbus_proxy_call_sync() with no timeout (-1 means
         the 25 s default) inside a signal handler; a hung player freezes
         the main loop. Also XXX: DRY: this Properties.Get call and its
         unwrapping is repeated in the other property readers, with string
         literals although PROPERTIES_IFACE and PLAYER_IFACE exist; make one
         helper. */
      GVariant *call_reply = g_dbus_proxy_call_sync (
          G_DBUS_PROXY (self->priv->proxy),
          "org.freedesktop.DBus.Properties.Get",
          g_variant_new ("(ss)", "org.mpris.MediaPlayer2.Player",
                         "PlaybackStatus"),
          G_DBUS_CALL_FLAGS_NONE, -1, NULL, NULL);

      if (call_reply != NULL)
        {
          playback_status = properties_get_reply_value (call_reply);
          g_variant_unref (call_reply);
          if (playback_status != NULL
              && !g_variant_is_of_type (playback_status,
                                        G_VARIANT_TYPE_STRING))
            {
              g_variant_unref (playback_status);
              playback_status = NULL;
            }
        }
    }

  if (loop_status != NULL)
    {
      const gchar *status_str = g_variant_get_string (loop_status, NULL);
      PlayerctlLoopStatus status = 0;
      GQuark quark = 0;
      if (pctl_parse_loop_status (status_str, &status))
        {
          switch (status)
            {
            case PLAYERCTL_LOOP_STATUS_TRACK:
              quark = g_quark_from_string ("track");
              break;
            case PLAYERCTL_LOOP_STATUS_PLAYLIST:
              quark = g_quark_from_string ("playlist");
              break;
            case PLAYERCTL_LOOP_STATUS_NONE:
              quark = g_quark_from_string ("none");
              break;
            }
          g_debug ("%s: loop status set to %s", instance,
                   g_quark_to_string (quark));
          g_signal_emit (self, connection_signals[LOOP_STATUS], quark, status);
        }

      g_variant_unref (loop_status);
    }

  if (playback_status != NULL)
    {
      const gchar *status_str = g_variant_get_string (playback_status, NULL);
      g_debug ("%s: playback status set to %s", instance, status_str);
      PlayerctlPlaybackStatus status = 0;
      GQuark quark = 0;

      if (pctl_parse_playback_status (status_str, &status))
        {
          PlayerctlPlaybackStatus old_status = self->priv->cached_status;
          switch (status)
            {
            case PLAYERCTL_PLAYBACK_STATUS_PLAYING:
              quark = g_quark_from_string ("playing");
              if (old_status != PLAYERCTL_PLAYBACK_STATUS_PLAYING)
                {
                  clock_gettime (CLOCK_MONOTONIC,
                                 &self->priv->cached_position_monotonic);
                }
              break;
            case PLAYERCTL_PLAYBACK_STATUS_PAUSED:
              quark = g_quark_from_string ("paused");
              self->priv->cached_position = calculate_cached_position (
                  old_status, &self->priv->cached_position_monotonic,
                  self->priv->cached_position);
              break;
            case PLAYERCTL_PLAYBACK_STATUS_STOPPED:
              self->priv->cached_position = 0;
              quark = g_quark_from_string ("stopped");
              break;
            }

          // update the cache first, so that the handlers read the new state
          self->priv->cached_status = status;

          /* XXX: SUSPICIOUS: status_signals[] is indexed by the enum value,
             which silently relies on PLAYING, PAUSED and STOPPED being 0, 1
             and 2. The deprecated play/pause/stop signals are also emitted
             when the status did not change, unlike playback-status. */
          // the PLAY, PAUSE and STOP signals are DEPRECATED; indexed by status
          const guint status_signals[] = { PLAY, PAUSE, STOP };
          g_signal_emit (self, connection_signals[status_signals[status]], 0);

          if (old_status != status)
            {
              g_signal_emit (self, connection_signals[PLAYBACK_STATUS], quark,
                             status);
            }
        }
      else
        {
          g_debug ("%s: got unknown playback state: %s", instance, status_str);
        }

      g_variant_unref (playback_status);
    }
}

/* STYLE: user_data is declared gpointer *, not gpointer; the same in the other callbacks.
   It works only because all pointers have the same representation. */
static void
playerctl_player_seeked_callback (GDBusProxy *_proxy, gint64 position,
                                  gpointer *user_data)
{
  PlayerctlPlayer *player = PLAYERCTL_PLAYER (user_data);
  player->priv->cached_position = position;
  g_debug ("%s: new player position %" G_GINT64_FORMAT, player->priv->instance,
           position);
  clock_gettime (CLOCK_MONOTONIC, &player->priv->cached_position_monotonic);
  g_signal_emit (player, connection_signals[SEEKED], 0, position);
}

static void playerctl_player_initable_iface_init (GInitableIface *iface);

G_DEFINE_TYPE_WITH_CODE (
    PlayerctlPlayer, playerctl_player, G_TYPE_OBJECT,
    G_ADD_PRIVATE (PlayerctlPlayer)
        G_IMPLEMENT_INTERFACE (G_TYPE_INITABLE,
                               playerctl_player_initable_iface_init));

// clang-format off
G_DEFINE_QUARK(playerctl-player-error-quark, playerctl_player_error);
// clang-format on

GVariant *
playerctl_player_get_metadata (PlayerctlPlayer *self, GError **err)
{
  GVariant *metadata;
  GError *tmp_error = NULL;

  metadata = org_mpris_media_player2_player_dup_metadata (self->priv->proxy);

  if (!metadata)
    {
      // XXX: Ugly spotify workaround. Spotify does not seem to use the
      // property cache. We have to get the properties directly.
      g_debug ("Spotify does not use the D-Bus property cache, getting "
               "properties directly");
      GVariant *call_reply = g_dbus_proxy_call_sync (
          G_DBUS_PROXY (self->priv->proxy),
          "org.freedesktop.DBus.Properties.Get",
          g_variant_new ("(ss)", "org.mpris.MediaPlayer2.Player", "Metadata"),
          G_DBUS_CALL_FLAGS_NONE, -1, NULL, &tmp_error);

      if (tmp_error != NULL)
        {
          g_propagate_error (err, tmp_error);
          return NULL;
        }

      metadata = properties_get_reply_value (call_reply);
      g_variant_unref (call_reply);

      if (metadata == NULL)
        {
          /* XXX: SUSPICIOUS: error codes are bare literals. 3 means
             "invalid reply" here and in the capability reader but "instance
             without source" in the constructor; 1 is "not found", 2 is "no track id". Define a public
             error enum so callers can tell them apart. */
          g_set_error (err, playerctl_player_error_quark (), 3,
                       "Player sent an invalid reply for the Metadata "
                       "property");
          return NULL;
        }
    }

  return metadata;
}

static const gchar *
can_property_name (guint property_id)
{
  switch (property_id)
    {
    case PROP_CAN_CONTROL:
      return "CanControl";
    case PROP_CAN_PLAY:
      return "CanPlay";
    case PROP_CAN_PAUSE:
      return "CanPause";
    case PROP_CAN_SEEK:
      return "CanSeek";
    case PROP_CAN_GO_NEXT:
      return "CanGoNext";
    case PROP_CAN_GO_PREVIOUS:
      return "CanGoPrevious";
    default:
      g_assert_not_reached ();
    }
}

gboolean
player_propagate_init_error (PlayerctlPlayer *self, GError **err)
{
  if (self->priv->init_error == NULL)
    {
      return FALSE;
    }

  g_propagate_error (err, g_error_copy (self->priv->init_error));
  return TRUE;
}

static PlayerctlPlayer *
player_new_with_properties (GError **err, const gchar *first_property_name,
                            ...)
{
  GError *tmp_error = NULL;
  va_list args;

  va_start (args, first_property_name);
  GObject *player = g_initable_new_valist (
      PLAYERCTL_TYPE_PLAYER, first_property_name, args, NULL, &tmp_error);
  va_end (args);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return NULL;
    }

  return PLAYERCTL_PLAYER (player);
}

// Reads one of the boolean Can* properties of the player interface. The value
// comes from the proxy's property cache. A player created without
// load-properties has no cache (GDBus does not keep it up to date for such a
// proxy), so the property is fetched with a Properties.Get on every read. A
// failed or malformed reply reads as FALSE, like a property missing from the
// cache.
static gboolean
player_get_capability (PlayerctlPlayer *self, const gchar *name)
{
  GDBusProxy *proxy = G_DBUS_PROXY (self->priv->proxy);
  GVariant *value = NULL;

  if (self->priv->load_properties)
    {
      value = g_dbus_proxy_get_cached_property (proxy, name);
    }
  else
    {
      GError *error = NULL;
      GVariant *reply = g_dbus_proxy_call_sync (
          proxy, "org.freedesktop.DBus.Properties.Get",
          g_variant_new ("(ss)", PLAYER_IFACE, name), G_DBUS_CALL_FLAGS_NONE,
          -1, NULL, &error);
      if (reply == NULL)
        {
          g_debug ("could not get %s: %s", name, error->message);
          g_error_free (error);
          return FALSE;
        }

      value = properties_get_reply_value (reply);
      g_variant_unref (reply);
    }

  if (value == NULL)
    {
      return FALSE;
    }

  gboolean result = g_variant_is_of_type (value, G_VARIANT_TYPE_BOOLEAN)
                    && g_variant_get_boolean (value);
  g_variant_unref (value);
  return result;
}

static void
playerctl_player_set_property (GObject *object, guint property_id,
                               const GValue *value, GParamSpec *pspec)
{
  PlayerctlPlayer *self = PLAYERCTL_PLAYER (object);

  switch (property_id)
    {
    case PROP_PLAYER_NAME:
      g_free (self->priv->player_name);
      self->priv->player_name = g_strdup (g_value_get_string (value));
      break;

    case PROP_PLAYER_INSTANCE:
      g_free (self->priv->instance);
      self->priv->instance = g_strdup (g_value_get_string (value));
      break;

    case PROP_SOURCE:
      self->priv->source = g_value_get_enum (value);
      break;

    case PROP_LOAD_PROPERTIES:
      self->priv->load_properties = g_value_get_boolean (value);
      break;

    case PROP_VOLUME:
      g_warning ("setting the volume property directly is deprecated and will "
                 "be removed in a future version. Use "
                 "playerctl_player_set_volume() instead.");
      org_mpris_media_player2_player_set_volume (self->priv->proxy,
                                                 g_value_get_double (value));
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, property_id, pspec);
      break;
    }
}

static void
playerctl_player_get_property (GObject *object, guint property_id,
                               GValue *value, GParamSpec *pspec)
{
  PlayerctlPlayer *self = PLAYERCTL_PLAYER (object);

  switch (property_id)
    {
    case PROP_PLAYER_NAME:
      g_value_set_string (value, self->priv->player_name);
      break;

    case PROP_PLAYER_INSTANCE:
      g_value_set_string (value, self->priv->instance);
      break;

    case PROP_SOURCE:
      g_value_set_enum (value, self->priv->source);
      break;

    case PROP_LOAD_PROPERTIES:
      g_value_set_boolean (value, self->priv->load_properties);
      break;

    case PROP_PLAYBACK_STATUS:
      g_value_set_enum (value, self->priv->cached_status);
      break;

    /* XXX: SUSPICIOUS: no proxy == NULL guard here, unlike PROP_SHUFFLE,
       PROP_STATUS, PROP_VOLUME and PROP_CAN_*; a player whose init failed
       passes NULL to the generated getter. */
    case PROP_LOOP_STATUS:
      {
        const gchar *status_str
            = org_mpris_media_player2_player_get_loop_status (
                self->priv->proxy);
        PlayerctlLoopStatus status = 0;
        if (pctl_parse_loop_status (status_str, &status))
          {
            g_value_set_enum (value, status);
          }
        else
          {
            if (status_str != NULL)
              {
                g_debug ("got unknown loop status: %s", status_str);
              }
            g_value_set_enum (value, PLAYERCTL_LOOP_STATUS_NONE);
          }
        break;
      }

    case PROP_SHUFFLE:
      {
        if (self->priv->proxy == NULL)
          {
            g_value_set_boolean (value, FALSE);
            break;
          }
        g_value_set_boolean (
            value,
            org_mpris_media_player2_player_get_shuffle (self->priv->proxy));
        break;
      }

    case PROP_STATUS:
      // DEPRECATED
      if (self->priv->proxy)
        {
          g_value_set_string (value, pctl_playback_status_to_string (
                                         self->priv->cached_status));
        }
      else
        {
          g_value_set_string (value, "");
        }
      break;

    case PROP_METADATA:
      {
        GError *error = NULL;
        GVariant *metadata = NULL;
        metadata = playerctl_player_get_metadata (self, &error);
        if (error != NULL)
          {
            // a property getter cannot return an error, and must not abort
            g_warning ("could not get metadata: %s", error->message);
            g_clear_error (&error);
          }
        // playerctl_player_get_metadata() returns a new reference
        g_value_take_variant (value, metadata);
        break;
      }

    case PROP_VOLUME:
      if (self->priv->proxy)
        {
          g_value_set_double (
              value,
              org_mpris_media_player2_player_get_volume (self->priv->proxy));
        }
      else
        {
          g_value_set_double (value, 0);
        }
      break;

    case PROP_POSITION:
      {
        gint64 position = calculate_cached_position (
            self->priv->cached_status, &self->priv->cached_position_monotonic,
            self->priv->cached_position);
        g_value_set_int64 (value, position);
        break;
      }

    case PROP_CAN_CONTROL:
    case PROP_CAN_PLAY:
    case PROP_CAN_PAUSE:
    case PROP_CAN_SEEK:
    case PROP_CAN_GO_NEXT:
    case PROP_CAN_GO_PREVIOUS:
      if (self->priv->proxy == NULL)
        {
          g_value_set_boolean (value, FALSE);
          break;
        }
      g_value_set_boolean (value, player_get_capability (
                                      self, can_property_name (property_id)));
      break;

    default:
      G_OBJECT_WARN_INVALID_PROPERTY_ID (object, property_id, pspec);
      break;
    }
}

static void
playerctl_player_constructed (GObject *gobject)
{
  PlayerctlPlayer *self = PLAYERCTL_PLAYER (gobject);

  self->priv->init_error = NULL;

  g_initable_init ((GInitable *)self, NULL, &self->priv->init_error);

  G_OBJECT_CLASS (playerctl_player_parent_class)->constructed (gobject);
}

static void
playerctl_player_dispose (GObject *gobject)
{
  PlayerctlPlayer *self = PLAYERCTL_PLAYER (gobject);

  /* HARDENING: dispose does not disconnect the g-properties-changed, seeked
     and notify::g-name-owner handlers that hold this player as user_data;
     harmless today because the proxy is private and dies in
     g_clear_object(), but g_signal_handlers_disconnect_by_data() would make
     it robust. */
  g_clear_error (&self->priv->init_error);
  g_clear_object (&self->priv->proxy);

  G_OBJECT_CLASS (playerctl_player_parent_class)->dispose (gobject);
}

static void
playerctl_player_finalize (GObject *gobject)
{
  PlayerctlPlayer *self = PLAYERCTL_PLAYER (gobject);

  g_free (self->priv->player_name);
  g_free (self->priv->instance);
  g_free (self->priv->cached_track_id);
  g_free (self->priv->bus_name);

  G_OBJECT_CLASS (playerctl_player_parent_class)->finalize (gobject);
}

// All the signals of the player have no return value and no class handler;
// only the flags, the marshaller and the (at most one) parameter type differ.
static guint
player_signal_new (const gchar *name, GSignalFlags flags,
                   GSignalCMarshaller marshaller, GType param_type)
{
  return g_signal_new (name, PLAYERCTL_TYPE_PLAYER, flags, 0, NULL, NULL,
                       marshaller, G_TYPE_NONE,
                       param_type == G_TYPE_NONE ? 0 : 1, param_type);
}

static void
player_define_properties (void)
{
  obj_properties[PROP_PLAYER_NAME] = g_param_spec_string (
      "player-name", "Player name",
      "The name of the type of player this is. "
      "The instance is fully qualified with the player-instance and the "
      "source.",
      NULL, /* default */
      G_PARAM_READWRITE | G_PARAM_CONSTRUCT_ONLY | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_PLAYER_INSTANCE] = g_param_spec_string (
      "player-instance", "Player instance",
      "An instance name that identifies "
      "this player on the source",
      NULL, /* default */
      G_PARAM_READWRITE | G_PARAM_CONSTRUCT_ONLY | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_SOURCE] = g_param_spec_enum (
      "source", "Player source",
      "The source of this player. Currently supported "
      "sources are the DBus session bus and DBus system bus.",
      playerctl_source_get_type (), PLAYERCTL_SOURCE_NONE,
      G_PARAM_CONSTRUCT_ONLY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_PLAYBACK_STATUS] = g_param_spec_enum (
      "playback-status", "Player playback status",
      "Whether the player is playing, paused, or stopped",
      playerctl_playback_status_get_type (), PLAYERCTL_PLAYBACK_STATUS_STOPPED,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_LOOP_STATUS] = g_param_spec_enum (
      "loop-status", "Player loop status", "The loop status of the player",
      playerctl_loop_status_get_type (), PLAYERCTL_LOOP_STATUS_NONE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_SHUFFLE] = g_param_spec_boolean (
      "shuffle", "Shuffle",
      "A value of false indicates that playback is "
      "progressing linearly through a playlist, while true means playback is "
      "progressing through a playlist in some other order.",
      FALSE, G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  /**
   * PlayerctlPlayer:status:
   *
   * The playback status of the player as a string
   *
   * Deprecated:2.0.0: Use the "playback-status" signal instead.
   */
  obj_properties[PROP_STATUS] = g_param_spec_string (
      "status", "Player status",
      "The play status of the player (deprecated: use "
      "playback-status)",
      NULL, /* default */
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS | G_PARAM_DEPRECATED);
}

static void
player_define_state_properties (void)
{
  obj_properties[PROP_VOLUME] = g_param_spec_double (
      "volume", "Player volume",
      "The volume level of the player. Setting "
      "this property directly is deprecated and this property will become "
      "read "
      "only in a future version. Use playerctl_player_set_volume() to set the "
      "volume.",
      /* XXX: SUSPICIOUS: the volume range is 0..100 here and in the volume
         signal docs, but playerctl_player_set_volume() documents
         0.0..1.0, which is the MPRIS scale. One of them is wrong. */
      0, 100, 0, G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);

  /**
   * PlayerctlPlayer:load-properties:
   *
   * Whether to fetch all the properties of the player when connecting to it.
   * This is the default. A player can be slow to answer that request, and the
   * connection waits for it.
   *
   * When %FALSE the properties are not fetched up front and not kept up to
   * date. The `can-*` properties are read from the player each time they are
   * read, and the other properties are not available. Use it for one-shot
   * commands such as play or next.
   */
  obj_properties[PROP_LOAD_PROPERTIES] = g_param_spec_boolean (
      "load-properties", "Load properties",
      "Whether to fetch all the properties of the player when connecting",
      TRUE,
      G_PARAM_CONSTRUCT_ONLY | G_PARAM_READWRITE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_POSITION] = g_param_spec_int64 (
      "position", "Player position",
      "The position in the current track of the player in microseconds", 0,
      INT64_MAX, 0, G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_METADATA] = g_param_spec_variant (
      "metadata", "Player metadata",
      "The metadata of the currently playing track as an array of key-value "
      "pairs. The metadata available depends on the track, but may include "
      "the "
      "artist, title, length, art url, and other metadata.",
      G_VARIANT_TYPE_VARDICT, NULL, G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_CONTROL] = g_param_spec_boolean (
      "can-control", "Can control",
      "Whether the player can be controlled by playerctl", FALSE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_PLAY] = g_param_spec_boolean (
      "can-play", "Can play",
      "Whether the player can start playing and has a "
      "current track.",
      FALSE, G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_PAUSE] = g_param_spec_boolean (
      "can-pause", "Can pause", "Whether the player can pause", FALSE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_SEEK] = g_param_spec_boolean (
      "can-seek", "Can seek",
      "Whether the position of the player can be controlled", FALSE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_GO_NEXT] = g_param_spec_boolean (
      "can-go-next", "Can go next",
      "Whether the player can go to the next track", FALSE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);

  obj_properties[PROP_CAN_GO_PREVIOUS] = g_param_spec_boolean (
      "can-go-previous", "Can go previous",
      "Whether the player can go to the previous track", FALSE,
      G_PARAM_READABLE | G_PARAM_STATIC_STRINGS);
}

static void
player_install_signals (void)
{
  /**
   * PlayerctlPlayer::playback-status:
   * @player: the player this event was emitted on
   * @playback_status: the playback status of the player
   *
   * Emitted when the playback status changes. Detail will be "playing",
   * "paused", or "stopped" which you can listen to by connecting to the
   * "playback-status::[STATUS]" signal.
   */
  connection_signals[PLAYBACK_STATUS] = player_signal_new (
      "playback-status", G_SIGNAL_RUN_FIRST | G_SIGNAL_DETAILED,
      g_cclosure_marshal_VOID__ENUM, playerctl_playback_status_get_type ());

  /**
   * PlayerctlPlayer::loop-status:
   * @player: the player this event was emitted on
   * @loop_status: the loop status of the player
   *
   * Emitted when the loop status changes.
   */
  connection_signals[LOOP_STATUS] = player_signal_new (
      "loop-status", G_SIGNAL_RUN_FIRST | G_SIGNAL_DETAILED,
      g_cclosure_marshal_VOID__ENUM, playerctl_loop_status_get_type ());

  /**
   * PlayerctlPlayer::shuffle:
   * @player: the player this event was emitted on
   * @shuffle_status: the shuffle status of the player
   *
   * Emitted when the shuffle status changes.
   */
  connection_signals[SHUFFLE]
      = player_signal_new ("shuffle", G_SIGNAL_RUN_FIRST,
                           g_cclosure_marshal_VOID__BOOLEAN, G_TYPE_BOOLEAN);

  /**
   * PlayerctlPlayer::play:
   * @player: the player this event was emitted on
   *
   * Emitted when the player begins to play.
   *
   * Deprecated:2.0.0: Use the "playback-status::playing" signal instead.
   */
  connection_signals[PLAY]
      = player_signal_new ("play", G_SIGNAL_RUN_FIRST | G_SIGNAL_DEPRECATED,
                           g_cclosure_marshal_VOID__VOID, G_TYPE_NONE);

  /**
   * PlayerctlPlayer::pause:
   * @player: the player this event was emitted on
   *
   * Emitted when the player pauses.
   *
   * Deprecated:2.0.0: Use the "playback-status::paused" signal instead.
   */
  connection_signals[PAUSE]
      = player_signal_new ("pause", G_SIGNAL_RUN_FIRST | G_SIGNAL_DEPRECATED,
                           g_cclosure_marshal_VOID__VOID, G_TYPE_NONE);

  /**
   * PlayerctlPlayer::stop:
   * @player: the player this event was emitted on
   *
   * Emitted when the player stops.
   *
   * Deprecated:2.0.0: Use the "playback-status::stopped" signal instead.
   */
  connection_signals[STOP]
      = player_signal_new ("stop", G_SIGNAL_RUN_FIRST | G_SIGNAL_DEPRECATED,
                           g_cclosure_marshal_VOID__VOID, G_TYPE_NONE);
}

static void
player_install_more_signals (void)
{
  /**
   * PlayerctlPlayer::metadata:
   * @player: the player this event was emitted on
   * @metadata: the metadata for the currently playing track.
   *
   * Emitted when the metadata for the currently playing track changes.
   */
  connection_signals[METADATA]
      = player_signal_new ("metadata", G_SIGNAL_RUN_FIRST,
                           g_cclosure_marshal_VOID__VARIANT, G_TYPE_VARIANT);

  /**
   * PlayerctlPlayer::volume:
   * @player: the player this event was emitted on
   * @volume: the volume of the player from 0 to 100.
   *
   * Emitted when the volume of the player changes.
   */
  connection_signals[VOLUME]
      = player_signal_new ("volume", G_SIGNAL_RUN_FIRST,
                           g_cclosure_marshal_VOID__DOUBLE, G_TYPE_DOUBLE);

  /**
   * PlayerctlPlayer::seeked:
   * @player: the player this event was emitted on.
   * @position: the new position in the track in microseconds.
   *
   * Emitted when the track changes position unexpectedly or begins in a
   * position other than the beginning. Otherwise, position is assumed to
   * progress normally.
   */
  /* FIXME: g_cclosure_marshal_VOID__LONG reads a glong but the parameter is
     G_TYPE_INT64; on 32-bit targets (long is 32 bits) the position is
     truncated. Use g_cclosure_marshal_generic or a VOID__INT64 marshaller. */
  connection_signals[SEEKED]
      = player_signal_new ("seeked", G_SIGNAL_RUN_FIRST,
                           g_cclosure_marshal_VOID__LONG, G_TYPE_INT64);

  /**
   * PlayerctlPlayer::exit:
   * @player: the player this event was emitted on.
   *
   * Emitted when the player has disconnected and will no longer respond to
   * queries and commands.
   */
  connection_signals[EXIT] = player_signal_new (
      "exit", G_SIGNAL_RUN_FIRST, g_cclosure_marshal_VOID__VOID, G_TYPE_NONE);
}

static void
playerctl_player_class_init (PlayerctlPlayerClass *klass)
{
  GObjectClass *gobject_class = G_OBJECT_CLASS (klass);

  gobject_class->set_property = playerctl_player_set_property;
  gobject_class->get_property = playerctl_player_get_property;
  gobject_class->constructed = playerctl_player_constructed;
  gobject_class->dispose = playerctl_player_dispose;
  gobject_class->finalize = playerctl_player_finalize;

  player_define_properties ();
  player_define_state_properties ();
  g_object_class_install_properties (gobject_class, N_PROPERTIES,
                                     obj_properties);

  player_install_signals ();
  player_install_more_signals ();
}

static void
playerctl_player_init (PlayerctlPlayer *self)
{
  self->priv = playerctl_player_get_instance_private (self);
}

/*
 * Get the matching bus name for this player name. Bus name will be like:
 * "org.mpris.MediaPlayer2.{PLAYER_NAME}[.{INSTANCE}]"
 * Pass a NULL player_name to get the first name on the bus
 * Returns NULL if no matching bus name is found on the bus.
 * Returns an error if there was a problem listing the names on the bus.
 */
/* STYLE: name is not modified; take const gchar *. */
static gchar *
bus_name_for_player_name (gchar *name, GBusType bus_type, GError **err)
{
  gchar *bus_name = NULL;
  GError *tmp_error = NULL;
  PlayerctlSource source = pctl_bus_type_to_source (bus_type);

  g_return_val_if_fail (err == NULL || *err == NULL, NULL);

  GList *names = pctl_list_player_names_on_bus (bus_type, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return NULL;
    }

  if (names == NULL)
    {
      return NULL;
    }

  GList *match = NULL;
  if (name == NULL)
    {
      g_debug ("Getting bus name for first available player");
      match = names;
    }
  else
    {
      match = pctl_player_name_find (names, name, source);
      if (match != NULL)
        {
          g_debug ("Getting bus name for player %s by exact match", name);
        }
      else
        {
          match = pctl_player_name_find_instance (names, name, source);
          if (match != NULL)
            {
              g_debug ("Getting bus name for player %s by instance match",
                       name);
            }
        }
    }

  if (match != NULL)
    {
      PlayerctlPlayerName *match_name = match->data;
      bus_name = g_strdup_printf (MPRIS_PREFIX "%s", match_name->instance);
    }

  pctl_player_name_list_destroy (names);
  return bus_name;
}

static void
playerctl_player_name_owner_changed_callback (GObject *object,
                                              GParamSpec *pspec,
                                              gpointer *user_data)
{
  PlayerctlPlayer *player = PLAYERCTL_PLAYER (user_data);
  GDBusProxy *proxy = G_DBUS_PROXY (object);
  char *name_owner = g_dbus_proxy_get_name_owner (proxy);

  if (name_owner == NULL)
    {
      g_signal_emit (player, connection_signals[EXIT], 0);
    }

  g_free (name_owner);
}

static gboolean
playerctl_player_initable_init (GInitable *initable, GCancellable *cancellable,
                                GError **err)
{
  GError *tmp_error = NULL;
  PlayerctlPlayer *player = PLAYERCTL_PLAYER (initable);

  if (player->priv->initted)
    {
      return TRUE;
    }

  g_return_val_if_fail (err == NULL || *err == NULL, FALSE);

  if (player->priv->instance != NULL && player->priv->player_name != NULL)
    {
      // if instance is specified, ignore name
      g_free (player->priv->player_name);
      player->priv->player_name = NULL;
    }

  if (player->priv->instance != NULL
      && player->priv->source == PLAYERCTL_SOURCE_NONE)
    {
      g_set_error (
          err, playerctl_player_error_quark (), 3,
          "A player cannot be constructed with an instance and no source");
      return FALSE;
    }

  gchar *bus_name = NULL;
  if (player->priv->instance != NULL)
    {
      bus_name = g_strdup_printf (MPRIS_PREFIX "%s", player->priv->instance);
    }
  else if (player->priv->source != PLAYERCTL_SOURCE_NONE)
    {
      // the source was specified
      bus_name = bus_name_for_player_name (
          player->priv->player_name,
          pctl_source_to_bus_type (player->priv->source), &tmp_error);
      if (tmp_error)
        {
          g_propagate_error (err, tmp_error);
          return FALSE;
        }
    }
  else
    {
      // the source was not specified
      const GBusType bus_types[] = { G_BUS_TYPE_SESSION, G_BUS_TYPE_SYSTEM };
      /* STYLE: int index compared with the size_t from LENGTH(); use gsize. */
      for (int i = 0; i < LENGTH (bus_types); ++i)
        {
          bus_name = bus_name_for_player_name (player->priv->player_name,
                                               bus_types[i], &tmp_error);
          if (tmp_error != NULL)
            {
              g_propagate_error (err, tmp_error);
              return FALSE;
            }
          if (bus_name != NULL)
            {
              player->priv->source = pctl_bus_type_to_source (bus_types[i]);
              break;
            }
        }
    }

  if (bus_name == NULL)
    {
      g_set_error (err, playerctl_player_error_quark (), 1,
                   "Player not found");
      return FALSE;
    }
  /* FIXME: priv->instance is never set for a player created by
     playerctl_player_new() or _new_for_source() (only _new_from_name()
     passes "player-instance"), so "player-instance" reads NULL, the debug
     lines that print it show (null), and playerctl-formatter.c passes that
     NULL to g_variant_new_string(). Derive the instance from bus_name here. */
  player->priv->bus_name = bus_name;

  /* org.mpris.MediaPlayer2.{NAME}[.{INSTANCE}] */
  /* STYLE: strlen() (size_t) is stored in an int. */
  int offset = strlen (MPRIS_PREFIX);
  g_free (player->priv->player_name);
  player->priv->player_name = pctl_player_base_name (bus_name + offset);

  player->priv->proxy = org_mpris_media_player2_player_proxy_new_for_bus_sync (
      pctl_source_to_bus_type (player->priv->source),
      player->priv->load_properties
          ? G_DBUS_PROXY_FLAGS_GET_INVALIDATED_PROPERTIES
          : G_DBUS_PROXY_FLAGS_DO_NOT_LOAD_PROPERTIES,
      bus_name, MPRIS_PATH, NULL, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return FALSE;
    }

  // init the cache
  g_debug ("initializing player: %s", player->priv->instance);
  player->priv->cached_position
      = org_mpris_media_player2_player_get_position (player->priv->proxy);
  clock_gettime (CLOCK_MONOTONIC, &player->priv->cached_position_monotonic);

  const gchar *playback_status_str
      = org_mpris_media_player2_player_get_playback_status (
          player->priv->proxy);

  // a missing or unknown status is not "playing" (the zero value); the parser
  // leaves status untouched on failure
  PlayerctlPlaybackStatus status = PLAYERCTL_PLAYBACK_STATUS_STOPPED;
  (void)pctl_parse_playback_status (playback_status_str, &status);
  player->priv->cached_status = status;

  // the track the client found, so that a change of the same track keeps the
  // position
  GVariant *metadata
      = org_mpris_media_player2_player_dup_metadata (player->priv->proxy);
  if (metadata != NULL)
    {
      player->priv->cached_track_id = metadata_get_track_id (metadata);
      g_variant_unref (metadata);
    }

  g_signal_connect (player->priv->proxy, "g-properties-changed",
                    G_CALLBACK (playerctl_player_properties_changed_callback),
                    player);

  g_signal_connect (player->priv->proxy, "seeked",
                    G_CALLBACK (playerctl_player_seeked_callback), player);

  g_signal_connect (player->priv->proxy, "notify::g-name-owner",
                    G_CALLBACK (playerctl_player_name_owner_changed_callback),
                    player);

  player->priv->initted = TRUE;
  return TRUE;
}

static void
playerctl_player_initable_iface_init (GInitableIface *iface)
{
  iface->init = playerctl_player_initable_init;
}

/**
 * playerctl_list_players:
 * @err: The location of a GError or NULL
 *
 * Lists all the players that can be controlled by Playerctl.
 *
 * Returns:(transfer full) (element-type PlayerctlPlayerName): A list of player
 * names.
 */
GList *
playerctl_list_players (GError **err)
{
  GError *tmp_error = NULL;

  g_return_val_if_fail (err == NULL || *err == NULL, NULL);

  GList *session_players
      = pctl_list_player_names_on_bus (G_BUS_TYPE_SESSION, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      return NULL;
    }

  GList *system_players
      = pctl_list_player_names_on_bus (G_BUS_TYPE_SYSTEM, &tmp_error);
  if (tmp_error != NULL)
    {
      pctl_player_name_list_destroy (session_players);
      g_propagate_error (err, tmp_error);
      return NULL;
    }

  GList *players = g_list_concat (session_players, system_players);

  return players;
}

/**
 * playerctl_player_new:
 * @player_name:(allow-none): The name to use to find the bus name of the
 * player
 * @err: The location of a GError or NULL
 *
 * Allocates a new #PlayerctlPlayer and tries to connect to an instance of the
 * player with the given name.
 *
 * Returns:(transfer full): A new #PlayerctlPlayer connected to an instance of
 * the player or NULL if an error occurred
 */
PlayerctlPlayer *
playerctl_player_new (const gchar *player_name, GError **err)
{
  return player_new_with_properties (err, "player-name", player_name, NULL);
}

/**
 * playerctl_player_new_for_source:
 * @player_name:(allow-none): The name to use to find the bus name of the
 * player
 * @source: The source where the player name is.
 * @err: The location of a GError or NULL
 *
 * Allocates a new #PlayerctlPlayer and tries to connect to an instance of the
 * player with the given name from the given source.
 *
 * Returns:(transfer full): A new #PlayerctlPlayer connected to an instance of
 * the player or NULL if an error occurred
 */
PlayerctlPlayer *
playerctl_player_new_for_source (const gchar *player_name,
                                 PlayerctlSource source, GError **err)
{
  return player_new_with_properties (err, "player-name", player_name, "source",
                                     source, NULL);
}

/**
 * playerctl_player_new_from_name:
 * @player_name: The name type to use to find the player
 * @err:(allow-none): The location of a GError or NULL
 *
 * Allocates a new #PlayerctlPlayer and tries to connect to the player
 * identified by the #PlayerctlPlayerName.
 *
 * Returns:(transfer full): A new #PlayerctlPlayer connected to the player or
 * NULL if an error occurred
 */
/* XXX: SUSPICIOUS: player_name is dereferenced without g_return_val_if_fail
   (player_name != NULL, NULL). */
PlayerctlPlayer *
playerctl_player_new_from_name (PlayerctlPlayerName *player_name, GError **err)
{
  return player_new_with_properties (err, "player-instance",
                                     player_name->instance, "source",
                                     player_name->source, NULL);
}

/* XXX: SUSPICIOUS: playerctl.syms exports pctl_*, so these internal helpers
   become part of the library ABI. No NULL check either. */
char *
pctl_player_get_instance (PlayerctlPlayer *player)
{
  return player->priv->instance;
}

/* STYLE: bool here but gboolean everywhere else in this file. */
bool
pctl_player_has_cached_property (PlayerctlPlayer *player, const gchar *name)
{
  GVariant *value = g_dbus_proxy_get_cached_property (
      G_DBUS_PROXY (player->priv->proxy), name);
  if (value == NULL)
    {
      return false;
    }
  g_variant_unref (value);
  return true;
}

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

#include <assert.h>
#include <gio/gio.h>
#include <stdbool.h>
#include <stdio.h>

#include "playerctl-common.h"

#define MPRIS_PATH "/org/mpris/MediaPlayer2"
#define DBUS_NAME "org.freedesktop.DBus"
#define DBUS_INTERFACE "org.freedesktop.DBus"
#define DBUS_PATH "/org/freedesktop/DBus"
#define PLAYER_INTERFACE "org.mpris.MediaPlayer2.Player"
#define ROOT_INTERFACE "org.mpris.MediaPlayer2"
#define PLAYLISTS_INTERFACE "org.mpris.MediaPlayer2.Playlists"
#define TRACKLIST_INTERFACE "org.mpris.MediaPlayer2.TrackList"
#define PROPERTIES_INTERFACE "org.freedesktop.DBus.Properties"

/**
 * The optional MPRIS interfaces, with the properties invalidated for them when
 * no player is left
 */
#define N_OPTIONAL 2
static const struct
{
  const char *name;
  const gchar *const *invalidated;
} optional_interfaces[N_OPTIONAL] = {
  { TRACKLIST_INTERFACE,
    (const gchar *const[]){ "Tracks", "CanEditTracks", NULL } },
  { PLAYLISTS_INTERFACE, (const gchar *const[]){ "PlaylistCount", "Orderings",
                                                 "ActivePlaylist", NULL } },
};

static int
optional_index (const char *interface_name)
{
  for (int i = 0; i < N_OPTIONAL; i++)
    {
      if (g_strcmp0 (interface_name, optional_interfaces[i].name) == 0)
        {
          return i;
        }
    }
  return -1;
}

/**
 * A representation of an MPRIS player and its cached MPRIS properties
 */
struct Player
{
  char *unique;
  char *well_known;
  gint64 position;
  GVariant *player_properties;
  GVariant *root_properties;
  // org.mpris.MediaPlayer2.TrackList and org.mpris.MediaPlayer2.Playlists are
  // optional: the player supports one while its properties are not NULL
  GVariant *optional_properties[N_OPTIONAL];
  // cancelled when the player goes away, so late replies skip it
  GCancellable *cancellable;
};

struct PlayerctldContext
{
  GMainLoop *loop;
  gint bus_id;
  gchar *bus_address;
  GDBusConnection *connection;
  GDBusInterfaceInfo *root_interface_info;
  GDBusInterfaceInfo *player_interface_info;
  GDBusInterfaceInfo *playlists_interface_info;
  GDBusInterfaceInfo *tracklist_interface_info;
  GDBusInterfaceInfo *playerctld_interface_info;
  GDBusInterfaceInfo *playerctld_legacy_interface_info;
  GQueue *players;
  GQueue *pending_players;
  gint return_code;
  struct Player *pending_active;
  // bit I set: optional interface I was announced for the active player
  guint announced_optional;
};

/**
 * Allocate and create a new player, with the specified connection name and
 * well-known bus name
 */
static struct Player *
player_new (const char *unique, const char *well_known)
{
  struct Player *player = calloc (1, sizeof (struct Player));
  player->unique = g_strdup (unique);
  player->well_known = g_strdup (well_known);
  // Explicitly initialize everything else - just in case
  player->position = 0;
  player->player_properties = NULL;
  player->root_properties = NULL;
  player->cancellable = g_cancellable_new ();
  return player;
}

static void
player_set_unique_name (struct Player *player, const char *unique)
{
  g_free (player->unique);
  player->unique = g_strdup (unique);
}

static void
player_free (struct Player *name)
{
  if (name == NULL)
    {
      return;
    }
  if (name->player_properties != NULL)
    {
      g_variant_unref (name->player_properties);
    }
  if (name->root_properties != NULL)
    {
      g_variant_unref (name->root_properties);
    }
  for (int i = 0; i < N_OPTIONAL; i++)
    {
      if (name->optional_properties[i] != NULL)
        {
          g_variant_unref (name->optional_properties[i]);
        }
    }
  g_cancellable_cancel (name->cancellable);
  g_object_unref (name->cancellable);
  g_free (name->unique);
  g_free (name->well_known);
  free (name);
}

/**
 * Whether the replies to the initial property requests are enough to use the
 * player
 */
static bool
player_is_usable (struct Player *player)
{
  return player->player_properties != NULL && player->root_properties != NULL;
}

static gint
player_compare (gconstpointer a, gconstpointer b)
{
  struct Player *fn_a = (struct Player *)a;
  struct Player *fn_b = (struct Player *)b;
  if (fn_a->unique != NULL && fn_b->unique != NULL
      && strcmp (fn_a->unique, fn_b->unique) != 0)
    {
      return 1;
    }
  if (fn_a->well_known != NULL && fn_b->well_known != NULL
      && strcmp (fn_a->well_known, fn_b->well_known) != 0)
    {
      return 1;
    }

  return 0;
}

/*
 * The cached properties of one interface of the player, or NULL for an
 * interface that is not part of MPRIS
 */
static GVariant **
player_cache_for (struct Player *player, const char *interface_name)
{
  if (g_strcmp0 (interface_name, PLAYER_INTERFACE) == 0)
    {
      return &player->player_properties;
    }
  if (g_strcmp0 (interface_name, ROOT_INTERFACE) == 0)
    {
      return &player->root_properties;
    }
  int optional = optional_index (interface_name);
  return optional < 0 ? NULL : &player->optional_properties[optional];
}

static void
player_cache_position (struct Player *player, GVariant *position)
{
  if (g_variant_is_of_type (position, G_VARIANT_TYPE_INT64))
    {
      player->position = g_variant_get_int64 (position);
    }
  else
    {
      g_debug ("%s: ignoring Position of type %s", player->well_known,
               g_variant_get_type_string (position));
    }
}

/*
 * Updates the properties for the player. Returns TRUE if the properties have
 * changed, or else FALSE.
 */
static gboolean
player_update_properties (struct Player *player, const char *interface_name,
                          GVariant *properties)
{
  gboolean changed = FALSE;
  GVariantDict cached_properties;
  GVariantIter iter;
  GVariant *child;
  GVariant **cache = player_cache_for (player, interface_name);

  if (cache == NULL)
    {
      // a misbehaving player must not take the daemon down
      // (altdesktop/playerctl#268)
      g_warning ("cannot update properties for unknown interface: %s",
                 interface_name);
      return FALSE;
    }
  g_variant_dict_init (&cached_properties, *cache);
  if (!g_variant_is_of_type (properties, G_VARIANT_TYPE_VARDICT))
    {
      g_warning ("cannot update properties with unknown type: %s",
                 g_variant_get_type_string (properties));
      g_variant_dict_clear (&cached_properties);
      return FALSE;
    }
  g_variant_iter_init (&iter, properties);

  while ((child = g_variant_iter_next_value (&iter)))
    {
      GVariant *key_variant = g_variant_get_child_value (child, 0);
      const gchar *key = g_variant_get_string (key_variant, 0);
      GVariant *prop_variant = g_variant_get_child_value (child, 1);
      GVariant *prop_value = g_variant_get_variant (prop_variant);
      // g_debug("key=%s, value=%s", key, g_variant_print(prop_value, TRUE));
      if (cache == &player->player_properties
          && g_strcmp0 (key, "Position") == 0)
        {
          // gets cached separately (never counts as changed)
          player_cache_position (player, prop_value);
          goto loop_out;
        }
      GVariant *cache_value
          = g_variant_dict_lookup_value (&cached_properties, key, NULL);
      if (cache_value != NULL)
        {
          if (!g_variant_equal (cache_value, prop_value))
            {
              g_debug ("%s: changed property '%s.%s'", player->well_known,
                       interface_name, key);
              // g_debug("old = %s, new = %s", g_variant_print(cache_value,
              // FALSE),
              changed = TRUE;
            }
          g_variant_unref (cache_value);
        }
      else
        {
          g_debug ("%s: new property '%s.%s'", player->well_known,
                   interface_name, key);
          changed = TRUE;
        }
      g_variant_dict_insert_value (&cached_properties, key, prop_value);
    loop_out:
      g_variant_unref (prop_value);
      g_variant_unref (prop_variant);
      g_variant_unref (key_variant);
      g_variant_unref (child);
    }

  if (*cache != NULL)
    {
      g_variant_unref (*cache);
    }
  *cache = g_variant_ref_sink (g_variant_dict_end (&cached_properties));

  return changed;
}

static void
player_update_position_sync (struct Player *player,
                             struct PlayerctldContext *ctx, GError **error)
{
  GError *tmp_error = NULL;
  g_return_if_fail (error == NULL || *error == NULL);
  g_debug ("updating position for player unique='%s', well_known='%s'",
           player->unique, player->well_known);
  GVariant *reply = g_dbus_connection_call_sync (
      ctx->connection, player->unique, MPRIS_PATH, PROPERTIES_INTERFACE, "Get",
      g_variant_new ("(ss)", PLAYER_INTERFACE, "Position"), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return;
    }
  GVariant *position_unwrapped = g_variant_get_child_value (reply, 0);
  GVariant *position_variant = g_variant_get_variant (position_unwrapped);
  if (g_variant_is_of_type (position_variant, G_VARIANT_TYPE_INT64))
    {
      player->position = g_variant_get_int64 (position_variant);
      g_debug ("new position: %ld", player->position);
    }
  else
    {
      g_set_error (error, G_IO_ERROR, G_IO_ERROR_INVALID_DATA,
                   "Position has type %s, expected x",
                   g_variant_get_type_string (position_variant));
    }
  g_variant_unref (position_variant);
  g_variant_unref (position_unwrapped);
  g_variant_unref (reply);
}

/**
 * Fetch and cache the properties of one interface of the player
 */
static gboolean
player_fetch_properties_sync (struct Player *player,
                              struct PlayerctldContext *ctx,
                              const char *interface_name, GError **error)
{
  GVariant *reply = g_dbus_connection_call_sync (
      ctx->connection, player->unique, MPRIS_PATH, PROPERTIES_INTERFACE,
      "GetAll", g_variant_new ("(s)", interface_name), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, error);
  if (reply == NULL)
    {
      return FALSE;
    }
  GVariant *properties = g_variant_get_child_value (reply, 0);
  player_update_properties (player, interface_name, properties);
  g_variant_unref (properties);
  g_variant_unref (reply);
  return TRUE;
}

static GVariant *
context_player_names_to_gvariant (struct PlayerctldContext *ctx)
{
  GVariantBuilder builder;
  g_variant_builder_init (&builder, G_VARIANT_TYPE_STRING_ARRAY);
  guint len = g_queue_get_length (ctx->players);
  for (int i = 0; i < len; ++i)
    {
      struct Player *current = g_queue_pop_head (ctx->players);
      g_variant_builder_add_value (&builder,
                                   g_variant_new_string (current->well_known));
      g_queue_push_tail (ctx->players, current);
    }

  return g_variant_builder_end (&builder);
}

static const char *const playerctld_interfaces[]
    = { PLAYERCTLD_INTERFACE, PLAYERCTLD_INTERFACE_LEGACY };

/**
 * Emit PropertiesChanged for one interface; CHANGED (NULL for none) is
 * consumed if floating, INVALIDATED is a NULL terminated list (NULL for none)
 */
static gboolean
context_emit_properties_changed (struct PlayerctldContext *ctx,
                                 const char *interface_name, GVariant *changed,
                                 const gchar *const *invalidated,
                                 GError **error)
{
  static const gchar *const no_names[] = { NULL };
  if (changed == NULL)
    {
      changed = g_variant_new_array (G_VARIANT_TYPE ("{sv}"), NULL, 0);
    }
  return g_dbus_connection_emit_signal (
      ctx->connection, NULL, MPRIS_PATH, PROPERTIES_INTERFACE,
      "PropertiesChanged",
      g_variant_new ("(s@a{sv}@as)", interface_name, changed,
                     g_variant_new_strv (
                         invalidated != NULL ? invalidated : no_names, -1)),
      error);
}

static const gchar *const player_invalidated[]
    = { "CanControl",  "CanGoNext",   "CanGoPrevious",  "CanPause",
        "CanPlay",     "CanSeek",     "Shuffle",        "Metadata",
        "MaximumRate", "MinimumRate", "Rate",           "Volume",
        "Position",    "LoopStatus",  "PlaybackStatus", NULL };
static const gchar *const root_invalidated[] = { "SupportedMimeTypes",
                                                 "SupportedUriSchemes",
                                                 "CanQuit",
                                                 "CanRaise",
                                                 "CanSetFullScreen",
                                                 "HasTrackList",
                                                 "DesktopEntry",
                                                 "Identity",
                                                 NULL };

/**
 * Announce the optional interfaces of the player; one the player lacks is
 * invalidated if it was announced before (or when there is no player)
 */
static gboolean
context_emit_optional_properties (struct PlayerctldContext *ctx,
                                  struct Player *player, GError **error)
{
  for (int i = 0; i < N_OPTIONAL; i++)
    {
      GVariant *properties = player ? player->optional_properties[i] : NULL;
      guint bit = 1u << i;
      if (properties == NULL && player != NULL
          && !(ctx->announced_optional & bit))
        {
          continue;
        }
      if (!context_emit_properties_changed (
              ctx, optional_interfaces[i].name, properties,
              properties ? NULL : optional_interfaces[i].invalidated, error))
        {
          return FALSE;
        }
      ctx->announced_optional = properties ? ctx->announced_optional | bit
                                           : ctx->announced_optional & ~bit;
    }
  return TRUE;
}

/**
 * Announce the properties of the active player and its Seeked position, or
 * invalidate them when there is none
 */
static gboolean
context_emit_player_properties (struct PlayerctldContext *ctx,
                                struct Player *player, GError **error)
{
  g_debug ("emitting %s signals for the active player",
           player != NULL ? "property" : "invalidated property");
  if (!context_emit_properties_changed (
          ctx, PLAYER_INTERFACE, player ? player->player_properties : NULL,
          player ? NULL : player_invalidated, error)
      || !context_emit_properties_changed (
          ctx, ROOT_INTERFACE, player ? player->root_properties : NULL,
          player ? NULL : root_invalidated, error))
    {
      return FALSE;
    }
  if (!context_emit_optional_properties (ctx, player, error))
    {
      return FALSE;
    }
  if (player == NULL)
    {
      return TRUE;
    }
  g_debug ("sending Seeked signal with position %ld", player->position);
  return g_dbus_connection_emit_signal (
      ctx->connection, NULL, MPRIS_PATH, PLAYER_INTERFACE, "Seeked",
      g_variant_new ("(x)", player->position), error);
}

static void
context_emit_active_player_changed (struct PlayerctldContext *ctx,
                                    GError **error)
{
  g_return_if_fail (error == NULL || *error == NULL);

  struct Player *player = g_queue_peek_head (ctx->players);

  for (gsize i = 0; i < G_N_ELEMENTS (playerctld_interfaces); i++)
    {
      if (!g_dbus_connection_emit_signal (
              ctx->connection, NULL, MPRIS_PATH, playerctld_interfaces[i],
              "ActivePlayerChangeBegin",
              g_variant_new ("(s)",
                             (player != NULL ? player->well_known : "")),
              error))
        {
          return;
        }
    }

  if (player != NULL && !player_is_usable (player))
    {
      g_warning ("active player '%s' has no properties, not announcing it",
                 player->well_known);
    }
  else if (!context_emit_player_properties (ctx, player, error))
    {
      return;
    }

  for (gsize i = 0; i < G_N_ELEMENTS (playerctld_interfaces); i++)
    {
      GVariantDict dict;
      g_variant_dict_init (&dict, NULL);
      g_variant_dict_insert_value (&dict, "PlayerNames",
                                   context_player_names_to_gvariant (ctx));
      if (!context_emit_properties_changed (ctx, playerctld_interfaces[i],
                                            g_variant_dict_end (&dict), NULL,
                                            error))
        {
          return;
        }
    }
  for (gsize i = 0; i < G_N_ELEMENTS (playerctld_interfaces); i++)
    {
      if (!g_dbus_connection_emit_signal (
              ctx->connection, NULL, MPRIS_PATH, playerctld_interfaces[i],
              "ActivePlayerChangeEnd",
              g_variant_new ("(s)",
                             (player != NULL ? player->well_known : "")),
              error))
        {
          return;
        }
    }
}

static struct Player *
context_find_player (struct PlayerctldContext *ctx, const char *unique,
                     const char *well_known)
{
  const struct Player find_name = {
    .unique = (char *)unique,
    .well_known = (char *)well_known,
  };
  GList *found
      = g_queue_find_custom (ctx->players, &find_name, player_compare);
  if (found != NULL)
    {
      return (struct Player *)found->data;
    }

  found
      = g_queue_find_custom (ctx->pending_players, &find_name, player_compare);
  if (found != NULL)
    {
      return (struct Player *)found->data;
    }

  return NULL;
}

static struct Player *
context_get_active_player (struct PlayerctldContext *ctx)
{
  return g_queue_peek_head (ctx->players);
}

static void
context_set_active_player (struct PlayerctldContext *ctx,
                           struct Player *player)
{
  g_queue_remove (ctx->players, player);
  g_queue_remove (ctx->pending_players, player);
  g_queue_push_head (ctx->players, player);
  ctx->pending_active = NULL;
}

static void
context_add_player (struct PlayerctldContext *ctx, struct Player *player)
{
  g_queue_remove (ctx->players, player);
  g_queue_remove (ctx->pending_players, player);
  g_queue_push_tail (ctx->players, player);
}

static void
context_add_pending_player (struct PlayerctldContext *ctx,
                            struct Player *player)
{
  g_queue_remove (ctx->players, player);
  g_queue_remove (ctx->pending_players, player);
  g_queue_push_tail (ctx->pending_players, player);
}

static void
context_remove_player (struct PlayerctldContext *ctx, struct Player *player)
{
  g_queue_remove (ctx->players, player);
  g_queue_remove (ctx->pending_players, player);
  if (ctx->pending_active == player)
    {
      ctx->pending_active = NULL;
    }
}

static void
context_unrotate_queue (struct PlayerctldContext *ctx)
{
  struct Player *player = g_queue_peek_tail (ctx->players);
  if (player != NULL)
    {
      context_remove_player (ctx, player);
      g_queue_push_head (ctx->players, player);
    }
}

/**
 * Returns the newly activated player
 */
static struct Player *
context_shift_active_player (struct PlayerctldContext *ctx)
{
  GError *error = NULL;
  struct Player *previous = context_get_active_player (ctx);

  if (previous == NULL)
    {
      return NULL;
    }
  context_remove_player (ctx, previous);
  context_add_player (ctx, previous);
  struct Player *current = context_get_active_player (ctx);
  if (current != previous)
    {
      player_update_position_sync (current, ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not update player position: %s", error->message);
          g_clear_error (&error);
        }
      context_emit_active_player_changed (ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not emit active player change: %s",
                     error->message);
          g_clear_error (&error);
        }
    }
  return current;
}

static struct Player *
context_unshift_active_player (struct PlayerctldContext *ctx)
{
  GError *error = NULL;
  struct Player *previous = context_get_active_player (ctx);

  if (previous == NULL)
    {
      return NULL;
    }

  context_unrotate_queue (ctx);

  struct Player *current = context_get_active_player (ctx);
  if (current != previous)
    {
      player_update_position_sync (current, ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not update player position: %s", error->message);
          g_clear_error (&error);
        }
      context_emit_active_player_changed (ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not emit active player change: %s",
                     error->message);
          g_clear_error (&error);
        }
    }
  return current;
}

#define LEGACY_DEPRECATED_ANNOTATION                                          \
  "    <annotation name=\"org.freedesktop.DBus.Deprecated\" "                 \
  "value=\"true\"/>\n"

#define PLAYERCTLD_INTERFACE_XML(name, annotation)                            \
  "  <interface name=\"" name "\">\n" annotation                              \
  "    <method name=\"Shift\">\n"                                             \
  "        <arg name=\"Player\" type=\"s\" direction=\"out\"/>\n"             \
  "    </method>\n"                                                           \
  "    <method name=\"Unshift\">\n"                                           \
  "        <arg name=\"Player\" type=\"s\" direction=\"out\"/>\n"             \
  "    </method>\n"                                                           \
  "    <property name=\"PlayerNames\" type=\"as\" access=\"read\"/>\n"        \
  "    <signal name=\"ActivePlayerChangeBegin\">\n"                           \
  "        <arg name=\"Name\" type=\"s\"/>\n"                                 \
  "    </signal>\n"                                                           \
  "    <signal name=\"ActivePlayerChangeEnd\">\n"                             \
  "        <arg name=\"Name\" type=\"s\"/>\n"                                 \
  "    </signal>\n"                                                           \
  "  </interface>\n"

static const char *playerctld_introspection_xml
    = "<node>\n" PLAYERCTLD_INTERFACE_XML (PLAYERCTLD_INTERFACE, "")
        PLAYERCTLD_INTERFACE_XML (PLAYERCTLD_INTERFACE_LEGACY,
                                  LEGACY_DEPRECATED_ANNOTATION) "</node>\n";

static const char *mpris_introspection_xml
    = "<node>\n"
      "  <interface name=\"org.mpris.MediaPlayer2\">\n"
      "    <method name=\"Raise\">\n"
      "    </method>\n"
      "    <method name=\"Quit\">\n"
      "    </method>\n"
      "    <property name=\"CanQuit\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"Fullscreen\" type=\"b\" access=\"readwrite\"/>\n"
      "    <property name=\"CanSetFullscreen\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanRaise\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"HasTrackList\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"Identity\" type=\"s\" access=\"read\"/>\n"
      "    <property name=\"DesktopEntry\" type=\"s\" access=\"read\"/>\n"
      "    <property name=\"SupportedUriSchemes\" type=\"as\" "
      "access=\"read\"/>\n"
      "    <property name=\"SupportedMimeTypes\" type=\"as\" "
      "access=\"read\"/>\n"
      "  </interface>\n"
      "  <interface name=\"org.mpris.MediaPlayer2.Player\">\n"
      "    <method name=\"Next\">\n"
      "    </method>\n"
      "    <method name=\"Previous\">\n"
      "    </method>\n"
      "    <method name=\"Pause\">\n"
      "    </method>\n"
      "    <method name=\"PlayPause\">\n"
      "    </method>\n"
      "    <method name=\"Stop\">\n"
      "    </method>\n"
      "    <method name=\"Play\">\n"
      "    </method>\n"
      "    <method name=\"Seek\">\n"
      "      <arg type=\"x\" name=\"Offset\" direction=\"in\"/>\n"
      "    </method>\n"
      "    <method name=\"SetPosition\">\n"
      "      <arg type=\"o\" name=\"TrackId\" direction=\"in\"/>\n"
      "      <arg type=\"x\" name=\"Offset\" direction=\"in\"/>\n"
      "    </method>\n"
      "    <method name=\"OpenUri\">\n"
      "      <arg type=\"s\" name=\"Uri\" direction=\"in\"/>\n"
      "    </method>\n"
      "    <signal name=\"Seeked\">\n"
      "      <arg type=\"x\" name=\"Position\" direction=\"out\"/>\n"
      "    </signal>\n"
      "    <property name=\"PlaybackStatus\" type=\"s\" access=\"read\"/>\n"
      "    <property name=\"LoopStatus\" type=\"s\" access=\"readwrite\"/>\n"
      "    <property name=\"Rate\" type=\"d\" access=\"readwrite\"/>\n"
      "    <property name=\"Shuffle\" type=\"b\" access=\"readwrite\"/>\n"
      "    <property name=\"Metadata\" type=\"a{sv}\" access=\"read\"/>\n"
      "    <property name=\"Volume\" type=\"d\" access=\"readwrite\"/>\n"
      "    <property name=\"Position\" type=\"x\" access=\"read\"/>\n"
      "    <property name=\"MinimumRate\" type=\"d\" access=\"read\"/>\n"
      "    <property name=\"MaximumRate\" type=\"d\" access=\"read\"/>\n"
      "    <property name=\"CanGoNext\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanGoPrevious\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanPlay\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanPause\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanSeek\" type=\"b\" access=\"read\"/>\n"
      "    <property name=\"CanControl\" type=\"b\" access=\"read\"/>\n"
      "  </interface>\n"
      "  <interface name=\"org.mpris.MediaPlayer2.TrackList\">\n"
      "    <method name=\"GetTracksMetadata\">\n"
      "      <arg direction=\"in\" name=\"TrackIds\" type=\"ao\">\n"
      "      </arg>\n"
      "      <arg direction=\"out\" type=\"aa{sv}\" name=\"Metadata\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <method name=\"AddTrack\">\n"
      "      <arg direction=\"in\" type=\"s\" name=\"Uri\">\n"
      "      </arg>\n"
      "      <arg direction=\"in\" type=\"o\" name=\"AfterTrack\">\n"
      "      </arg>\n"
      "      <arg direction=\"in\" type=\"b\" name=\"SetAsCurrent\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <method name=\"RemoveTrack\">\n"
      "      <arg direction=\"in\" type=\"o\" name=\"TrackId\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <method name=\"GoTo\">\n"
      "      <arg direction=\"in\" type=\"o\" name=\"TrackId\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <property name=\"Tracks\" type=\"ao\" access=\"read\">\n"
      "      <annotation "
      "name=\"org.freedesktop.DBus.Property.EmitsChangedSignal\" "
      "value=\"invalidates\"/>\n"
      "    </property>\n"
      "    <property name=\"CanEditTracks\" type=\"b\" access=\"read\">\n"
      "      <annotation "
      "name=\"org.freedesktop.DBus.Property.EmitsChangedSignal\" "
      "value=\"true\"/>\n"
      "    </property>\n"
      "    <signal name=\"TrackListReplaced\">\n"
      "      <arg name=\"Tracks\" type=\"ao\">\n"
      "      </arg>\n"
      "      <arg name=\"CurrentTrack\" type=\"o\">\n"
      "      </arg>\n"
      "    </signal>\n"
      "    <signal name=\"TrackAdded\">\n"
      "      <arg type=\"a{sv}\" name=\"Metadata\">\n"
      "      </arg>\n"
      "      <arg type=\"o\" name=\"AfterTrack\">\n"
      "      </arg>\n"
      "    </signal>\n"
      "    <signal name=\"TrackRemoved\">\n"
      "      <arg type=\"o\" name=\"TrackId\">\n"
      "      </arg>\n"
      "    </signal>\n"
      "    <signal name=\"TrackMetadataChanged\">\n"
      "      <arg type=\"o\" name=\"TrackId\">\n"
      "      </arg>\n"
      "      <arg type=\"a{sv}\" name=\"Metadata\">\n"
      "      </arg>\n"
      "    </signal>\n"
      "  </interface>\n"
      "  <interface name=\"org.mpris.MediaPlayer2.Playlists\">\n"
      "    <method name=\"ActivatePlaylist\">\n"
      "      <arg direction=\"in\" name=\"PlaylistId\" type=\"o\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <method name=\"GetPlaylists\">\n"
      "      <arg direction=\"in\" name=\"Index\" type=\"u\">\n"
      "      </arg>\n"
      "      <arg direction=\"in\" name=\"MaxCount\" type=\"u\">\n"
      "      </arg>\n"
      "      <arg direction=\"in\" name=\"Order\" type=\"s\">\n"
      "      </arg>\n"
      "      <arg direction=\"in\" name=\"ReverseOrder\" type=\"b\">\n"
      "      </arg>\n"
      "      <arg direction=\"out\" name=\"Playlists\" type=\"a(oss)\">\n"
      "      </arg>\n"
      "    </method>\n"
      "    <property name=\"PlaylistCount\" type=\"u\" access=\"read\">\n"
      "      <annotation "
      "name=\"org.freedesktop.DBus.Property.EmitsChangedSignal\" "
      "value=\"true\"/>\n"
      "    </property>\n"
      "    <property name=\"Orderings\" type=\"as\" access=\"read\">\n"
      "      <annotation "
      "name=\"org.freedesktop.DBus.Property.EmitsChangedSignal\" "
      "value=\"true\"/>\n"
      "    </property>\n"
      "    <property name=\"ActivePlaylist\" type=\"(b(oss))\" "
      "access=\"read\">\n"
      "      <annotation "
      "name=\"org.freedesktop.DBus.Property.EmitsChangedSignal\" "
      "value=\"true\"/>\n"
      "    </property>\n"
      "    <signal name=\"PlaylistChanged\">\n"
      "      <arg name=\"Playlist\" type=\"(oss)\">\n"
      "      </arg>\n"
      "    </signal>\n"
      "  </interface>\n"
      "</node>\n";

static void
proxy_method_call_async_callback (GObject *source_object, GAsyncResult *res,
                                  gpointer user_data)
{
  GDBusMethodInvocation *invocation = G_DBUS_METHOD_INVOCATION (user_data);
  GDBusConnection *connection = G_DBUS_CONNECTION (source_object);
  GError *error = NULL;
  GDBusMessage *reply = g_dbus_connection_send_message_with_reply_finish (
      connection, res, &error);
  if (error != NULL)
    {
      g_dbus_method_invocation_return_gerror (invocation, error);
      g_error_free (error);
      g_object_unref (invocation);
      return;
    }
  GVariant *body = g_dbus_message_get_body (reply);
  GDBusMessageType message_type = g_dbus_message_get_message_type (reply);
  switch (message_type)
    {
    case G_DBUS_MESSAGE_TYPE_METHOD_RETURN:
      g_dbus_method_invocation_return_value (invocation, body);
      break;
    case G_DBUS_MESSAGE_TYPE_ERROR:
      {
        GVariant *error_message_variant = NULL;
        const char *error_message = "Failed to call method";

        if (body != NULL && g_variant_n_children (body) > 0)
          {
            error_message_variant = g_variant_get_child_value (body, 0);
            if (g_variant_is_of_type (error_message_variant,
                                      G_VARIANT_TYPE_STRING))
              {
                error_message
                    = g_variant_get_string (error_message_variant, NULL);
              }
          }
        g_dbus_method_invocation_return_dbus_error (
            invocation, g_dbus_message_get_error_name (reply), error_message);
        if (error_message_variant != NULL)
          {
            g_variant_unref (error_message_variant);
          }
        break;
      }
    default:
      g_warning (
          "got unexpected message type: %d (this is a dbus spec violation)",
          message_type);
      g_dbus_method_invocation_return_dbus_error (
          invocation, "org.freedesktop.DBus.Error.Failed",
          "Unexpected reply from the player");
      break;
    }

  g_object_unref (invocation);
  g_object_unref (reply);
}

/**
 * Implement MPRIS method calls by delegating to the active player.
 * If there is no active player, send an error to our caller.
 */
static void
player_method_call_proxy_callback (
    GDBusConnection *connection, const char *sender, const char *object_path,
    const char *interface_name, const char *method_name, GVariant *parameters,
    GDBusMethodInvocation *invocation, gpointer user_data)
{
  g_debug ("got method call: sender=%s, object_path=%s, interface_name=%s, "
           "method_name=%s",
           sender, object_path, interface_name, method_name);
  GError *error = NULL;
  struct PlayerctldContext *ctx = user_data;
  struct Player *active_player = context_get_active_player (ctx);
  if (active_player == NULL)
    {
      g_debug ("no active player, returning error");
      // no playerctld interface is involved here, so keep the legacy name
      // existing clients match
      g_dbus_method_invocation_return_dbus_error (
          invocation, PLAYERCTLD_INTERFACE_LEGACY ".NoActivePlayer",
          "No player is being controlled by playerctld");
      return;
    }

  GDBusMessage *message = g_dbus_message_copy (
      g_dbus_method_invocation_get_message (invocation), &error);
  if (error != NULL)
    {
      g_warning ("could not copy message");
      g_dbus_method_invocation_return_gerror (invocation, error);
      return;
    }

  g_debug ("sending command '%s.%s' to player '%s'", interface_name,
           method_name, active_player->well_known);

  g_dbus_message_set_destination (message, active_player->unique);

  g_object_ref (invocation);
  g_dbus_connection_send_message_with_reply (
      ctx->connection, message, G_DBUS_SEND_MESSAGE_FLAGS_NONE, -1, NULL, NULL,
      proxy_method_call_async_callback, invocation);

  g_object_unref (message);
}

/**
 * Tell the log, once per daemon run, that a client still uses the deprecated
 * interface name
 */
static void
warn_if_legacy_interface (const char *interface_name, const char *sender)
{
  static gboolean warned = FALSE;
  if (warned || g_strcmp0 (interface_name, PLAYERCTLD_INTERFACE_LEGACY) != 0)
    {
      return;
    }
  warned = TRUE;
  g_warning ("client %s uses the deprecated D-Bus interface '%s', which will "
             "be removed in the "
             "next major version. Use '%s' instead",
             sender, PLAYERCTLD_INTERFACE_LEGACY, PLAYERCTLD_INTERFACE);
}

/**
 * Implement the playerctld methods (on both the current and legacy interface)
 */
static void
playerctld_method_call_func (GDBusConnection *connection, const char *sender,
                             const char *object_path,
                             const char *interface_name,
                             const char *method_name, GVariant *parameters,
                             GDBusMethodInvocation *invocation,
                             gpointer user_data)
{
  g_debug ("got method call: sender=%s, object_path=%s, interface_name=%s, "
           "method_name=%s",
           sender, object_path, interface_name, method_name);

  struct PlayerctldContext *ctx = user_data;
  struct Player *active_player;
  warn_if_legacy_interface (interface_name, sender);
  g_autofree gchar *no_active_player_error
      = g_strdup_printf ("%s.NoActivePlayer", interface_name);
  g_autofree gchar *invalid_method_error
      = g_strdup_printf ("%s.InvalidMethod", interface_name);

  if (strcmp (method_name, "Shift") == 0)
    {
      /**
       * playerctld.Shift
       * Move the active player to the back of the queue,
       * return the new active player
       */
      active_player = context_shift_active_player (ctx);
      if (active_player != NULL)
        {
          g_dbus_method_invocation_return_value (
              invocation, g_variant_new ("(s)", active_player->well_known));
        }
      else
        {
          g_debug ("no active player, returning error");
          g_dbus_method_invocation_return_dbus_error (
              invocation, no_active_player_error,
              "No player is being controlled by playerctld");
        }
    }
  else if (strcmp (method_name, "Unshift") == 0)
    {
      /**
       * playerctld.Unshift
       * Set the least recently active player to active,
       * return that player. Inverse of Shift.
       */
      active_player = context_unshift_active_player (ctx);
      if (active_player != NULL)
        {
          g_dbus_method_invocation_return_value (
              invocation, g_variant_new ("(s)", active_player->well_known));
        }
      else
        {
          g_debug ("no active player, returning error");
          g_dbus_method_invocation_return_dbus_error (
              invocation, no_active_player_error,
              "No player is being controlled by playerctld");
        }
    }
  else
    {
      /**
       * Fail on unknown methods.
       */
      g_dbus_method_invocation_return_dbus_error (
          invocation, invalid_method_error, "This method is not valid");
    }
}

/**
 * Property getter for the playerctld interfaces
 */
static GVariant *
playerctld_get_property_func (GDBusConnection *connection, const gchar *sender,
                              const gchar *object_path,
                              const gchar *interface_name,
                              const gchar *property_name, GError **error,
                              gpointer user_data)
{
  struct PlayerctldContext *ctx = user_data;
  warn_if_legacy_interface (interface_name, sender);
  if (g_strcmp0 (property_name, "PlayerNames") != 0)
    {
      // Fail on unknown properties.
      // FIXME: Should return a DBus error and not crash
      g_error ("unknown property: %s", property_name);
      assert (false);
    }

  return context_player_names_to_gvariant (ctx);
}

/**
 * Location of implementation of MPRIS interfaces
 */
static GDBusInterfaceVTable vtable_mpris
    = { player_method_call_proxy_callback, NULL, NULL, { 0 } };

/**
 * Location of implementation of the playerctld interfaces
 */
static GDBusInterfaceVTable vtable_playerctld = {
  playerctld_method_call_func, playerctld_get_property_func, NULL, { 0 }
};

/**
 * Register callbacks to implement the interfaces we're supposed to
 * That is to say, the four MPRIS interfaces as well as the playerctld
 * interfaces
 */
static void
on_bus_acquired (GDBusConnection *connection, const char *name,
                 gpointer user_data)
{
  GError *error = NULL;
  struct PlayerctldContext *ctx = user_data;

  g_dbus_connection_register_object (connection, MPRIS_PATH,
                                     ctx->root_interface_info, &vtable_mpris,
                                     user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }

  g_dbus_connection_register_object (connection, MPRIS_PATH,
                                     ctx->player_interface_info, &vtable_mpris,
                                     user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }

  g_dbus_connection_register_object (connection, MPRIS_PATH,
                                     ctx->playlists_interface_info,
                                     &vtable_mpris, user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }

  g_dbus_connection_register_object (connection, MPRIS_PATH,
                                     ctx->tracklist_interface_info,
                                     &vtable_mpris, user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }

  g_dbus_connection_register_object (
      connection, MPRIS_PATH, ctx->playerctld_interface_info,
      &vtable_playerctld, user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }

  g_dbus_connection_register_object (
      connection, MPRIS_PATH, ctx->playerctld_legacy_interface_info,
      &vtable_playerctld, user_data, NULL, &error);
  if (error != NULL)
    {
      g_warning ("%s", error->message);
      g_clear_error (&error);
    }
}

static void
on_name_lost (GDBusConnection *connection, const char *name,
              gpointer user_data)
{
  struct PlayerctldContext *ctx = user_data;

  if (connection == NULL)
    {
      g_printerr ("%s\n",
                  "could not acquire bus name: unknown connection error");
    }
  else
    {
      g_printerr ("%s\n",
                  "could not acquire bus name: playerctld is already running");
    }

  ctx->return_code = 1;
  g_main_loop_quit (ctx->loop);
}

static bool
well_known_name_is_managed (const char *name)
{
  return g_str_has_prefix (name, "org.mpris.MediaPlayer2.")
         && !g_str_has_prefix (name, "org.mpris.MediaPlayer2.playerctld");
}

struct GetPropertiesUserData
{
  struct PlayerctldContext *ctx;
  const char *interface_name;
  struct Player *player;
};

static void
active_player_get_properties_async_callback (GObject *source_object,
                                             GAsyncResult *res,
                                             gpointer user_data)
{
  GDBusConnection *connection = G_DBUS_CONNECTION (source_object);
  struct GetPropertiesUserData *data = user_data;
  struct PlayerctldContext *ctx = data->ctx;
  GError *error = NULL;
  GVariant *body = g_dbus_connection_call_finish (connection, res, &error);

  if (g_error_matches (error, G_IO_ERROR, G_IO_ERROR_CANCELLED))
    {
      // the player was freed meanwhile
      g_clear_error (&error);
      free (data);
      return;
    }
  struct Player *player = data->player;
  bool updated = (error == NULL);
  if (!updated)
    {
      g_warning ("could not get properties for active player: %s",
                 error->message);
      g_clear_error (&error);
    }
  else
    {
      g_debug ("got all properties response for name='%s', interface '%s'",
               player->well_known, data->interface_name);
      GVariant *body_value = g_variant_get_child_value (body, 0);
      player_update_properties (player, data->interface_name, body_value);
      g_variant_unref (body_value);
      g_variant_unref (body);
    }

  if (g_queue_find (ctx->pending_players, player) != NULL)
    {
      // wait for both mandatory requests to complete before setting the
      // player nonpending; the optional ones are asked first, so they are
      // normally in by then
      if (!player_is_usable (player))
        {
          goto out;
        }
      if (player == ctx->pending_active)
        {
          context_set_active_player (ctx, player);
          context_emit_active_player_changed (ctx, &error);
        }
      else
        {
          context_add_player (ctx, player);
        }
    }
  else if (updated && optional_index (data->interface_name) >= 0
           && player == context_get_active_player (ctx))
    {
      // a late reply of the active player is announced on its own, the
      // player keeps its place
      context_emit_optional_properties (ctx, player, &error);
    }
  if (error != NULL)
    {
      g_warning (
          "could not emit properties changed signal for active player: %s",
          error->message);
      context_remove_player (ctx, player);
      g_clear_error (&error);
    }
out:
  free (data);
}

/**
 * Ask the player for the properties of one interface
 */
static void
player_request_properties (struct PlayerctldContext *ctx,
                           struct Player *player, const char *interface_name)
{
  struct GetPropertiesUserData *data
      = calloc (1, sizeof (struct GetPropertiesUserData));
  data->interface_name = interface_name;
  data->player = player;
  data->ctx = ctx;
  g_dbus_connection_call (
      ctx->connection, player->unique, MPRIS_PATH, PROPERTIES_INTERFACE,
      "GetAll", g_variant_new ("(s)", interface_name), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, player->cancellable,
      active_player_get_properties_async_callback, data);
}

static void
name_owner_changed_signal_callback (GDBusConnection *connection,
                                    const gchar *sender_name,
                                    const gchar *object_path,
                                    const gchar *interface_name,
                                    const gchar *signal_name,
                                    GVariant *parameters, gpointer user_data)
{
  struct PlayerctldContext *ctx = user_data;
  GError *error = NULL;
  GVariant *name_variant = g_variant_get_child_value (parameters, 0);
  GVariant *new_owner_variant = g_variant_get_child_value (parameters, 2);
  const gchar *name = g_variant_get_string (name_variant, 0);
  const gchar *new_owner = g_variant_get_string (new_owner_variant, 0);

  if (!well_known_name_is_managed (name))
    {
      goto out;
    }

  g_debug ("got name owner changed signal: name='%s', owner='%s'", name,
           new_owner);

  if (strlen (new_owner) > 0)
    {
      g_debug ("player name appeared: unique=%s, well_known=%s", new_owner,
               name);
      // see if it's already managed
      struct Player *player = context_find_player (ctx, NULL, name);
      if (player != NULL)
        {
          g_debug ("player already managed, setting to active");
          player_set_unique_name (player, new_owner);
          if (player != context_get_active_player (ctx))
            {
              context_set_active_player (ctx, player);
              player_update_position_sync (player, ctx, &error);
              if (error != NULL)
                {
                  g_warning ("could not update player position: %s",
                             error->message);
                  g_clear_error (&error);
                }
              context_emit_active_player_changed (ctx, &error);
              if (error != NULL)
                {
                  g_warning ("could not emit active player change: %s",
                             error->message);
                  g_clear_error (&error);
                }
            }
          goto out;
        }

      g_debug ("setting player to pending active");
      player = player_new (new_owner, name);
      context_add_pending_player (ctx, player);
      ctx->pending_active = player;

      // the optional ones first: a player answers in order, so they are in
      // by the time the mandatory ones promote the player
      for (int i = 0; i < N_OPTIONAL; i++)
        {
          player_request_properties (ctx, player, optional_interfaces[i].name);
        }
      player_request_properties (ctx, player, PLAYER_INTERFACE);
      player_request_properties (ctx, player, ROOT_INTERFACE);
    }
  else
    {
      struct Player *player = context_find_player (ctx, NULL, name);
      if (player == NULL)
        {
          g_debug ("%s", "name not found in queue");
          goto out;
        }

      bool is_active = (player == context_get_active_player (ctx));

      g_debug ("removing name from players: unique=%s, well_known=%s",
               player->unique, player->well_known);

      context_remove_player (ctx, player);
      player_free (player);

      if (!is_active)
        {
          goto out;
        }

      struct Player *active_player = context_get_active_player (ctx);
      if (active_player != NULL)
        {
          player_update_position_sync (active_player, ctx, &error);
          if (error != NULL)
            {
              active_player->position = 0L;
              g_warning (
                  "could not update player position for player '%s': %s",
                  active_player->well_known, error->message);
              g_clear_error (&error);
            }
        }
      context_emit_active_player_changed (ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not emit player properties changed signal: %s",
                     error->message);
          g_clear_error (&error);
        }
    }

out:
  g_variant_unref (name_variant);
  g_variant_unref (new_owner_variant);
}

/**
 * Cache the properties of a PropertiesChanged signal of the player. Returns
 * TRUE if they have changed.
 */
static gboolean
player_apply_properties_changed (struct Player *player, GVariant *parameters)
{
  GVariant *interface = g_variant_get_child_value (parameters, 0);
  GVariant *properties = g_variant_get_child_value (parameters, 1);
  const gchar *name = g_variant_get_string (interface, 0);
  GVariant **cache = player_cache_for (player, name);
  if (cache != NULL && *cache == NULL)
    {
      // only the optional interfaces can be missing here; the change
      // announces them
      g_warning ("Player %s doesn't appear to support interface %s, but sent "
                 "PropertiesChanged regarding its properties.",
                 player->well_known, name);
    }
  gboolean changed = player_update_properties (player, name, properties);
  g_variant_unref (interface);
  g_variant_unref (properties);
  return changed;
}

static void
player_signal_proxy_callback (GDBusConnection *connection,
                              const gchar *sender_name,
                              const gchar *object_path,
                              const gchar *interface_name,
                              const gchar *signal_name, GVariant *parameters,
                              gpointer user_data)
{
  gboolean changed = TRUE;

  GError *error = NULL;
  struct PlayerctldContext *ctx = user_data;
  struct Player *player = context_find_player (ctx, sender_name, NULL);
  if (player == NULL)
    {
      return;
    }

  g_debug ("got player signal: sender=%s, object_path=%s, interface_name=%s, "
           "signal_name=%s",
           sender_name, object_path, interface_name, signal_name);

  if (g_strcmp0 (interface_name, PLAYER_INTERFACE) != 0
      && g_strcmp0 (interface_name, PROPERTIES_INTERFACE) != 0
      && optional_index (interface_name) < 0)
    {
      return;
    }

  if (g_queue_find (ctx->pending_players, player) != NULL)
    {
      // not usable until both property replies arrived (also covers a player
      // whose reply failed and that is no longer pending_active)
      // TODO buffer seeked signals
      return;
    }

  bool is_properties_changed
      = (g_strcmp0 (signal_name, "PropertiesChanged") == 0);

  if (is_properties_changed)
    {
      changed = player_apply_properties_changed (player, parameters);
    }

  if (changed && player != context_get_active_player (ctx))
    {
      g_debug ("new active player: %s", player->well_known);
      context_set_active_player (ctx, player);
      player_update_position_sync (player, ctx, &error);
      if (error != NULL)
        {
          player->position = 0L;
          g_warning ("could not update player position: %s", error->message);
          g_clear_error (&error);
        }
      context_emit_active_player_changed (ctx, &error);
      if (error != NULL)
        {
          g_warning ("could not emit all properties changed signal: %s",
                     error->message);
          g_clear_error (&error);
        }
    }

  g_dbus_connection_emit_signal (ctx->connection, NULL, object_path,
                                 interface_name, signal_name, parameters,
                                 &error);
  if (error != NULL)
    {
      g_debug ("could not emit signal: %s", error->message);
      g_clear_error (&error);
    }
}

static gchar **command_arg = NULL;

static const GOptionEntry entries[] = {
  { G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_STRING_ARRAY, &command_arg, NULL,
    "COMMAND" },
  { NULL },
};

static gboolean
parse_setup_options (int argc, char **argv, GError **error)
{
  static const gchar *description
      = "Available Commands:"
        "\n  daemon                  Activate playerctld and exit"
        "\n  shift                   Shift to next player"
        "\n  unshift                 Unshift to previous player";

  GOptionContext *context;
  gboolean success;

  context = g_option_context_new ("- Playerctl Daemon");
  g_option_context_add_main_entries (context, entries, NULL);
  g_option_context_set_description (context, description);

  success = g_option_context_parse (context, &argc, &argv, error);

  if (success && command_arg
      && (g_strcmp0 (command_arg[0], "shift") != 0
          && g_strcmp0 (command_arg[0], "unshift") != 0
          && g_strcmp0 (command_arg[0], "daemon") != 0))
    {
      gchar *help = g_option_context_get_help (context, TRUE, NULL);
      printf ("%s\n", help);
      g_option_context_free (context);
      g_free (help);
      exit (1);
    }

  g_option_context_free (context);
  return success;
}

static int
playercmd_call (GDBusConnection *connection, const char *method)
{
  GError *error = NULL;

  for (gsize i = 0; i < G_N_ELEMENTS (playerctld_interfaces); i++)
    {
      g_clear_error (&error);
      g_dbus_connection_call_sync (
          connection, "org.mpris.MediaPlayer2.playerctld", MPRIS_PATH,
          playerctld_interfaces[i], method, NULL, NULL,
          G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &error);
      // an older playerctld only serves the legacy interface
      if (error == NULL
          || !g_error_matches (error, G_DBUS_ERROR,
                               G_DBUS_ERROR_UNKNOWN_METHOD))
        {
          break;
        }
    }
  g_object_unref (connection);
  if (error != NULL)
    {
      g_autofree gchar *verb = g_ascii_strdown (method, -1);
      g_printerr ("Cannot %s: %s\n", verb, error->message);
      g_error_free (error);
      return 1;
    }
  return 0;
}

int
playercmd_shift (GDBusConnection *connection)
{
  return playercmd_call (connection, "Shift");
}

int
playercmd_unshift (GDBusConnection *connection)
{
  return playercmd_call (connection, "Unshift");
}

enum activation_result
{
  ACTIVATION_FAIL = 0,
  ACTIVATION_NOT_SUPPORTED,
  ACTIVATION_SUCCESS,
  ACTIVATION_ALREADY_RUNNING,
};

enum activation_result
start_playerctld_dbus_activation (GDBusConnection *connection, GError **error)
{
  GError *tmp_error = NULL;
  GVariant *child = NULL;

  GVariant *result = g_dbus_connection_call_sync (
      connection, "org.freedesktop.DBus", "/org/freedesktop/DBus",
      "org.freedesktop.DBus", "StartServiceByName",
      g_variant_new ("(su)", "org.mpris.MediaPlayer2.playerctld", 0), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &tmp_error);
  if (tmp_error != NULL)
    {
      // NOLINTBEGIN(bugprone-assignment-in-if-condition): glib macro
      if (g_str_has_prefix (
              tmp_error->message,
              "GDBus.Error:org.freedesktop.DBus.Error.ServiceUnknown"))
        {
          g_clear_error (&tmp_error);
          return ACTIVATION_NOT_SUPPORTED;
        }
      // NOLINTEND(bugprone-assignment-in-if-condition)

      g_propagate_error (error, tmp_error);
      return ACTIVATION_FAIL;
    }

  child = g_variant_get_child_value (result, 0);
  guint32 result_code = g_variant_get_uint32 (child);
  g_variant_unref (child);
  g_variant_unref (result);

  if (result_code == 1)
    {
      return ACTIVATION_SUCCESS;
    }
  if (result_code == 2)
    {
      return ACTIVATION_ALREADY_RUNNING;
    }

  g_warning ("Got unknown result from StartServiceByName: %d\n", result_code);
  return ACTIVATION_SUCCESS;
}

int
main (int argc, char *argv[])
{
  struct PlayerctldContext ctx = { 0 };
  GError *error = NULL;

  if (!parse_setup_options (argc, argv, &error))
    {
      g_printerr ("%s\n", error->message);
      g_clear_error (&error);
      exit (0);
    }

  // Setup DBus connection
  GDBusConnectionFlags connection_flags
      = G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT
        | G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION;

  ctx.bus_address
      = g_dbus_address_get_for_bus_sync (G_BUS_TYPE_SESSION, NULL, &error);
  if (error != NULL)
    {
      g_printerr ("could not get bus address: %s", error->message);
      return 1;
    }
  // ctx.connection = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &error);
  ctx.connection = g_dbus_connection_new_for_address_sync (
      ctx.bus_address, connection_flags, NULL, NULL, &error);
  if (error != NULL)
    {
      g_printerr ("could not connect to message bus: %s", error->message);
      return 1;
    }

  g_debug ("connected to dbus: %s",
           g_dbus_connection_get_unique_name (ctx.connection));

  if (command_arg && g_strcmp0 (command_arg[0], "daemon") == 0)
    {
      enum activation_result result
          = start_playerctld_dbus_activation (ctx.connection, &error);
      if (error != NULL)
        {
          g_printerr ("could not activate playerctld service: %s\n",
                      error->message);
          g_clear_error (&error);
          return 1;
        }

      switch (result)
        {
        case ACTIVATION_NOT_SUPPORTED:
          // TODO: find some other way to daemonize the process
          g_printerr ("%s\n", "org.freedesktop.DBus.Error.ServiceUnknown: "
                              "DBus service activation "
                              "of playerctld is not supported");
          return 1;
          break;
        case ACTIVATION_SUCCESS:
          g_printerr (
              "%s\n",
              "playerctld successfully started with DBus service activation");
          return 0;
          break;
        case ACTIVATION_ALREADY_RUNNING:
          g_printerr ("%s\n", "playerctld DBus service is already running");
          return 0;
          break;
        case ACTIVATION_FAIL:
          // not reached, already handled in the error condition
          return 1;
        }
    }

  if (command_arg && g_strcmp0 (command_arg[0], "shift") == 0)
    {
      return playercmd_shift (ctx.connection);
    }

  if (command_arg && g_strcmp0 (command_arg[0], "unshift") == 0)
    {
      return playercmd_unshift (ctx.connection);
    }

  GDBusNodeInfo *mpris_introspection_data = NULL;
  GDBusNodeInfo *playerctld_introspection_data = NULL;
  ctx.players = g_queue_new ();
  ctx.pending_players = g_queue_new ();
  ctx.loop = g_main_loop_new (NULL, FALSE);

  // Load introspection data and split into separate interfaces
  mpris_introspection_data
      = g_dbus_node_info_new_for_xml (mpris_introspection_xml, &error);
  if (error != NULL)
    {
      g_printerr ("%s", error->message);
      return 1;
    }
  playerctld_introspection_data
      = g_dbus_node_info_new_for_xml (playerctld_introspection_xml, &error);
  if (error != NULL)
    {
      g_printerr ("%s", error->message);
      return 1;
    }
  ctx.root_interface_info = g_dbus_node_info_lookup_interface (
      mpris_introspection_data, ROOT_INTERFACE);
  if (ctx.root_interface_info == NULL)
    {
      g_error ("Missing introspection data for MPRIS root interface");
    }
  // Is the player interface missing from the introspection data?
  ctx.player_interface_info = g_dbus_node_info_lookup_interface (
      mpris_introspection_data, PLAYER_INTERFACE);
  if (ctx.player_interface_info == NULL)
    {
      g_error ("Missing introspection data for MPRIS player interface");
    }
  ctx.playlists_interface_info = g_dbus_node_info_lookup_interface (
      mpris_introspection_data, PLAYLISTS_INTERFACE);
  if (ctx.playlists_interface_info == NULL)
    {
      g_error ("Missing introspection data for MPRIS playlists interface");
    }
  ctx.tracklist_interface_info = g_dbus_node_info_lookup_interface (
      mpris_introspection_data, TRACKLIST_INTERFACE);
  if (ctx.tracklist_interface_info == NULL)
    {
      g_error ("Missing introspection data for MPRIS tracklist interface");
    }
  ctx.playerctld_interface_info = g_dbus_node_info_lookup_interface (
      playerctld_introspection_data, PLAYERCTLD_INTERFACE);
  ctx.playerctld_legacy_interface_info = g_dbus_node_info_lookup_interface (
      playerctld_introspection_data, PLAYERCTLD_INTERFACE_LEGACY);

  // Get all names of players (names that start with "org.mpris.MediaPlayer2.")
  // then fetch their properties on all supported interfaces
  GVariant *names_reply = g_dbus_connection_call_sync (
      ctx.connection, DBUS_NAME, DBUS_PATH, DBUS_INTERFACE, "ListNames", NULL,
      NULL, G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &error);
  if (error != NULL)
    {
      g_warning ("could not call ListNames: %s", error->message);
      return 1;
    }
  GVariant *names_reply_value = g_variant_get_child_value (names_reply, 0);
  gsize nnames;
  const gchar **names = g_variant_get_strv (names_reply_value, &nnames);
  for (int i = 0; i < nnames; ++i)
    {
      if (well_known_name_is_managed (names[i]))
        {
          // org.mpris.MediaPlayer2.Player properties
          GVariant *owner_reply = g_dbus_connection_call_sync (
              ctx.connection, DBUS_NAME, DBUS_PATH, DBUS_INTERFACE,
              "GetNameOwner", g_variant_new ("(s)", names[i]), NULL,
              G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &error);
          if (error != NULL)
            {
              g_warning ("could not get owner for name %s: %s", names[i],
                         error->message);
              g_clear_error (&error);
              continue;
            }

          GVariant *owner_reply_value
              = g_variant_get_child_value (owner_reply, 0);
          struct Player *player = player_new (
              g_variant_get_string (owner_reply_value, 0), names[i]);
          g_variant_unref (owner_reply_value);
          g_variant_unref (owner_reply);

          // org.mpris.MediaPlayer2.Player and org.mpris.MediaPlayer2
          // properties are mandatory, get rid of "players" who don't support
          // them
          if (!player_fetch_properties_sync (player, &ctx, PLAYER_INTERFACE,
                                             &error)
              || !player_fetch_properties_sync (player, &ctx, ROOT_INTERFACE,
                                                &error))
            {
              g_warning ("could not get properties for player: %s",
                         player->well_known);
              player_free (player);
              g_clear_error (&error);
              continue;
            }

          // the other interfaces are optional, so we can keep the player
          // around
          for (int j = 0; j < N_OPTIONAL; j++)
            {
              if (!player_fetch_properties_sync (
                      player, &ctx, optional_interfaces[j].name, &error))
                {
                  g_warning ("could not get %s properties for player: %s",
                             optional_interfaces[j].name, player->well_known);
                  g_clear_error (&error);
                }
            }

          g_debug ("found player: %s", player->well_known);
          g_queue_push_head (ctx.players, player);
        }
    }

  g_free (names);
  g_variant_unref (names_reply_value);
  g_variant_unref (names_reply);

  g_dbus_connection_signal_subscribe (
      ctx.connection, DBUS_NAME, DBUS_INTERFACE, "NameOwnerChanged", DBUS_PATH,
      NULL, G_DBUS_SIGNAL_FLAGS_NONE, name_owner_changed_signal_callback, &ctx,
      NULL);

  g_dbus_connection_signal_subscribe (
      ctx.connection, NULL, NULL, NULL, MPRIS_PATH, NULL,
      G_DBUS_SIGNAL_FLAGS_NONE, player_signal_proxy_callback, &ctx, NULL);

  ctx.bus_id = g_bus_own_name_on_connection (
      ctx.connection, "org.mpris.MediaPlayer2.playerctld",
      G_BUS_NAME_OWNER_FLAGS_DO_NOT_QUEUE, on_bus_acquired, on_name_lost, &ctx,
      NULL);

  g_main_loop_run (ctx.loop);
  g_bus_unown_name (ctx.bus_id);
  g_main_loop_unref (ctx.loop);
  g_dbus_node_info_unref (mpris_introspection_data);
  g_dbus_node_info_unref (playerctld_introspection_data);
  g_queue_free_full (ctx.players, (GDestroyNotify)player_free);
  g_object_unref (ctx.connection);
  g_free (ctx.bus_address);

  return ctx.return_code;
}

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

#include <gio/gio.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "playerctl-common.h"
#include "playerctl-daemon-private.h"

/**
 * The optional MPRIS interfaces, with the properties invalidated for them when
 * no player is left
 */
const struct OptionalInterface optional_interfaces[N_OPTIONAL] = {
  { TRACKLIST_INTERFACE,
    (const gchar *const[]){ "Tracks", "CanEditTracks", NULL } },
  { PLAYLISTS_INTERFACE, (const gchar *const[]){ "PlaylistCount", "Orderings",
                                                 "ActivePlaylist", NULL } },
};

int
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
 * Allocate and create a new player, with the specified connection name and
 * well-known bus name
 */
struct Player *
player_new (const char *unique, const char *well_known)
{
  struct Player *player = g_new0 (struct Player, 1);
  player->unique = g_strdup (unique);
  player->well_known = g_strdup (well_known);
  player->cancellable = g_cancellable_new ();
  return player;
}

void
player_set_unique_name (struct Player *player, const char *unique)
{
  g_free (player->unique);
  player->unique = g_strdup (unique);
}

/* STYLE: the parameter of type struct Player is called "name". */
void
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
  g_free (name);
}

/**
 * Whether the replies to the initial property requests are enough to use the
 * player
 */
bool
player_is_usable (struct Player *player)
{
  return player->player_properties != NULL && player->root_properties != NULL;
}

/*
 * A GCompareFunc for g_queue_find_custom() that is a matcher, not an ordering:
 * it returns 1 for "different" and 0 for "equal or not comparable", so a NULL
 * field is a wildcard and a probe with both names NULL matches the first
 * player. Never use it to sort.
 */
gint
player_matches (gconstpointer a, gconstpointer b)
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
GVariant **
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
gboolean
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
      if (cache == &player->player_properties
          && g_strcmp0 (key, "Position") == 0)
        {
          // gets cached separately (never counts as changed)
          player_cache_position (player, prop_value);
        }
      else
        {
          GVariant *cache_value
              = g_variant_dict_lookup_value (&cached_properties, key, NULL);
          if (cache_value != NULL)
            {
              if (!g_variant_equal (cache_value, prop_value))
                {
                  g_debug ("%s: changed property '%s.%s'", player->well_known,
                           interface_name, key);
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
        }
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

void
player_update_position_sync (struct Player *player,
                             struct PlayerctldContext *ctx, GError **error)
{
  GError *tmp_error = NULL;
  g_return_if_fail (error == NULL || *error == NULL);
  g_debug ("updating position for player unique='%s', well_known='%s'",
           player->unique, player->well_known);
  /* FIXME: blocking g_dbus_connection_call_sync() with the default 25 s
     timeout runs on the daemon main loop through
     player_update_position_sync(), which signal handlers call; one hung
     player stalls every client of playerctld. The same sync calls in the
     start-up scan (player_fetch_properties_sync, GetNameOwner) run before
     the loop and only delay start-up; playercmd_call and the activation
     call are one-shot client commands. */
  GVariant *reply = g_dbus_connection_call_sync (
      ctx->connection, player->unique, MPRIS_PATH, PROPERTIES_INTERFACE, "Get",
      g_variant_new ("(ss)", PLAYER_INTERFACE, "Position"), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return;
    }
  /* FIXME: the reply is assumed to be "(v)" without a type check; another
     reply type makes g_variant_get_child_value() return NULL or warn.
     playerctl-player.c has properties_get_reply_value() for exactly this;
     share it. The same is assumed for GetAll replies in
     player_fetch_properties_sync() and the properties callbacks. */
  GVariant *position_unwrapped = g_variant_get_child_value (reply, 0);
  GVariant *position_variant = g_variant_get_variant (position_unwrapped);
  if (g_variant_is_of_type (position_variant, G_VARIANT_TYPE_INT64))
    {
      player->position = g_variant_get_int64 (position_variant);
      g_debug ("new position: %" G_GINT64_FORMAT, player->position);
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
gboolean
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

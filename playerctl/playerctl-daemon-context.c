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

GVariant *
context_player_names_to_gvariant (struct PlayerctldContext *ctx)
{
  GVariantBuilder builder;
  g_variant_builder_init (&builder, G_VARIANT_TYPE_STRING_ARRAY);
  for (GList *item = ctx->players->head; item != NULL; item = item->next)
    {
      struct Player *current = item->data;
      g_variant_builder_add_value (&builder,
                                   g_variant_new_string (current->well_known));
    }

  return g_variant_builder_end (&builder);
}

static const char *const playerctld_interfaces[] = PLAYERCTLD_INTERFACES;

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
                                                 "CanSetFullscreen",
                                                 "Fullscreen",
                                                 "HasTrackList",
                                                 "DesktopEntry",
                                                 "Identity",
                                                 NULL };

/**
 * Announce the optional interfaces of the player; one the player lacks is
 * invalidated if it was announced before (or when there is no player)
 */
gboolean
context_emit_optional_properties (struct PlayerctldContext *ctx,
                                  struct Player *player, GError **error)
{
  for (int i = 0; i < N_OPTIONAL; i++)
    {
      GVariant *properties
          = player != NULL ? player->optional_properties[i] : NULL;
      if (properties == NULL && player != NULL && !ctx->announced_optional[i])
        {
          continue;
        }
      if (!context_emit_properties_changed (
              ctx, optional_interfaces[i].name, properties,
              properties != NULL ? NULL : optional_interfaces[i].invalidated,
              error))
        {
          return FALSE;
        }
      ctx->announced_optional[i] = properties != NULL;
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
  g_debug ("sending Seeked signal with position %" G_GINT64_FORMAT,
           player->position);
  return g_dbus_connection_emit_signal (
      ctx->connection, NULL, MPRIS_PATH, PLAYER_INTERFACE, "Seeked",
      g_variant_new ("(x)", player->position), error);
}

/**
 * Emit the ActivePlayerChangeBegin or ActivePlayerChangeEnd signal on every
 * playerctld interface, stopping at the first failure
 */
static gboolean
context_emit_active_player_change_signal (struct PlayerctldContext *ctx,
                                          const char *signal_name,
                                          struct Player *player,
                                          GError **error)
{
  for (gsize i = 0; i < G_N_ELEMENTS (playerctld_interfaces); i++)
    {
      if (!g_dbus_connection_emit_signal (
              ctx->connection, NULL, MPRIS_PATH, playerctld_interfaces[i],
              signal_name,
              g_variant_new ("(s)",
                             (player != NULL ? player->well_known : "")),
              error))
        {
          return FALSE;
        }
    }
  return TRUE;
}

void
context_emit_active_player_changed (struct PlayerctldContext *ctx,
                                    GError **error)
{
  g_return_if_fail (error == NULL || *error == NULL);

  struct Player *player = g_queue_peek_head (ctx->players);

  /* XXX: If a Begin emit fails halfway the clients get no matching End. */
  if (!context_emit_active_player_change_signal (
          ctx, "ActivePlayerChangeBegin", player, error))
    {
      return;
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
  context_emit_active_player_change_signal (ctx, "ActivePlayerChangeEnd",
                                            player, error);
}

struct Player *
context_find_player (struct PlayerctldContext *ctx, const char *unique,
                     const char *well_known)
{
  const struct Player find_name = {
    .unique = (char *)unique,
    .well_known = (char *)well_known,
  };
  GList *found
      = g_queue_find_custom (ctx->players, &find_name, player_matches);
  if (found != NULL)
    {
      return (struct Player *)found->data;
    }

  found
      = g_queue_find_custom (ctx->pending_players, &find_name, player_matches);
  if (found != NULL)
    {
      return (struct Player *)found->data;
    }

  return NULL;
}

struct Player *
context_get_active_player (struct PlayerctldContext *ctx)
{
  return g_queue_peek_head (ctx->players);
}

/**
 * Take the player out of both queues
 */
static void
context_unlink_player (struct PlayerctldContext *ctx, struct Player *player)
{
  g_queue_remove (ctx->players, player);
  g_queue_remove (ctx->pending_players, player);
}

void
context_set_active_player (struct PlayerctldContext *ctx,
                           struct Player *player)
{
  context_unlink_player (ctx, player);
  g_queue_push_head (ctx->players, player);
  ctx->pending_active = NULL;
}

void
context_add_player (struct PlayerctldContext *ctx, struct Player *player)
{
  context_unlink_player (ctx, player);
  g_queue_push_tail (ctx->players, player);
}

void
context_add_pending_player (struct PlayerctldContext *ctx,
                            struct Player *player)
{
  context_unlink_player (ctx, player);
  g_queue_push_tail (ctx->pending_players, player);
}

void
context_remove_player (struct PlayerctldContext *ctx, struct Player *player)
{
  context_unlink_player (ctx, player);
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
 * Returns the active player; when it is not PREVIOUS, update its position and
 * announce it
 */
static struct Player *
context_announce_if_changed (struct PlayerctldContext *ctx,
                             struct Player *previous)
{
  GError *error = NULL;
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

/**
 * Returns the newly activated player
 */
/* XXX: DRY: name_appeared(), name_vanished() and
   player_signal_proxy_callback() repeat the same position update plus emit
   block; name_vanished() and player_signal_proxy_callback() use different
   warning texts and a position reset, so they cannot share
   context_announce_if_changed() without changing the warnings. */
struct Player *
context_shift_active_player (struct PlayerctldContext *ctx)
{
  struct Player *previous = context_get_active_player (ctx);

  if (previous == NULL)
    {
      return NULL;
    }
  context_remove_player (ctx, previous);
  context_add_player (ctx, previous);
  return context_announce_if_changed (ctx, previous);
}

struct Player *
context_unshift_active_player (struct PlayerctldContext *ctx)
{
  struct Player *previous = context_get_active_player (ctx);

  if (previous == NULL)
    {
      return NULL;
    }

  context_unrotate_queue (ctx);

  return context_announce_if_changed (ctx, previous);
}

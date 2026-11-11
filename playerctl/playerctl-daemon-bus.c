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
  /* STYLE: doc-style comments inside a function body (also in
     active_player_get_properties_async_callback()) look like gtk-doc but document nothing. */
  static const struct
  {
    const char *name;
    struct Player *(*func) (struct PlayerctldContext *ctx);
  } methods[] = {
    /**
     * playerctld.Shift
     * Move the active player to the back of the queue,
     * return the new active player
     */
    { "Shift", context_shift_active_player },
    /**
     * playerctld.Unshift
     * Set the least recently active player to active,
     * return that player. Inverse of Shift.
     */
    { "Unshift", context_unshift_active_player },
  };
  warn_if_legacy_interface (interface_name, sender);

  for (gsize i = 0; i < G_N_ELEMENTS (methods); i++)
    {
      if (strcmp (method_name, methods[i].name) != 0)
        {
          continue;
        }
      active_player = methods[i].func (ctx);
      if (active_player != NULL)
        {
          g_dbus_method_invocation_return_value (
              invocation, g_variant_new ("(s)", active_player->well_known));
        }
      else
        {
          g_debug ("no active player, returning error");
          g_autofree gchar *no_active_player_error
              = g_strdup_printf ("%s.NoActivePlayer", interface_name);
          g_dbus_method_invocation_return_dbus_error (
              invocation, no_active_player_error,
              "No player is being controlled by playerctld");
        }
      return;
    }

  /**
   * Fail on unknown methods.
   */
  g_autofree gchar *invalid_method_error
      = g_strdup_printf ("%s.InvalidMethod", interface_name);
  g_dbus_method_invocation_return_dbus_error (invocation, invalid_method_error,
                                              "This method is not valid");
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
/* XXX: If one registration fails the daemon carries on half-registered and
   still owns the bus name. */
void
on_bus_acquired (GDBusConnection *connection, const char *name,
                 gpointer user_data)
{
  GError *error = NULL;
  struct PlayerctldContext *ctx = user_data;
  const struct
  {
    GDBusInterfaceInfo *info;
    const GDBusInterfaceVTable *vtable;
  } objects[] = {
    { ctx->root_interface_info, &vtable_mpris },
    { ctx->player_interface_info, &vtable_mpris },
    { ctx->playlists_interface_info, &vtable_mpris },
    { ctx->tracklist_interface_info, &vtable_mpris },
    { ctx->playerctld_interface_info, &vtable_playerctld },
    { ctx->playerctld_legacy_interface_info, &vtable_playerctld },
  };

  for (gsize i = 0; i < G_N_ELEMENTS (objects); i++)
    {
      g_dbus_connection_register_object (connection, MPRIS_PATH,
                                         objects[i].info, objects[i].vtable,
                                         user_data, NULL, &error);
      if (error != NULL)
        {
          g_warning ("%s", error->message);
          g_clear_error (&error);
        }
    }
}

void
/* STYLE: name is unused; g_printerr ("%s\n", literal) is g_printerr
   ("literal\n"). */
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

/* STYLE: bool here and gboolean elsewhere in the file (also
   player_is_usable() and the start-up scan in main()). */
bool
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
      g_free (data);
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
          // nothing to do yet
        }
      else if (player == ctx->pending_active)
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
      /* FIXME: leak: context_remove_player() only unlinks the player;
         nothing calls player_free() on this error path, so the struct, its
         cancellable and its in-flight requests are orphaned. */
      context_remove_player (ctx, player);
      g_clear_error (&error);
    }
  g_free (data);
}

/**
 * Ask the player for the properties of one interface
 */
static void
player_request_properties (struct PlayerctldContext *ctx,
                           struct Player *player, const char *interface_name)
{
  struct GetPropertiesUserData *data
      = g_new0 (struct GetPropertiesUserData, 1);
  data->interface_name = interface_name;
  data->player = player;
  data->ctx = ctx;
  g_dbus_connection_call (
      ctx->connection, player->unique, MPRIS_PATH, PROPERTIES_INTERFACE,
      "GetAll", g_variant_new ("(s)", interface_name), NULL,
      G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, player->cancellable,
      active_player_get_properties_async_callback, data);
}

/**
 * A player owns the name: a known player becomes the active one, an unknown
 * one is queued as pending active until its properties arrive
 */
static void
name_appeared (struct PlayerctldContext *ctx, const gchar *name,
               const gchar *new_owner)
{
  GError *error = NULL;

  g_debug ("player name appeared: unique=%s, well_known=%s", new_owner, name);
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
      return;
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

/**
 * The name has no owner any more: forget the player and, when it was the
 * active one, announce the next one
 */
static void
name_vanished (struct PlayerctldContext *ctx, const gchar *name)
{
  GError *error = NULL;
  struct Player *player = context_find_player (ctx, NULL, name);
  if (player == NULL)
    {
      g_debug ("%s", "name not found in queue");
      return;
    }

  bool is_active = (player == context_get_active_player (ctx));

  g_debug ("removing name from players: unique=%s, well_known=%s",
           player->unique, player->well_known);

  context_remove_player (ctx, player);
  player_free (player);

  if (!is_active)
    {
      return;
    }

  struct Player *active_player = context_get_active_player (ctx);
  if (active_player != NULL)
    {
      player_update_position_sync (active_player, ctx, &error);
      if (error != NULL)
        {
          active_player->position = 0L;
          g_warning ("could not update player position for player '%s': %s",
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

void
name_owner_changed_signal_callback (GDBusConnection *connection,
                                    const gchar *sender_name,
                                    const gchar *object_path,
                                    const gchar *interface_name,
                                    const gchar *signal_name,
                                    GVariant *parameters, gpointer user_data)
{
  struct PlayerctldContext *ctx = user_data;
  GVariant *name_variant = g_variant_get_child_value (parameters, 0);
  GVariant *new_owner_variant = g_variant_get_child_value (parameters, 2);
  const gchar *name = g_variant_get_string (name_variant, 0);
  const gchar *new_owner = g_variant_get_string (new_owner_variant, 0);

  if (well_known_name_is_managed (name))
    {
      g_debug ("got name owner changed signal: name='%s', owner='%s'", name,
               new_owner);

      /* STYLE: strlen (x) > 0 as an emptiness test; use *x != '\0'. */
      if (strlen (new_owner) > 0)
        {
          name_appeared (ctx, name, new_owner);
        }
      else
        {
          name_vanished (ctx, name);
        }
    }

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
  /* FIXME: the child count and types of parameters are not validated; a
     malformed PropertiesChanged from a managed player makes
     g_variant_get_child_value() return NULL with GLib critical warnings and
     the update is dropped. Check the type "(sa{sv}as)" first. */
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

void
player_signal_proxy_callback (GDBusConnection *connection,
                              const gchar *sender_name,
                              const gchar *object_path,
                              const gchar *interface_name,
                              const gchar *signal_name, GVariant *parameters,
                              gpointer user_data)
{
  /* XXX: SUSPICIOUS: changed starts TRUE, so any signal other than
     PropertiesChanged (e.g. Seeked) makes the player the active one even if
     nothing changed. */
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

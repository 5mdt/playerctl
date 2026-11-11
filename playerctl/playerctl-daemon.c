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
#include "playerctl-daemon-introspection.h"
#include "playerctl-daemon-playerctld-introspection.h"
#include "playerctl-daemon-private.h"

/* playerctld_introspection_xml: the playerctld interface under its own and the
   deprecated legacy name, generated at build time from
   data/org._5mdt.playerctld.xml by playerctl/gen-introspection-header.py. */

/* mpris_introspection_xml: the MPRIS interfaces playerctld announces, generated
   at build time from data/mpris-dbus-interface.xml (the vendored MPRIS
   specification, see doc/specs/) by playerctl/gen-introspection-header.py.
   Methods that pass file descriptors are excluded in playerctl/meson.build. */

static const char *const playerctld_interfaces[] = PLAYERCTLD_INTERFACES;

/* STYLE: file-scope mutable state (command_arg) next to a context struct
   that exists to avoid it. */
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

  const gchar *command = command_arg != NULL ? command_arg[0] : NULL;
  if (success && command_arg
      && (g_strcmp0 (command, "shift") != 0
          && g_strcmp0 (command, "unshift") != 0
          && g_strcmp0 (command, "daemon") != 0))
    {
      /* XXX: KISS: the option parser prints the help and calls exit (1)
         itself; return an error to main() instead. */
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
  if (error != NULL)
    {
      g_autofree gchar *verb = g_ascii_strdown (method, -1);
      g_printerr ("Cannot %s: %s\n", verb, error->message);
      g_error_free (error);
      return 1;
    }
  return 0;
}

/* STYLE: playercmd_shift(), playercmd_unshift() and
   start_playerctld_dbus_activation() are not static and have no
   prototype (-Wmissing-prototypes); make them static. */
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

// the values of the reply of StartServiceByName
enum start_service_reply
{
  START_REPLY_SUCCESS = 1,
  START_REPLY_ALREADY_RUNNING = 2,
};

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
      if (g_error_matches (tmp_error, G_DBUS_ERROR,
                           G_DBUS_ERROR_SERVICE_UNKNOWN))
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

  /* XXX: SUSPICIOUS: an unknown code is reported as success. */
  if (result_code == START_REPLY_SUCCESS)
    {
      return ACTIVATION_SUCCESS;
    }
  if (result_code == START_REPLY_ALREADY_RUNNING)
    {
      return ACTIVATION_ALREADY_RUNNING;
    }

  /* STYLE: the g_warning() message ends with a newline and a guint32 is
     printed with %d (use %u). */
  g_warning ("Got unknown result from StartServiceByName: %d\n", result_code);
  return ACTIVATION_SUCCESS;
}

/* XXX: g_error() aborts, so a mismatch gives a core dump instead of a
   message. */
static GDBusInterfaceInfo *
lookup_interface_or_abort (GDBusNodeInfo *node_info,
                           const char *interface_name,
                           const char *missing_message)
{
  GDBusInterfaceInfo *info
      = g_dbus_node_info_lookup_interface (node_info, interface_name);
  if (info == NULL)
    {
      g_error ("%s", missing_message);
    }
  return info;
}

/**
 * Open the connection to the session bus; prints the reason and returns FALSE
 * on failure
 */
static gboolean
connect_to_bus (struct PlayerctldContext *ctx)
{
  GError *error = NULL;
  GDBusConnectionFlags connection_flags
      = G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT
        | G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION;

  ctx->bus_address
      = g_dbus_address_get_for_bus_sync (G_BUS_TYPE_SESSION, NULL, &error);
  if (error != NULL)
    {
      /* STYLE: the g_printerr messages in connect_to_bus() and
         load_introspection() have no trailing newline. */
      g_printerr ("could not get bus address: %s", error->message);
      g_clear_error (&error);
      return FALSE;
    }
  ctx->connection = g_dbus_connection_new_for_address_sync (
      ctx->bus_address, connection_flags, NULL, NULL, &error);
  if (error != NULL)
    {
      g_printerr ("could not connect to message bus: %s", error->message);
      g_clear_error (&error);
      return FALSE;
    }

  g_debug ("connected to dbus: %s",
           g_dbus_connection_get_unique_name (ctx->connection));
  return TRUE;
}

/**
 * The "daemon" command: activate playerctld through the bus; returns the exit
 * code
 */
static int
run_activation (GDBusConnection *connection)
{
  GError *error = NULL;
  enum activation_result result
      = start_playerctld_dbus_activation (connection, &error);
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
    case ACTIVATION_SUCCESS:
      g_printerr (
          "%s\n",
          "playerctld successfully started with DBus service activation");
      break;
    case ACTIVATION_ALREADY_RUNNING:
      g_printerr ("%s\n", "playerctld DBus service is already running");
      break;
    case ACTIVATION_FAIL:
      // not reached, already handled in the error condition
      return 1;
    }
  return 0;
}

/**
 * Load introspection data and split into separate interfaces; the node infos
 * are owned by the caller even on failure. Prints the reason and returns FALSE
 * on failure.
 */
static gboolean
load_introspection (struct PlayerctldContext *ctx,
                    GDBusNodeInfo **mpris_introspection_data,
                    GDBusNodeInfo **playerctld_introspection_data)
{
  GError *error = NULL;

  *mpris_introspection_data
      = g_dbus_node_info_new_for_xml (mpris_introspection_xml, &error);
  if (error != NULL)
    {
      g_printerr ("%s", error->message);
      g_clear_error (&error);
      return FALSE;
    }
  *playerctld_introspection_data
      = g_dbus_node_info_new_for_xml (playerctld_introspection_xml, &error);
  if (error != NULL)
    {
      g_printerr ("%s", error->message);
      g_clear_error (&error);
      return FALSE;
    }
  ctx->root_interface_info = lookup_interface_or_abort (
      *mpris_introspection_data, ROOT_INTERFACE,
      "Missing introspection data for MPRIS root interface");
  ctx->player_interface_info = lookup_interface_or_abort (
      *mpris_introspection_data, PLAYER_INTERFACE,
      "Missing introspection data for MPRIS player interface");
  ctx->playlists_interface_info = lookup_interface_or_abort (
      *mpris_introspection_data, PLAYLISTS_INTERFACE,
      "Missing introspection data for MPRIS playlists interface");
  ctx->tracklist_interface_info = lookup_interface_or_abort (
      *mpris_introspection_data, TRACKLIST_INTERFACE,
      "Missing introspection data for MPRIS tracklist interface");
  ctx->playerctld_interface_info = lookup_interface_or_abort (
      *playerctld_introspection_data, PLAYERCTLD_INTERFACE,
      "Missing introspection data for the playerctld interface");
  ctx->playerctld_legacy_interface_info = lookup_interface_or_abort (
      *playerctld_introspection_data, PLAYERCTLD_INTERFACE_LEGACY,
      "Missing introspection data for the legacy playerctld interface");
  return TRUE;
}

/**
 * Fetch the properties of the player that owns the (managed) well-known name
 * and queue it as the active one; a player without the mandatory properties
 * is dropped
 */
static void
scan_player (struct PlayerctldContext *ctx, const gchar *name)
{
  GError *error = NULL;

  // org.mpris.MediaPlayer2.Player properties
  GVariant *owner_reply = g_dbus_connection_call_sync (
      ctx->connection, DBUS_NAME, DBUS_PATH, DBUS_INTERFACE, "GetNameOwner",
      g_variant_new ("(s)", name), NULL, G_DBUS_CALL_FLAGS_NO_AUTO_START, -1,
      NULL, &error);
  if (error != NULL)
    {
      g_warning ("could not get owner for name %s: %s", name, error->message);
      g_clear_error (&error);
      return;
    }

  GVariant *owner_reply_value = g_variant_get_child_value (owner_reply, 0);
  struct Player *player
      = player_new (g_variant_get_string (owner_reply_value, 0), name);
  g_variant_unref (owner_reply_value);
  g_variant_unref (owner_reply);

  // org.mpris.MediaPlayer2.Player and org.mpris.MediaPlayer2
  // properties are mandatory, get rid of "players" who don't support
  // them
  if (!player_fetch_properties_sync (player, ctx, PLAYER_INTERFACE, &error)
      || !player_fetch_properties_sync (player, ctx, ROOT_INTERFACE, &error))
    {
      g_warning ("could not get properties for player: %s",
                 player->well_known);
      player_free (player);
      g_clear_error (&error);
      return;
    }

  // the other interfaces are optional, so we can keep the player
  // around
  for (int j = 0; j < N_OPTIONAL; j++)
    {
      if (!player_fetch_properties_sync (player, ctx,
                                         optional_interfaces[j].name, &error))
        {
          g_warning ("could not get %s properties for player: %s",
                     optional_interfaces[j].name, player->well_known);
          g_clear_error (&error);
        }
    }

  g_debug ("found player: %s", player->well_known);
  /* XXX: SUSPICIOUS: g_queue_push_head() puts the last listed name
     in front, so after start-up the active player is whatever
     ListNames returned last, not the most recently active one. */
  g_queue_push_head (ctx->players, player);
}

/**
 * Get all names of players (names that start with "org.mpris.MediaPlayer2.")
 * then fetch their properties on all supported interfaces. Returns FALSE
 * (after a warning) when the names cannot be listed.
 */
static gboolean
scan_players (struct PlayerctldContext *ctx)
{
  GError *error = NULL;

  /* FIXME: race: ListNames is read here but the NameOwnerChanged and player
     signal subscriptions only start after the scan, so a player appearing in
     between is never seen. Subscribe first, then list. */
  GVariant *names_reply = g_dbus_connection_call_sync (
      ctx->connection, DBUS_NAME, DBUS_PATH, DBUS_INTERFACE, "ListNames", NULL,
      NULL, G_DBUS_CALL_FLAGS_NO_AUTO_START, -1, NULL, &error);
  if (error != NULL)
    {
      g_warning ("could not call ListNames: %s", error->message);
      g_clear_error (&error);
      return FALSE;
    }
  GVariant *names_reply_value = g_variant_get_child_value (names_reply, 0);
  gsize nnames;
  const gchar **names = g_variant_get_strv (names_reply_value, &nnames);
  /* STYLE: int index against gsize nnames. */
  for (int i = 0; i < nnames; ++i)
    {
      if (well_known_name_is_managed (names[i]))
        {
          scan_player (ctx, names[i]);
        }
    }

  g_free (names);
  g_variant_unref (names_reply_value);
  g_variant_unref (names_reply);
  return TRUE;
}

/**
 * Follow the bus, own the playerctld name and run the main loop; returns the
 * exit code
 */
static int
run_daemon (struct PlayerctldContext *ctx)
{
  g_dbus_connection_signal_subscribe (
      ctx->connection, DBUS_NAME, DBUS_INTERFACE, "NameOwnerChanged",
      DBUS_PATH, NULL, G_DBUS_SIGNAL_FLAGS_NONE,
      name_owner_changed_signal_callback, ctx, NULL);

  g_dbus_connection_signal_subscribe (
      ctx->connection, NULL, NULL, NULL, MPRIS_PATH, NULL,
      G_DBUS_SIGNAL_FLAGS_NONE, player_signal_proxy_callback, ctx, NULL);

  ctx->bus_id = g_bus_own_name_on_connection (
      ctx->connection, "org.mpris.MediaPlayer2.playerctld",
      G_BUS_NAME_OWNER_FLAGS_DO_NOT_QUEUE, on_bus_acquired, on_name_lost, ctx,
      NULL);

  g_main_loop_run (ctx->loop);
  return ctx->return_code;
}

/**
 * Release what main() acquired; every part may be
 * unset
 */
static void
release_resources (struct PlayerctldContext *ctx,
                   GDBusNodeInfo *mpris_introspection_data,
                   GDBusNodeInfo *playerctld_introspection_data)
{
  if (ctx->bus_id != 0)
    {
      g_bus_unown_name (ctx->bus_id);
    }
  if (ctx->loop != NULL)
    {
      g_main_loop_unref (ctx->loop);
    }
  if (mpris_introspection_data != NULL)
    {
      g_dbus_node_info_unref (mpris_introspection_data);
    }
  if (playerctld_introspection_data != NULL)
    {
      g_dbus_node_info_unref (playerctld_introspection_data);
    }
  if (ctx->players != NULL)
    {
      g_queue_free_full (ctx->players, (GDestroyNotify)player_free);
    }
  if (ctx->pending_players != NULL)
    {
      g_queue_free_full (ctx->pending_players, (GDestroyNotify)player_free);
    }
  g_clear_object (&ctx->connection);
  g_free (ctx->bus_address);
}

int
main (int argc, char *argv[])
{
  struct PlayerctldContext ctx = { 0 };
  GError *error = NULL;
  GDBusNodeInfo *mpris_introspection_data = NULL;
  GDBusNodeInfo *playerctld_introspection_data = NULL;
  int exit_code = 0;

  if (!parse_setup_options (argc, argv, &error))
    {
      g_printerr ("%s\n", error->message);
      g_clear_error (&error);
      exit (1);
    }

  if (!connect_to_bus (&ctx))
    {
      exit_code = 1;
      goto out;
    }

  const gchar *command = command_arg != NULL ? command_arg[0] : NULL;

  if (g_strcmp0 (command, "daemon") == 0)
    {
      exit_code = run_activation (ctx.connection);
      goto out;
    }

  if (g_strcmp0 (command, "shift") == 0)
    {
      exit_code = playercmd_shift (ctx.connection);
      goto out;
    }

  if (g_strcmp0 (command, "unshift") == 0)
    {
      exit_code = playercmd_unshift (ctx.connection);
      goto out;
    }

  ctx.players = g_queue_new ();
  ctx.pending_players = g_queue_new ();
  ctx.loop = g_main_loop_new (NULL, FALSE);

  if (!load_introspection (&ctx, &mpris_introspection_data,
                           &playerctld_introspection_data)
      || !scan_players (&ctx))
    {
      exit_code = 1;
      goto out;
    }

  exit_code = run_daemon (&ctx);

out:
  g_clear_error (&error);
  release_resources (&ctx, mpris_introspection_data,
                     playerctld_introspection_data);

  return exit_code;
}

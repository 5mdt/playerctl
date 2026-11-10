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

#include <inttypes.h>
#include <limits.h>
#include <locale.h>
#include <math.h>
#include <playerctl/playerctl.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "playerctl-common.h"
#include "playerctl-formatter.h"
#include "playerctl-player-private.h"

// clang-format off
G_DEFINE_QUARK(playerctl-cli-error-quark, playerctl_cli_error);
// clang-format on

/* Interval of the position refresh while following with a position format. */
#define POSITION_TICK_MS 1000

/* XXX: SUSPICIOUS: fifteen file-scope mutable globals plus a second state
   holder (playercmd_args); every command reads "formatter" directly, so
   none can be tested in isolation. */
/* The CLI will exit with this exit status */
static gint exit_status = 0;
/* A comma separated list of players to control. */
static gchar *player_arg = NULL;
/* A comma separated list of players to ignore. */
static gchar *ignore_player_arg = NULL;
/* If true, control all available media players */
static gboolean select_all_players;
/* If true, list all available players' names and exit. */
/* STYLE: // comments appear here too (about 20 in this file); GNU style
   uses block comments. */
static gboolean list_all_players_and_exit;
/* If true, print the version and exit. */
static gboolean print_version_and_exit;
/* If true, don't print error messages related to status. */
static gboolean no_status_error_messages;
/* The commands passed on the command line, filled in via G_OPTION_REMAINING.
 */
static gchar **command_arg = NULL;
/* A format string for printing properties and metadata */
static gchar *format_string_arg = NULL;
/* The formatter for the format string argument if present */
static PlayerctlFormatter *formatter = NULL;
/* Block and follow the command */
static gboolean follow = FALSE;
/* The main loop for the follow command */
static GMainLoop *main_loop = NULL;
/* The last output printed by the cli */
static gchar *last_output = NULL;
/* The manager of all the players we connect to */
static PlayerctlPlayerManager *manager = NULL;
/* List of player names parsed from the --player arg */
static GList *player_names = NULL;
/* List of ignored player names passed from the --ignore-player arg*/
static GList *ignored_player_names = NULL;

/* forward definitions */
static void managed_players_execute_command (GError **error);

/*
 * Sometimes players may notify metadata when nothing we care about has
 * changed, so we have this to avoid printing duplicate lines in follow
 * mode. Prints a newline if output is NULL which denotes that the property has
 * been cleared. Only use this in follow mode.
 *
 * This consumes the output string.
 */
static void
cli_print_output (gchar *output)
{
  if (output == NULL && last_output == NULL)
    {
      return;
    }

  if (output == NULL)
    {
      output = g_strdup ("\n");
    }

  if (g_strcmp0 (output, last_output) == 0)
    {
      g_free (output);
      return;
    }

  printf ("%s", output);
  (void)fflush (stdout);
  g_free (last_output);
  last_output = output;
}

struct playercmd_args
{
  gchar **argv;
  gint argc;
};

/* Arguments given to the player for the follow command */
static struct playercmd_args *playercmd_args = NULL;

static struct playercmd_args *
playercmd_args_create (gchar **argv, gint argc)
{
  struct playercmd_args *user_data = g_new0 (struct playercmd_args, 1);
  user_data->argc = argc;
  user_data->argv = g_strdupv (argv);
  return user_data;
}

static void
playercmd_args_destroy (struct playercmd_args *data)
{
  if (data == NULL)
    {
      return;
    }

  g_strfreev (data->argv);
  g_free (data);
}

/* The metadata of the player, or NULL when it has none. */
static GVariant *
get_nonempty_metadata (PlayerctlPlayer *player)
{
  GVariant *metadata = NULL;
  g_object_get (player, "metadata", &metadata, NULL);
  if (metadata != NULL && g_variant_n_children (metadata) == 0)
    {
      g_variant_unref (metadata);
      return NULL;
    }
  return metadata;
}

static gchar *
get_metadata_formatted (PlayerctlPlayer *player, GError **error)
{
  GError *tmp_error = NULL;

  g_return_val_if_fail (formatter != NULL, NULL);

  GVariant *metadata = get_nonempty_metadata (player);
  if (metadata == NULL)
    {
      return NULL;
    }

  GVariantDict *context = playerctl_formatter_default_template_context (
      formatter, player, metadata);

  gchar *result
      = playerctl_formatter_expand_format (formatter, context, &tmp_error);

  g_variant_unref (metadata);
  g_variant_dict_unref (context);

  if (tmp_error)
    {
      g_propagate_error (error, tmp_error);
      return NULL;
    }

  return result;
}

typedef void (*PlayerAction) (PlayerctlPlayer *player, GError **error);

/* Runs a transport action when the given Can* property allows it. */
static gboolean
run_if_allowed (PlayerctlPlayer *player, const gchar *can_property,
                const gchar *skip_message, PlayerAction action, GError **error)
{
  GError *tmp_error = NULL;
  gchar *instance = pctl_player_get_instance (player);

  gboolean allowed = FALSE;
  g_object_get (player, can_property, &allowed, NULL);

  if (!allowed)
    {
      g_debug ("%s: %s", instance, skip_message);
      return FALSE;
    }

  action (player, &tmp_error);
  if (tmp_error)
    {
      g_propagate_error (error, tmp_error);
      return FALSE;
    }
  return TRUE;
}

static gboolean
playercmd_play (PlayerctlPlayer *player, gchar **argv, gint argc,
                gchar **output, GError **error)
{
  return run_if_allowed (player, "can-play", "can-play is false, skipping",
                         playerctl_player_play, error);
}

static gboolean
playercmd_pause (PlayerctlPlayer *player, gchar **argv, gint argc,
                 gchar **output, GError **error)
{
  return run_if_allowed (player, "can-pause", "player cannot pause",
                         playerctl_player_pause, error);
}

static gboolean
playercmd_play_pause (PlayerctlPlayer *player, gchar **argv, gint argc,
                      gchar **output, GError **error)
{
  return run_if_allowed (player, "can-play", "can-play is false, skipping",
                         playerctl_player_play_pause, error);
}

static gboolean
playercmd_stop (PlayerctlPlayer *player, gchar **argv, gint argc,
                gchar **output, GError **error)
{
  // XXX there is no CanStop property on the mpris player. CanPlay is supposed
  // to indicate whether there is a current track. If there is no current
  // track, then I assume the player cannot stop.
  return run_if_allowed (player, "can-play", "can-play is false, skipping",
                         playerctl_player_stop, error);
}

static gboolean
playercmd_next (PlayerctlPlayer *player, gchar **argv, gint argc,
                gchar **output, GError **error)
{
  return run_if_allowed (player, "can-go-next", "player cannot go next",
                         playerctl_player_next, error);
}

static gboolean
playercmd_previous (PlayerctlPlayer *player, gchar **argv, gint argc,
                    gchar **output, GError **error)
{
  return run_if_allowed (player, "can-go-previous",
                         "player cannot go previous",
                         playerctl_player_previous, error);
}

static gboolean
playercmd_open (PlayerctlPlayer *player, gchar **argv, gint argc,
                gchar **output, GError **error)
{
  const gchar *uri = argv[1];
  GError *tmp_error = NULL;
  gchar *instance = pctl_player_get_instance (player);

  gboolean can_control = FALSE;
  g_object_get (player, "can-control", &can_control, NULL);

  if (!can_control)
    {
      g_debug ("%s: player cannot control", instance);
      return FALSE;
    }

  /* XXX: SUSPICIOUS: "open" without an argument succeeds and does nothing. */
  if (argc > 1)
    {
      GFile *file = g_file_new_for_commandline_arg (uri);
      gboolean exists = g_file_query_exists (file, NULL);
      gchar *full_uri = NULL;

      if (exists)
        {
          // it's a file, so pass the absolute path of the file
          full_uri = g_file_get_uri (file);
        }
      else
        {
          // it may be some other scheme, just pass the uri directly
          full_uri = g_strdup (uri);
        }

      playerctl_player_open (player, full_uri, &tmp_error);

      g_free (full_uri);
      g_object_unref (file);

      if (tmp_error != NULL)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }
    }

  return TRUE;
}

/* Parses "N", "N+" or "N-". Rejects empty, non-finite and trailing garbage.
 * A "-" suffix negates the value; any suffix sets *relative. */
static gboolean
parse_relative_number (const gchar *text, gdouble *value, gboolean *relative)
{
  char *endptr = NULL;
  gdouble number = strtod (text, &endptr);

  if (endptr == text || !isfinite (number))
    {
      return FALSE;
    }

  *relative = FALSE;
  if (*endptr == '+' || *endptr == '-')
    {
      *relative = TRUE;
      if (*endptr == '-')
        {
          number = -number;
        }
      endptr++;
    }

  if (*endptr != '\0')
    {
      return FALSE;
    }

  *value = number;
  return TRUE;
}

/* Expands the formatter for the player into *output with a trailing
 * newline. */
static gboolean
print_formatted (PlayerctlPlayer *player, gchar **output, GError **error)
{
  GError *tmp_error = NULL;
  GVariantDict *context
      = playerctl_formatter_default_template_context (formatter, player, NULL);
  gchar *formatted
      = playerctl_formatter_expand_format (formatter, context, &tmp_error);
  g_variant_dict_unref (context);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return FALSE;
    }

  *output = g_strdup_printf ("%s\n", formatted);
  g_free (formatted);
  return TRUE;
}

/* Parses the position argument and sets or seeks the player to it. */
static gboolean
position_set (PlayerctlPlayer *player, const gchar *position, GError **error)
{
  gdouble seconds = 0;
  gboolean relative = FALSE;
  GError *tmp_error = NULL;

  if (!parse_relative_number (position, &seconds, &relative))
    {
      /* XXX: SUSPICIOUS: error code 1 is used for every CLI error (also
         in volume, shuffle, loop and get_player_command), and some
         messages end in "\n" so the caller prints an extra empty line.
         */
      g_set_error (error, playerctl_cli_error_quark (), 1,
                   "Could not parse position as a number: %s\n", position);
      return FALSE;
    }

  if (fabs (seconds) * 1000000.0 >= (gdouble)G_MAXINT64
      || (!relative && seconds < 0))
    {
      g_set_error (error, playerctl_cli_error_quark (), 1,
                   "Position out of range: %s\n", position);
      return FALSE;
    }
  gint64 offset = (gint64)(seconds * 1000000.0);

  gboolean can_seek = FALSE;
  g_object_get (player, "can-seek", &can_seek, NULL);
  if (!can_seek)
    {
      return FALSE;
    }

  if (relative)
    {
      playerctl_player_seek (player, offset, &tmp_error);
    }
  else
    {
      playerctl_player_set_position (player, offset, &tmp_error);
    }
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return FALSE;
    }
  return TRUE;
}

/* Prints the position of the player, formatted when a formatter is given. */
static gboolean
position_print (PlayerctlPlayer *player, gchar **output, GError **error)
{
  if (formatter != NULL)
    {
      return print_formatted (player, output, error);
    }

  /* XXX: SUSPICIOUS: with a formatter the cached-property check is
     skipped (here and in loop), so --format renders a player
     that has no such property; volume, status and shuffle check
     first. */
  if (!pctl_player_has_cached_property (player, "Position"))
    {
      g_debug ("%s: player has no cached position, skipping",
               pctl_player_get_instance (player));
      return FALSE;
    }
  gint64 offset = 0;
  g_object_get (player, "position", &offset, NULL);
  *output = g_strdup_printf ("%f\n", (double)offset / 1000000.0);
  return TRUE;
}

static gboolean
playercmd_position (PlayerctlPlayer *player, gchar **argv, gint argc,
                    gchar **output, GError **error)
{
  if (argc > 1)
    {
      return position_set (player, argv[1], error);
    }
  return position_print (player, output, error);
}

static gboolean
playercmd_volume (PlayerctlPlayer *player, gchar **argv, gint argc,
                  gchar **output, GError **error)
{
  GError *tmp_error = NULL;
  const gchar *volume = argv[1];
  gdouble level;
  gchar *instance = pctl_player_get_instance (player);

  if (argc > 1)
    {
      gboolean relative = FALSE;

      if (!parse_relative_number (volume, &level, &relative))
        {
          g_set_error (error, playerctl_cli_error_quark (), 1,
                       "could not parse volume as a number: %s\n", volume);
          return FALSE;
        }

      if (relative)
        {
          /* XXX: SUSPICIOUS: a relative volume reads the property without
             the cached-property check of the query branch; for a
             player without Volume the result is 0 plus the adjustment. */
          gdouble adjustment = level;
          g_object_get (player, "volume", &level, NULL);
          level += adjustment;
        }

      level = CLAMP (level, 0.0, 1.0);

      gboolean can_control = FALSE;
      g_object_get (player, "can-control", &can_control, NULL);

      if (!can_control)
        {
          g_debug ("%s: player cannot control", instance);
          return FALSE;
        }

      /* STYLE: g_debug messages end with "\n" (also in shuffle and loop). */
      g_debug ("%s: setting volume to %f\n", instance, level);
      playerctl_player_set_volume (player, level, &tmp_error);
      if (tmp_error != NULL)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }
    }
  else
    {
      if (!pctl_player_has_cached_property (player, "Volume"))
        {
          g_debug ("%s: player has no volume set, skipping", instance);
          return FALSE;
        }

      g_object_get (player, "volume", &level, NULL);

      if (formatter != NULL)
        {
          if (!print_formatted (player, output, error))
            {
              return FALSE;
            }
        }
      else
        {
          *output = g_strdup_printf ("%f\n", level);
        }
    }

  return TRUE;
}

static gboolean
playercmd_status (PlayerctlPlayer *player, gchar **argv, gint argc,
                  gchar **output, GError **error)
{
  gchar *instance = pctl_player_get_instance (player);

  if (!pctl_player_has_cached_property (player, "PlaybackStatus"))
    {
      g_debug ("%s: player has no playback status set, skipping", instance);
      return FALSE;
    }

  if (formatter != NULL)
    {
      if (!print_formatted (player, output, error))
        {
          return FALSE;
        }
    }
  else
    {
      PlayerctlPlaybackStatus status = 0;
      g_object_get (player, "playback-status", &status, NULL);
      const gchar *status_str = pctl_playback_status_to_string (status);
      if (status_str == NULL)
        {
          g_error ("assertion failed: status_str != NULL");
        }
      *output = g_strdup_printf ("%s\n", status_str);
    }

  return TRUE;
}

static gboolean
playercmd_shuffle (PlayerctlPlayer *player, gchar **argv, gint argc,
                   gchar **output, GError **error)
{
  GError *tmp_error = NULL;
  gchar *instance = pctl_player_get_instance (player);

  if (argc > 1)
    {
      gchar *status_str = argv[1];
      gboolean status = FALSE;

      if (g_ascii_strcasecmp (status_str, "on") == 0)
        {
          status = TRUE;
        }
      else if (g_ascii_strcasecmp (status_str, "off") == 0)
        {
          status = FALSE;
        }
      else if (g_ascii_strcasecmp (status_str, "toggle") == 0)
        {
          g_object_get (player, "shuffle", &status, NULL);
          status = !status;
        }
      else
        {
          g_set_error (error, playerctl_cli_error_quark (), 1,
                       "Got unknown shuffle status: '%s' (expected 'on', "
                       "'off', or 'toggle').",
                       argv[1]);
          return FALSE;
        }

      gboolean can_control = FALSE;
      g_object_get (player, "can-control", &can_control, NULL);
      if (!can_control)
        {
          g_debug ("%s: player cannot control, not setting shuffle", instance);
          return FALSE;
        }

      playerctl_player_set_shuffle (player, status, &tmp_error);
      if (tmp_error != NULL)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }
      g_debug ("%s: setting shuffle to %d\n", instance, status);
    }
  else
    {
      if (!pctl_player_has_cached_property (player, "Shuffle"))
        {
          g_debug ("%s: player has no shuffle status set, skipping", instance);
          return FALSE;
        }

      if (formatter != NULL)
        {
          if (!print_formatted (player, output, error))
            {
              return FALSE;
            }
        }
      else
        {
          gboolean status = FALSE;
          g_object_get (player, "shuffle", &status, NULL);
          *output = g_strdup (status ? "On\n" : "Off\n");
        }
    }

  return TRUE;
}

static gboolean
playercmd_loop (PlayerctlPlayer *player, gchar **argv, gint argc,
                gchar **output, GError **error)
{
  GError *tmp_error = NULL;
  gchar *instance = pctl_player_get_instance (player);

  if (argc > 1)
    {
      gchar *status_str = argv[1];
      PlayerctlLoopStatus status = 0;
      if (!pctl_parse_loop_status (status_str, &status))
        {
          g_set_error (error, playerctl_cli_error_quark (), 1,
                       "Got unknown loop status: '%s' (expected 'none', "
                       "'playlist', or 'track').",
                       argv[1]);
          return FALSE;
        }

      gboolean can_control = FALSE;
      g_object_get (player, "can-control", &can_control, NULL);
      if (!can_control)
        {
          g_debug ("%s: player cannot control", instance);
          return FALSE;
        }

      g_debug ("%s: setting loop status to %d\n", instance, status);
      playerctl_player_set_loop_status (player, status, &tmp_error);
      if (tmp_error != NULL)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }
    }
  else
    {
      if (formatter != NULL)
        {
          if (!print_formatted (player, output, error))
            {
              return FALSE;
            }
        }
      else
        {
          if (!pctl_player_has_cached_property (player, "LoopStatus"))
            {
              g_debug ("%s: player has no cached loop status, skipping",
                       instance);
              return FALSE;
            }
          PlayerctlLoopStatus status = 0;
          g_object_get (player, "loop-status", &status, NULL);
          const gchar *status_str = pctl_loop_status_to_string (status);
          if (status_str == NULL)
            {
              g_error ("assertion failed: loop status string is NULL");
            }
          *output = g_strdup_printf ("%s\n", status_str);
        }
    }

  return TRUE;
}

/* The first player with metadata answers for all the keys; a key it lacks
 * prints nothing rather than coming from another player. */
static gboolean
metadata_keys_output (PlayerctlPlayer *player, gchar **argv, gint argc,
                      gchar **output)
{
  GVariant *metadata = get_nonempty_metadata (player);
  if (metadata == NULL)
    {
      return FALSE;
    }

  const gchar *shortcuts[] = { "artist", "title", "album", NULL };
  GString *lines = g_string_new (NULL);
  for (int i = 1; i < argc; ++i)
    {
      gchar *key = g_strv_contains (shortcuts, argv[i])
                       ? g_strconcat ("xesam:", argv[i], NULL)
                       : g_strdup (argv[i]);
      GVariant *value = g_variant_lookup_value (metadata, key, NULL);
      if (value != NULL)
        {
          gchar *printed = pctl_print_gvariant (value);
          g_string_append_printf (lines, "%s\n", printed);
          g_free (printed);
          g_variant_unref (value);
        }
      g_free (key);
    }

  g_variant_unref (metadata);
  *output = g_string_free (lines, lines->len == 0);
  return TRUE;
}

static gboolean
playercmd_metadata (PlayerctlPlayer *player, gchar **argv, gint argc,
                    gchar **output, GError **error)
{
  g_debug ("metadata command for player: %s",
           pctl_player_get_instance (player));
  GError *tmp_error = NULL;
  gchar *instance = pctl_player_get_instance (player);

  gboolean can_play = FALSE;
  g_object_get (player, "can-play", &can_play, NULL);

  if (!can_play)
    {
      // XXX: This is gotten from the property cache which may not be up to
      // date in all cases. If there is a bug with a player not printing
      // metadata, look here.
      g_debug ("%s: can-play is false, skipping", instance);
      return FALSE;
    }

  if (format_string_arg != NULL)
    {
      gchar *data = get_metadata_formatted (player, &tmp_error);
      if (tmp_error)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }
      if (data != NULL)
        {
          *output = g_strdup_printf ("%s\n", data);
          g_free (data);
        }
      else
        {
          g_debug ("%s: no metadata, skipping", instance);
          return FALSE;
        }
    }
  else if (argc < 2)
    {
      gchar *data
          = playerctl_player_print_metadata_prop (player, NULL, &tmp_error);
      if (tmp_error)
        {
          g_propagate_error (error, tmp_error);
          return FALSE;
        }

      if (data != NULL)
        {
          *output = g_strdup_printf ("%s\n", data);
          g_free (data);
        }
      else
        {
          return FALSE;
        }
    }
  else
    {
      return metadata_keys_output (player, argv, argc, output);
    }

  return TRUE;
}

/* Report an error that happened while following, clear it and stop the main
 * loop with exit status 1. */
static void
follow_fail (const gchar *prefix, GError **error)
{
  exit_status = 1;
  g_printerr ("%s: %s\n", prefix, (*error)->message);
  g_clear_error (error);
  g_main_loop_quit (main_loop);
}

static void
managed_player_properties_changed (PlayerctlPlayer *player)
{
  playerctl_player_manager_move_player_to_top (manager, player);
  GError *error = NULL;
  managed_players_execute_command (&error);
  if (error != NULL)
    {
      follow_fail ("Error while executing command", &error);
    }
}

/* One callback per signal signature: (player, argument, user data). */
static void
managed_player_int64_callback (PlayerctlPlayer *player, gint64 value,
                               gpointer data)
{
  managed_player_properties_changed (player);
}

static void
managed_player_double_callback (PlayerctlPlayer *player, gdouble value,
                                gpointer data)
{
  managed_player_properties_changed (player);
}

static void
managed_player_enum_callback (PlayerctlPlayer *player, gint value,
                              gpointer data)
{
  managed_player_properties_changed (player);
}

static void
managed_player_boolean_callback (PlayerctlPlayer *player, gboolean value,
                                 gpointer data)
{
  managed_player_properties_changed (player);
}

static void
managed_player_variant_callback (PlayerctlPlayer *player, GVariant *value,
                                 gpointer data)
{
  managed_player_properties_changed (player);
}

static GCallback
managed_player_callback_for_signal (const gchar *signal_name)
{
  if (g_strcmp0 (signal_name, "seeked") == 0)
    {
      return G_CALLBACK (managed_player_int64_callback);
    }
  if (g_strcmp0 (signal_name, "volume") == 0)
    {
      return G_CALLBACK (managed_player_double_callback);
    }
  if (g_strcmp0 (signal_name, "playback-status") == 0
      || g_strcmp0 (signal_name, "loop-status") == 0)
    {
      return G_CALLBACK (managed_player_enum_callback);
    }
  if (g_strcmp0 (signal_name, "shuffle") == 0)
    {
      return G_CALLBACK (managed_player_boolean_callback);
    }
  /* "metadata" */
  return G_CALLBACK (managed_player_variant_callback);
}

static gboolean
playercmd_tick_callback (gpointer data)
{
  GError *tmp_error = NULL;
  managed_players_execute_command (&tmp_error);
  if (tmp_error != NULL)
    {
      follow_fail ("Error while executing command", &tmp_error);
      return FALSE;
    }
  return TRUE;
}

/* STYLE: global array with external linkage defined together with its
   struct type; make it static const. The six positional TRUE/FALSE
   initialisers are unreadable; use designated initialisers. */
struct player_command
{
  const gchar *name;
  gboolean (*func) (PlayerctlPlayer *player, gchar **argv, gint argc,
                    gchar **output, GError **error);
  const gchar *follow_signal;
  gboolean supports_format;
  // the command only reads a Can* property and calls a method, so the player
  // does not need to load all of its properties first (a slow player would
  // delay the command)
  gboolean lazy;
  // extra arguments set a value, which can not be formatted or followed
  gboolean setter_with_args;
} player_commands[] = {
  { "open", &playercmd_open, NULL, FALSE, TRUE, FALSE },
  { "play", &playercmd_play, NULL, FALSE, TRUE, FALSE },
  { "pause", &playercmd_pause, NULL, FALSE, TRUE, FALSE },
  { "play-pause", &playercmd_play_pause, NULL, FALSE, TRUE, FALSE },
  { "stop", &playercmd_stop, NULL, FALSE, TRUE, FALSE },
  { "next", &playercmd_next, NULL, FALSE, TRUE, FALSE },
  { "previous", &playercmd_previous, NULL, FALSE, TRUE, FALSE },
  { "position", &playercmd_position, "seeked", TRUE, FALSE, TRUE },
  { "volume", &playercmd_volume, "volume", TRUE, FALSE, TRUE },
  { "status", &playercmd_status, "playback-status", TRUE, FALSE, FALSE },
  { "loop", &playercmd_loop, "loop-status", TRUE, FALSE, TRUE },
  { "shuffle", &playercmd_shuffle, "shuffle", TRUE, FALSE, TRUE },
  { "metadata", &playercmd_metadata, "metadata", TRUE, FALSE, FALSE },
};

static const struct player_command *
get_player_command (gchar **argv, gint argc, GError **error)
{
  if (argv == NULL || argc < 1)
    {
      g_set_error (error, playerctl_cli_error_quark (), 1, "No command given");
      return NULL;
    }

  for (gsize i = 0; i < LENGTH (player_commands); ++i)
    {
      const struct player_command *command = &player_commands[i];
      if (g_strcmp0 (command->name, argv[0]) == 0)
        {
          gboolean setter = command->setter_with_args && argc > 1;

          if (format_string_arg != NULL
              && (!command->supports_format || setter))
            {
              g_set_error (error, playerctl_cli_error_quark (), 1,
                           "format strings are not supported on command: %s",
                           argv[0]);
              return NULL;
            }

          if (follow && (command->follow_signal == NULL || setter))
            {
              g_set_error (error, playerctl_cli_error_quark (), 1,
                           "follow is not supported on command: %s", argv[0]);
              return NULL;
            }

          return &player_commands[i];
        }
    }

  g_set_error (error, playerctl_cli_error_quark (), 1,
               "Command not recognized: %s", argv[0]);

  return NULL;
}

static const GOptionEntry entries[] = {
  { "player", 'p', G_OPTION_FLAG_NONE, G_OPTION_ARG_STRING, &player_arg,
    "A comma separated list of names of players to control (default: the "
    "first available player)",
    "NAME" },
  { "all-players", 'a', G_OPTION_FLAG_NONE, G_OPTION_ARG_NONE,
    &select_all_players, "Select all available players to be controlled",
    NULL },
  { "ignore-player", 'i', G_OPTION_FLAG_NONE, G_OPTION_ARG_STRING,
    &ignore_player_arg,
    "A comma separated list of names of players to ignore.", "IGNORE" },
  { "format", 'f', G_OPTION_FLAG_NONE, G_OPTION_ARG_STRING, &format_string_arg,
    "A format string for printing properties and metadata", NULL },
  { "follow", 'F', G_OPTION_FLAG_NONE, G_OPTION_ARG_NONE, &follow,
    "Block and append the query to output when it changes for the most "
    "recently updated player.",
    NULL },
  { "list-all", 'l', G_OPTION_FLAG_NONE, G_OPTION_ARG_NONE,
    &list_all_players_and_exit,
    "List the names of running players that can be controlled", NULL },
  { "no-messages", 's', G_OPTION_FLAG_NONE, G_OPTION_ARG_NONE,
    &no_status_error_messages, "Suppress diagnostic messages", NULL },
  { "version", 'v', G_OPTION_FLAG_NONE, G_OPTION_ARG_NONE,
    &print_version_and_exit, "Print version information", NULL },
  { G_OPTION_REMAINING, 0, 0, G_OPTION_ARG_STRING_ARRAY, &command_arg, NULL,
    "COMMAND" },
  { NULL }
};

static gboolean
parse_setup_options (int argc, char *argv[], GError **error)
{
  /* XXX: DRY: the command help text exists here, in doc/playerctl.1.in and
     in doc/usage.md. Odd literal splits ("previous " "track") show it was
     re-wrapped by hand. */
  static const gchar *description
      = "Available Commands:"
        "\n  play                    Command the player to play"
        "\n  pause                   Command the player to pause"
        "\n  play-pause              Command the player to toggle between "
        "play/pause"
        "\n  stop                    Command the player to stop"
        "\n  next                    Command the player to skip to the next "
        "track"
        "\n  previous                Command the player to skip to the "
        "previous "
        "track"
        "\n  position [OFFSET][+/-]  Command the player to go to the position "
        "or "
        "seek forward/backward OFFSET in seconds"
        "\n  volume [LEVEL][+/-]     Print or set the volume to LEVEL from "
        "0.0 "
        "to 1.0"
        "\n  status                  Get the play status of the player"
        "\n  metadata [KEY...]       Print metadata information for the "
        "current "
        "track. If KEY is passed,"
        "\n                          print only those values. KEY may be "
        "artist,"
        "title, album, or any key found in the metadata."
        "\n  open [URI]              Command for the player to open given URI."
        "\n                          URI can be either file path or remote "
        "URL."
        "\n  loop [STATUS]           Print or set the loop status."
        "\n                          Can be \"None\", \"Track\", or "
        "\"Playlist\"."
        "\n  shuffle [STATUS]        Print or set the shuffle status."
        "\n                          Can be \"On\", \"Off\", or \"Toggle\".";

  static const gchar *summary
      = "  For players supporting the MPRIS D-Bus specification";
  GOptionContext *context = NULL;
  gboolean success;

  context = g_option_context_new ("- Controller for media players");
  g_option_context_add_main_entries (context, entries, NULL);
  g_option_context_set_description (context, description);
  g_option_context_set_summary (context, summary);

  success = g_option_context_parse (context, &argc, &argv, error);

  if (!success)
    {
      g_option_context_free (context);
      return FALSE;
    }

  if (command_arg == NULL && !print_version_and_exit
      && !list_all_players_and_exit)
    {
      gchar *help = g_option_context_get_help (context, TRUE, NULL);
      printf ("%s\n", help);
      g_option_context_free (context);
      g_free (help);
      /* XXX: KISS: the parser prints the help and calls exit (1) itself;
         main() exits in six more places without cleanup while
         others go through "end". */
      exit (1);
    }

  g_option_context_free (context);
  return TRUE;
}

static GList *
parse_player_list (gchar *player_list_arg)
{
  GList *players = NULL;
  if (player_list_arg == NULL)
    {
      return NULL;
    }

  /* Empty tokens are skipped (as strtok() did), whitespace is trimmed. */
  gchar **tokens = g_strsplit (player_list_arg, ",", -1);
  for (gchar **token = tokens; *token != NULL; ++token)
    {
      if (**token != '\0')
        {
          players = g_list_append (players, g_strdup (g_strstrip (*token)));
        }
    }
  g_strfreev (tokens);

  return players;
}

static gboolean
name_in_list (GList *names, const gchar *name)
{
  return g_list_find_custom (
             names, name,
             (GCompareFunc)pctl_player_name_string_instance_compare)
         != NULL;
}

static gboolean
name_is_selected (const gchar *name)
{
  if (ignored_player_names != NULL
      && name_in_list (ignored_player_names, name))
    {
      return FALSE;
    }

  if (player_names != NULL && !name_in_list (player_names, name))
    {
      return FALSE;
    }

  return TRUE;
}

static int
handle_version_flag (void)
{
  g_print ("v%s\n", PLAYERCTL_VERSION_S);
  return 0;
}

static int
handle_list_all_flag (void)
{
  GError *tmp_error = NULL;
  GList *player_names_list = playerctl_list_players (&tmp_error);

  if (tmp_error != NULL)
    {
      g_printerr ("%s\n", tmp_error->message);
      g_error_free (tmp_error);
      return 1;
    }

  player_names_list = g_list_sort_with_data (
      player_names_list, player_name_compare_func, (gpointer)player_names);

  gboolean one_selected = FALSE;
  GList *l = NULL;
  for (l = player_names_list; l != NULL; l = l->next)
    {
      PlayerctlPlayerName *name = l->data;
      if (name_is_selected (name->instance))
        {
          one_selected = TRUE;
          /* STYLE: printf here, g_print elsewhere; pick one. */
          printf ("%s\n", name->instance);
        }
    }

  if (!one_selected && !no_status_error_messages)
    {
      g_printerr ("No players found\n");
    }

  pctl_player_name_list_destroy (player_names_list);
  return 0;
}

static void
managed_players_execute_command (GError **error)
{
  GError *tmp_error = NULL;

  const struct player_command *player_cmd = get_player_command (
      playercmd_args->argv, playercmd_args->argc, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return;
    }
  g_debug ("executing command: %s", player_cmd->name);

  gboolean did_command = FALSE;
  GList *players = NULL;
  g_object_get (manager, "players", &players, NULL);
  GList *l = NULL;
  for (l = players; l != NULL; l = l->next)
    {
      PlayerctlPlayer *player = PLAYERCTL_PLAYER (l->data);
      gchar *output = NULL;

      gboolean result
          = player_cmd->func (player, playercmd_args->argv,
                              playercmd_args->argc, &output, &tmp_error);
      if (tmp_error != NULL)
        {
          g_propagate_error (error, tmp_error);
          g_free (output);
          return;
        }

      if (output != NULL)
        {
          cli_print_output (output);
        }
      did_command = did_command || result;

      if (result)
        {
          break;
        }
    }

  if (!did_command)
    {
      cli_print_output (NULL);
    }
}

static void
/* STYLE: the parameter "manager" shadows the file-scope variable of the
   same name (also in other callbacks). */
name_appeared_callback (PlayerctlPlayerManager *manager,
                        PlayerctlPlayerName *name, gpointer *data)
{
  if (!name_is_selected (name->instance))
    {
      return;
    }

  g_debug ("a selected name appeared: %s (source=%d)", name->instance,
           name->source);

  // make sure we are not managing the player already
  GList *players = NULL;
  g_object_get (manager, "players", &players, NULL);
  for (GList *l = players; l != NULL; l = l->next)
    {
      PlayerctlPlayer *player = PLAYERCTL_PLAYER (l->data);
      gchar *instance = pctl_player_get_instance (player);
      PlayerctlSource source = 0;
      g_object_get (player, "source", &source, NULL);

      if (source == name->source && g_strcmp0 (instance, name->instance) == 0)
        {
          g_debug ("this player is already managed: %s (source=%d)",
                   name->instance, name->source);
          return;
        }
    }

  GError *error = NULL;
  PlayerctlPlayer *player = playerctl_player_new_from_name (name, &error);
  if (error != NULL)
    {
      follow_fail ("Could not connect to player", &error);
      return;
    }

  playerctl_player_manager_manage_player (manager, player);
  g_object_unref (player);
}

static void
init_managed_player (PlayerctlPlayer *player,
                     const struct player_command *player_cmd)
{
  g_signal_connect (
      G_OBJECT (player), player_cmd->follow_signal,
      managed_player_callback_for_signal (player_cmd->follow_signal),
      playercmd_args);

  if (formatter != NULL)
    {
      for (gsize i = 0; i < LENGTH (player_commands); ++i)
        {
          const struct player_command *cmd = &player_commands[i];
          if (cmd != player_cmd && cmd->follow_signal != NULL
              && g_strcmp0 (cmd->name, "metadata") != 0
              && playerctl_formatter_contains_key (formatter, cmd->name))
            {
              g_signal_connect (
                  G_OBJECT (player), cmd->follow_signal,
                  managed_player_callback_for_signal (cmd->follow_signal),
                  playercmd_args);
            }
        }
    }
}

static void
player_appeared_callback (PlayerctlPlayerManager *manager,
                          PlayerctlPlayer *player, gpointer *data)
{
  GError *error = NULL;
  const struct player_command *player_cmd = get_player_command (
      playercmd_args->argv, playercmd_args->argc, &error);
  if (error != NULL)
    {
      follow_fail ("Could not get player command", &error);
      return;
    }

  init_managed_player (player, player_cmd);

  managed_players_execute_command (&error);
  if (error != NULL)
    {
      follow_fail ("Could not execute command", &error);
    }
}

static void
player_vanished_callback (PlayerctlPlayerManager *manager,
                          PlayerctlPlayer *player, gpointer *data)
{
  GError *error = NULL;

  managed_players_execute_command (&error);
  if (error != NULL)
    {
      follow_fail ("Could not execute command", &error);
    }
}

/* Put the managed players in the order of NAMES (a list of
 * PlayerctlPlayerName, the most active first). Players that are not managed
 * are skipped; managed players that are not in NAMES stay behind the others.
 * A sort function of the manager (-p) still takes precedence. */
static void
follow_order_players (const GList *names)
{
  for (const GList *n = g_list_last ((GList *)names); n != NULL; n = n->prev)
    {
      GList *players = NULL;
      g_object_get (manager, "players", &players, NULL);
      for (GList *l = players; l != NULL; l = l->next)
        {
          PlayerctlPlayer *player = PLAYERCTL_PLAYER (l->data);
          PlayerctlPlayerName managed
              = { .instance = pctl_player_get_instance (player) };
          g_object_get (player, "source", &managed.source, NULL);
          if (pctl_player_name_compare (&managed, n->data) == 0)
            {
              playerctl_player_manager_move_player_to_top (manager, player);
              break;
            }
        }
    }
}

static GDBusConnection *playerctld_connection = NULL;
static guint playerctld_subscription = 0;

/* playerctld announces the player that the next command would control with a
 * PropertiesChanged of PlayerNames (e.g. after `playerctld shift`). */
static void
playerctld_names_changed_callback (GDBusConnection *connection,
                                   const gchar *sender_name,
                                   const gchar *object_path,
                                   const gchar *interface_name,
                                   const gchar *signal_name,
                                   GVariant *parameters, gpointer user_data)
{
  if (!g_variant_is_of_type (parameters, G_VARIANT_TYPE ("(sa{sv}as)")))
    {
      return;
    }

  GVariant *changed = g_variant_get_child_value (parameters, 1);
  GVariant *value = g_variant_lookup_value (changed, "PlayerNames",
                                            G_VARIANT_TYPE_STRING_ARRAY);
  g_variant_unref (changed);
  if (value == NULL)
    {
      return;
    }

  gsize count = 0;
  const gchar **strv = g_variant_get_strv (value, &count);
  GList *names = NULL;
  for (gsize i = 0; i < count; i++)
    {
      // NOLINTNEXTLINE(bugprone-assignment-in-if-condition): g_str_has_prefix macro
      if (g_str_has_prefix (strv[i], MPRIS_PREFIX))
        {
          names = g_list_append (
              names, pctl_player_name_new (strv[i] + strlen (MPRIS_PREFIX),
                                           PLAYERCTL_SOURCE_DBUS_SESSION));
        }
    }
  g_free (strv);
  g_variant_unref (value);

  follow_order_players (names);
  pctl_player_name_list_destroy (names);

  GError *error = NULL;
  managed_players_execute_command (&error);
  if (error != NULL)
    {
      follow_fail ("Error while executing command", &error);
    }
}

/* Rank of a player in the -p list; lower sorts first. A player not in the
 * list ranks at the first %any (last when there is none). */
static gint
player_name_rank (const GList *names, const gchar *player)
{
  gint rank = INT_MAX;
  gint any_rank = INT_MAX;
  gint i = 0;

  for (; names != NULL; names = names->next, i++)
    {
      const gchar *name = names->data;
      if (g_strcmp0 (name, "%any") == 0)
        {
          any_rank = MIN (any_rank, i);
        }
      else if (pctl_player_name_string_instance_compare (name, player) == 0)
        {
          rank = MIN (rank, i);
        }
    }

  return rank == INT_MAX ? any_rank : rank;
}

/* STYLE: these three functions (also the two that follow) have external linkage
   only so that playerctl-player-private.h can declare them for this file;
   make them static and drop the declarations. */
gint
player_name_string_compare_func (gconstpointer a, gconstpointer b,
                                 gpointer user_data)
{
  gint rank_a = player_name_rank (user_data, a);
  gint rank_b = player_name_rank (user_data, b);

  return (rank_a > rank_b) - (rank_a < rank_b);
}

gint
player_name_compare_func (gconstpointer a, gconstpointer b, gpointer user_data)
{
  const PlayerctlPlayerName *name_a = a;
  const PlayerctlPlayerName *name_b = b;
  return player_name_string_compare_func (name_a->instance, name_b->instance,
                                          user_data);
}

/* Like player_name_compare_func, but at the same rank a name listed exactly
 * (-p mpv) beats its instances, so a command picks it first. */
static gint
player_name_exact_first_compare_func (gconstpointer a, gconstpointer b,
                                      gpointer user_data)
{
  const PlayerctlPlayerName *name_a = a;
  const PlayerctlPlayerName *name_b = b;
  gint result = player_name_compare_func (a, b, user_data);
  if (result != 0)
    {
      return result;
    }

  GCompareFunc equal = (GCompareFunc)g_strcmp0;
  gboolean exact_a
      = g_list_find_custom (user_data, name_a->instance, equal) != NULL;
  gboolean exact_b
      = g_list_find_custom (user_data, name_b->instance, equal) != NULL;
  return exact_b - exact_a;
}

gint
player_compare_func (gconstpointer a, gconstpointer b, gpointer user_data)
{
  PlayerctlPlayer *player_a = PLAYERCTL_PLAYER (a);
  PlayerctlPlayer *player_b = PLAYERCTL_PLAYER (b);
  gchar *name_a = NULL;
  gchar *name_b = NULL;
  g_object_get (player_a, "player-instance", &name_a, NULL);
  g_object_get (player_b, "player-instance", &name_b, NULL);
  gint result = player_name_string_compare_func (name_a, name_b, user_data);
  g_free (name_a);
  g_free (name_b);
  return result;
}

/* Parses the command line and builds the global state. Exits on its own for
 * every failure and for --version and --list-all. */
static const struct player_command *
setup_from_command_line (int argc, char *argv[], guint *num_commands)
{
  GError *error = NULL;

  if (!parse_setup_options (argc, argv, &error))
    {
      g_printerr ("%s\n", error->message);
      g_clear_error (&error);
      exit (1);
    }

  player_names = parse_player_list (player_arg);
  ignored_player_names = parse_player_list (ignore_player_arg);

  if (print_version_and_exit)
    {
      int result = handle_version_flag ();
      exit (result);
    }

  if (list_all_players_and_exit)
    {
      int result = handle_list_all_flag ();
      exit (result);
    }

  *num_commands = g_strv_length (command_arg);

  const struct player_command *player_cmd
      = get_player_command (command_arg, *num_commands, &error);
  if (error != NULL)
    {
      g_printerr ("Could not execute command: %s\n", error->message);
      g_clear_error (&error);
      exit (1);
    }

  if (format_string_arg != NULL)
    {
      formatter = playerctl_formatter_new (format_string_arg, &error);
      if (error != NULL)
        {
          g_printerr ("Could not execute command: %s\n", error->message);
          g_clear_error (&error);
          exit (1);
        }
    }

  playercmd_args = playercmd_args_create (command_arg, *num_commands);
  return player_cmd;
}

static GList *
name_in_list_exact (GList *names, const gchar *name)
{
  return g_list_find_custom (names, name, (GCompareFunc)g_strcmp0);
}

/* playerctld is not ignored, was specified exactly in the list of players,
 * and is not in the list of available players. */
static gboolean
should_autostart_playerctld (GList *available_players)
{
  PlayerctlPlayerName playerctld_name = {
    .instance = "playerctld",
    .source = PLAYERCTL_SOURCE_DBUS_SESSION,
  };
  if (!name_is_selected ("playerctld"))
    {
      return FALSE;
    }
  if (name_in_list_exact (player_names, "playerctld") == NULL)
    {
      return FALSE;
    }
  return g_list_find_custom (available_players, &playerctld_name,
                             (GCompareFunc)pctl_player_name_compare)
         == NULL;
}

/* The player names the manager knows, sorted, with playerctld added when it
 * may autostart. The caller frees the list (not its elements) and the name
 * stored in *added_name, which the manager does not own. */
static GList *
collect_available_players (PlayerctlPlayerName **added_name)
{
  GList *available_players = NULL;

  if (player_names != NULL && !select_all_players)
    {
      playerctl_player_manager_set_sort_func (manager, player_compare_func,
                                              (gpointer)player_names, NULL);
    }

  g_object_get (manager, "player-names", &available_players, NULL);
  available_players = g_list_copy (available_players);
  available_players = g_list_sort_with_data (
      available_players, player_name_exact_first_compare_func,
      (gpointer)player_names);

  if (should_autostart_playerctld (available_players))
    {
      // Add it to the list and try to autostart it.
      g_debug ("%s", "playerctld was selected explicitly, it may autostart");
      *added_name
          = pctl_player_name_new ("playerctld", PLAYERCTL_SOURCE_DBUS_SESSION);
      available_players = g_list_append (available_players, *added_name);
      available_players = g_list_sort_with_data (
          available_players, player_name_exact_first_compare_func,
          (gpointer)player_names);
    }

  return available_players;
}

static PlayerctlPlayer *
connect_player (PlayerctlPlayerName *name,
                const struct player_command *player_cmd, GError **error)
{
  if (!follow && player_cmd->lazy)
    {
      return g_initable_new (
          PLAYERCTL_TYPE_PLAYER, NULL, error,
          /* XXX: DRY: builds the player by property name to pass load-
             properties=FALSE and so bypasses
             playerctl_player_new_from_name (); the public API
             has no constructor for it. */
          "player-instance", name->instance, "source", name->source,
          "load-properties", FALSE, NULL);
    }
  return playerctl_player_new_from_name (name, error);
}

/* Runs the command once on a player. Returns FALSE when main must stop at
 * once (error or the first player handled it). */
static gboolean
run_command_on_player (PlayerctlPlayer *player,
                       const struct player_command *player_cmd,
                       guint num_commands, gboolean *did_command)
{
  GError *error = NULL;
  gchar *output = NULL;
  g_debug ("executing command %s", player_cmd->name);
  gboolean result
      = player_cmd->func (player, command_arg, num_commands, &output, &error);
  if (error != NULL)
    {
      g_printerr ("Could not execute command: %s\n", error->message);
      g_clear_error (&error);
      exit_status = 1;
      g_object_unref (player);
      return FALSE;
    }
  if (result)
    {
      *did_command = TRUE;
      if (output != NULL)
        {
          printf ("%s", output);
          (void)fflush (stdout);
          g_free (output);
        }

      if (!select_all_players)
        {
          g_object_unref (player);
          return FALSE;
        }
    }
  return TRUE;
}

/* Connects to every selected player and runs the command on it, or starts
 * managing it when following. Returns FALSE when main must stop at once. */
static gboolean
visit_selected_players (GList *available_players,
                        const struct player_command *player_cmd,
                        guint num_commands, gboolean *has_selected,
                        gboolean *did_command)
{
  for (GList *l = available_players; l != NULL; l = l->next)
    {
      GError *error = NULL;
      PlayerctlPlayerName *name = l->data;
      g_debug ("found player: %s", name->instance);
      if (!name_is_selected (name->instance))
        {
          continue;
        }
      *has_selected = TRUE;

      PlayerctlPlayer *player = connect_player (name, player_cmd, &error);
      if (error != NULL)
        {
          g_printerr ("Could not connect to player: %s\n", error->message);
          g_clear_error (&error);
          exit_status = 1;
          return FALSE;
        }

      if (follow)
        {
          playerctl_player_manager_manage_player (manager, player);
          init_managed_player (player, player_cmd);
        }
      else if (!run_command_on_player (player, player_cmd, num_commands,
                                       did_command))
        {
          return FALSE;
        }

      g_object_unref (player);
    }
  return TRUE;
}

/* Follow the player that playerctld selects (`playerctld shift`). */
static void
follow_playerctld (void)
{
  GError *bus_error = NULL;
  playerctld_connection
      = g_bus_get_sync (G_BUS_TYPE_SESSION, NULL, &bus_error);
  if (playerctld_connection != NULL)
    {
      playerctld_subscription = g_dbus_connection_signal_subscribe (
          playerctld_connection, PLAYERCTLD_BUS_NAME,
          "org.freedesktop.DBus.Properties", "PropertiesChanged",
          "/org/mpris/MediaPlayer2", PLAYERCTLD_INTERFACE,
          G_DBUS_SIGNAL_FLAGS_NONE, playerctld_names_changed_callback, NULL,
          NULL);
    }
  else
    {
      g_debug ("not following playerctld: %s", bus_error->message);
      g_clear_error (&bus_error);
    }
}

/* Runs the main loop that follows the managed players. */
static void
follow_players (GList *available_players)
{
  GError *error = NULL;

  // managing a player puts it on top, so the first player of the
  // list would be the last one: follow the order of the list
  follow_order_players (available_players);

  managed_players_execute_command (&error);
  if (error != NULL)
    {
      g_printerr ("Connection to player failed: %s\n", error->message);
      g_clear_error (&error);
      exit_status = 1;
      return;
    }

  follow_playerctld ();

  g_signal_connect (PLAYERCTL_PLAYER_MANAGER (manager), "name-appeared",
                    G_CALLBACK (name_appeared_callback), NULL);
  g_signal_connect (PLAYERCTL_PLAYER_MANAGER (manager), "player-appeared",
                    G_CALLBACK (player_appeared_callback), NULL);
  g_signal_connect (PLAYERCTL_PLAYER_MANAGER (manager), "player-vanished",
                    G_CALLBACK (player_vanished_callback), NULL);

  if (formatter != NULL
      && playerctl_formatter_contains_key (formatter, "position"))
    {
      /* XXX: SUSPICIOUS: main_loop is only created after the handlers
         that call g_main_loop_quit (main_loop) were connected. */
      g_timeout_add (POSITION_TICK_MS, playercmd_tick_callback, NULL);
    }

  main_loop = g_main_loop_new (NULL, FALSE);
  g_main_loop_run (main_loop);
  g_main_loop_unref (main_loop);
}

/* Runs the command on the players or follows them; sets exit_status. */
static void
run_command (GList *available_players, const struct player_command *player_cmd,
             guint num_commands)
{
  gboolean has_selected = FALSE;
  gboolean did_command = FALSE;

  if (!visit_selected_players (available_players, player_cmd, num_commands,
                               &has_selected, &did_command))
    {
      return;
    }

  if (follow)
    {
      follow_players (available_players);
    }
  else if (!has_selected)
    {
      if (!no_status_error_messages)
        {
          g_printerr ("No players found\n");
        }
      exit_status = 1;
    }
  else if (!did_command)
    {
      if (!no_status_error_messages)
        {
          g_printerr ("No player could handle this command\n");
        }
      exit_status = 1;
    }
}

int
main (int argc, char *argv[])
{
  g_debug ("playerctl version %s", PLAYERCTL_VERSION_S);
  GError *error = NULL;
  guint num_commands = 0;
  GList *available_players = NULL;
  PlayerctlPlayerName *added_name = NULL;

  // seems to be required to print unicode (see #8)
  (void)setlocale (LC_CTYPE, "");

  const struct player_command *player_cmd
      = setup_from_command_line (argc, argv, &num_commands);

  manager = playerctl_player_manager_new (&error);
  if (error != NULL)
    {
      g_printerr ("Could not connect to players: %s\n", error->message);
      g_clear_error (&error);
      exit_status = 1;
    }
  else
    {
      available_players = collect_available_players (&added_name);
      run_command (available_players, player_cmd, num_commands);
    }

  if (playerctld_connection != NULL)
    {
      g_dbus_connection_signal_unsubscribe (playerctld_connection,
                                            playerctld_subscription);
      g_clear_object (&playerctld_connection);
    }
  g_list_free (available_players);
  if (added_name != NULL)
    {
      playerctl_player_name_free (added_name);
    }
  playercmd_args_destroy (playercmd_args);
  if (manager != NULL)
    {
      g_object_unref (manager);
    }
  playerctl_formatter_destroy (formatter);
  g_free (last_output);
  g_list_free_full (player_names, g_free);
  g_list_free_full (ignored_player_names, g_free);

  /* STYLE: exit (exit_status) at the end of main instead of return. */
  exit (exit_status);
}

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

#include "playerctl-common.h"

#include <glib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

static const struct
{
  const gchar *name;
  PlayerctlPlaybackStatus status;
} playback_status_names[] = {
  { "Playing", PLAYERCTL_PLAYBACK_STATUS_PLAYING },
  { "Paused", PLAYERCTL_PLAYBACK_STATUS_PAUSED },
  { "Stopped", PLAYERCTL_PLAYBACK_STATUS_STOPPED },
};

static const struct
{
  const gchar *name;
  PlayerctlLoopStatus status;
} loop_status_names[] = {
  { "None", PLAYERCTL_LOOP_STATUS_NONE },
  { "Track", PLAYERCTL_LOOP_STATUS_TRACK },
  { "Playlist", PLAYERCTL_LOOP_STATUS_PLAYLIST },
};

gboolean
pctl_parse_playback_status (const gchar *status_str,
                            PlayerctlPlaybackStatus *status)
{
  if (status_str == NULL)
    {
      return FALSE;
    }

  for (gsize i = 0; i < G_N_ELEMENTS (playback_status_names); i++)
    {
      if (strcasecmp (status_str, playback_status_names[i].name) == 0)
        {
          *status = playback_status_names[i].status;
          return TRUE;
        }
    }

  return FALSE;
}

const gchar *
pctl_playback_status_to_string (PlayerctlPlaybackStatus status)
{
  for (gsize i = 0; i < G_N_ELEMENTS (playback_status_names); i++)
    {
      if (playback_status_names[i].status == status)
        {
          return playback_status_names[i].name;
        }
    }
  return NULL;
}

const gchar *
pctl_loop_status_to_string (PlayerctlLoopStatus status)
{
  for (gsize i = 0; i < G_N_ELEMENTS (loop_status_names); i++)
    {
      if (loop_status_names[i].status == status)
        {
          return loop_status_names[i].name;
        }
    }
  return NULL;
}

gboolean
pctl_parse_loop_status (const gchar *status_str, PlayerctlLoopStatus *status)
{
  if (status_str == NULL)
    {
      return FALSE;
    }

  for (gsize i = 0; i < G_N_ELEMENTS (loop_status_names); i++)
    {
      if (strcasecmp (status_str, loop_status_names[i].name) == 0)
        {
          *status = loop_status_names[i].status;
          return TRUE;
        }
    }

  return FALSE;
}

gchar *
pctl_print_gvariant (GVariant *value)
{
  if (value == NULL)
    {
      return g_strdup ("");
    }

  GString *printed = g_string_new ("");
  if (g_variant_is_of_type (value, G_VARIANT_TYPE_STRING_ARRAY))
    {
      gsize prop_count;
      const gchar **prop_strv = g_variant_get_strv (value, &prop_count);

      for (gsize i = 0; i < prop_count; i += 1)
        {
          g_string_append (printed, prop_strv[i]);

          if (i != prop_count - 1)
            {
              g_string_append (printed, ", ");
            }
        }

      g_free (prop_strv);
    }
  else if (g_variant_is_of_type (value, G_VARIANT_TYPE_STRING)
           || g_variant_is_of_type (value, G_VARIANT_TYPE_OBJECT_PATH))
    {
      g_string_append (printed, g_variant_get_string (value, NULL));
    }
  else
    {
      printed = g_variant_print_string (value, printed, FALSE);
    }

  return g_string_free (printed, FALSE);
}

GBusType
pctl_source_to_bus_type (PlayerctlSource source)
{
  switch (source)
    {
    case PLAYERCTL_SOURCE_DBUS_SESSION:
      return G_BUS_TYPE_SESSION;
    case PLAYERCTL_SOURCE_DBUS_SYSTEM:
      return G_BUS_TYPE_SYSTEM;
    default:
      return G_BUS_TYPE_NONE;
    }
}

PlayerctlSource
pctl_bus_type_to_source (GBusType bus_type)
{
  switch (bus_type)
    {
    case G_BUS_TYPE_SESSION:
      return PLAYERCTL_SOURCE_DBUS_SESSION;
    case G_BUS_TYPE_SYSTEM:
      return PLAYERCTL_SOURCE_DBUS_SYSTEM;
    default:
      /* STYLE: g_warning() message ends with "\n" and an enum is printed
         with %d. */
      g_warning ("could not convert bus type to source: %d\n", bus_type);
      return PLAYERCTL_SOURCE_NONE;
    }
}

/* Strips a trailing ".instanceN" (N digits), the only instance suffix. */
gchar *
pctl_player_base_name (const gchar *instance)
{
  static const gchar instance_marker[] = ".instance";
  const gsize marker_len = sizeof (instance_marker) - 1;
  const gchar *suffix = g_strrstr (instance, instance_marker);
  if (suffix != NULL && suffix != instance && suffix[marker_len] != '\0'
      && suffix[marker_len + strspn (suffix + marker_len, "0123456789")]
             == '\0')
    {
      return g_strndup (instance, suffix - instance);
    }
  return g_strdup (instance);
}

PlayerctlPlayerName *
pctl_player_name_new (const gchar *instance, PlayerctlSource source)
{
  PlayerctlPlayerName *player_name = g_new (PlayerctlPlayerName, 1);
  player_name->name = pctl_player_base_name (instance);
  player_name->instance = g_strdup (instance);
  player_name->source = source;
  return player_name;
}

/* XXX: SUSPICIOUS: pctl_player_name_compare() is used as a sort comparator
   but returns 1 in both directions when the sources differ, so it is not an
   ordering. It is only correct because all names of one bus share a source. */
gint
pctl_player_name_compare (const PlayerctlPlayerName *name_a,
                          const PlayerctlPlayerName *name_b)
{
  if (name_a->source != name_b->source)
    {
      return 1;
    }
  return g_strcmp0 (name_a->instance, name_b->instance);
}

gint
pctl_player_name_instance_compare (PlayerctlPlayerName *name,
                                   PlayerctlPlayerName *instance)
{
  if (name->source != instance->source)
    {
      return 1;
    }
  return pctl_player_name_string_instance_compare (name->instance,
                                                   instance->instance);
}

gint
pctl_player_name_string_instance_compare (const gchar *name,
                                          const gchar *instance)
{
  if (g_strcmp0 (name, "%any") == 0 || g_strcmp0 (instance, "%any") == 0)
    {
      return 0;
    }

  gboolean exact_match = (g_strcmp0 (name, instance) == 0);
  gboolean instance_match
      = !exact_match
        && (g_str_has_prefix (instance, name)
            && g_str_has_prefix (instance + strlen (name), "."));

  if (exact_match || instance_match)
    {
      return 0;
    }

  return 1;
}

GList *
pctl_player_name_find (GList *list, gchar *player_id, PlayerctlSource source)
{
  PlayerctlPlayerName player_name = {
    .instance = player_id,
    .source = source,
  };

  /* STYLE: pctl_player_name_compare and
     instance_compare_item_key are cast to
     GCompareFunc; calling through a different
     function type is undefined in C. Wrap them with
     the right signature. */
  return g_list_find_custom (list, &player_name,
                             (GCompareFunc)pctl_player_name_compare);
}

/* g_list_find_custom passes (list item, search key), the reverse of the
 * (name, instance) order of pctl_player_name_instance_compare. */
static gint
instance_compare_item_key (const PlayerctlPlayerName *item,
                           const PlayerctlPlayerName *key)
{
  return pctl_player_name_instance_compare ((PlayerctlPlayerName *)key,
                                            (PlayerctlPlayerName *)item);
}

GList *
pctl_player_name_find_instance (GList *list, gchar *player_id,
                                PlayerctlSource source)
{
  PlayerctlPlayerName player_name = {
    .instance = player_id,
    .source = source,
  };

  return g_list_find_custom (list, &player_name,
                             (GCompareFunc)instance_compare_item_key);
}

void
pctl_player_name_list_destroy (GList *list)
{
  if (list == NULL)
    {
      return;
    }
  g_list_free_full (list, (GDestroyNotify)playerctl_player_name_free);
}

/* Returns the bus connection, or NULL. *err is set only for an error other
   than a missing D-Bus socket address, which is logged and passed through. */
static GDBusConnection *
get_bus_connection (GBusType bus_type, GError **err)
{
  GError *tmp_error = NULL;

  /* Plain calls on the connection: a GDBusProxy would queue a cleanup
     callback on the main context for every call. */
  GDBusConnection *connection = g_bus_get_sync (bus_type, NULL, &tmp_error);

  if (tmp_error == NULL)
    {
      return connection;
    }

  if (tmp_error->domain == G_IO_ERROR
      && tmp_error->code == G_IO_ERROR_NOT_FOUND)
    {
      // XXX: This means the dbus socket address is not found which may
      // mean that the bus is not running or the address was set
      // incorrectly. I think we can pass through here because it is true
      // that there are no names on the bus that is supposed to be at
      // this socket path. But we need a better way of dealing with this
      // case.
      const gchar *message
          = "D-Bus socket address not found, unable to list player names";
      if (bus_type == G_BUS_TYPE_SESSION)
        {
          g_warning ("%s", message);
        }
      else
        {
          g_debug ("%s", message);
        }

      g_clear_error (&tmp_error);
      return NULL;
    }
  g_propagate_error (err, tmp_error);
  return NULL;
}

/* Reads the PlayerNames property of one playerctld interface. Returns a new
   string array variant, or NULL if the property is not there. */
static GVariant *
playerctld_get_player_names_property (GDBusConnection *connection,
                                      const gchar *interface_name)
{
  GError *tmp_error = NULL;
  GVariant *property = g_dbus_connection_call_sync (
      connection, PLAYERCTLD_BUS_NAME, MPRIS_PATH,
      "org.freedesktop.DBus.Properties", "Get",
      g_variant_new ("(ss)", interface_name, "PlayerNames"),
      G_VARIANT_TYPE ("(v)"), G_DBUS_CALL_FLAGS_NONE, -1, NULL, &tmp_error);
  if (tmp_error != NULL)
    {
      g_debug ("Could not get player names from %s: %s", interface_name,
               tmp_error->message);
      g_clear_error (&tmp_error);
      return NULL;
    }
  GVariant *boxed = g_variant_get_child_value (property, 0);
  GVariant *value = g_variant_get_variant (boxed);
  g_variant_unref (boxed);
  g_variant_unref (property);
  if (g_variant_is_of_type (value, G_VARIANT_TYPE_STRING_ARRAY))
    {
      return value;
    }
  g_variant_unref (value);
  return NULL;
}

/* Asks playerctld for its player names, which are in order of activity.
   Returns a new string array variant, or NULL (after a warning). */
static GVariant *
playerctld_get_player_names (GDBusConnection *connection)
{
  g_debug ("%s", "Playerctld is running. Getting names from there.");

  GVariant *playerctld_reply = NULL;
  const gchar *interfaces[] = PLAYERCTLD_INTERFACES;
  // an older playerctld only serves the legacy interface
  for (gsize j = 0; j < G_N_ELEMENTS (interfaces) && playerctld_reply == NULL;
       j++)
    {
      playerctld_reply
          = playerctld_get_player_names_property (connection, interfaces[j]);
    }
  if (playerctld_reply == NULL)
    {
      g_warning ("%s", "Could not get player names from playerctld: "
                       "PlayerNames property not found");
    }
  return playerctld_reply;
}

/* Appends the MPRIS players of the bus names, keeping their order. */
static GList *
append_mpris_player_names (GList *players, const gchar **names, gsize count,
                           GBusType bus_type)
{
  size_t offset = strlen (MPRIS_PREFIX);
  for (gsize i = 0; i < count; i += 1)
    {
      // NOLINTNEXTLINE(bugprone-assignment-in-if-condition): glib macro
      if (g_str_has_prefix (names[i], MPRIS_PREFIX))
        {
          PlayerctlPlayerName *player_name = pctl_player_name_new (
              names[i] + offset, pctl_bus_type_to_source (bus_type));
          players = g_list_append (players, player_name);
        }
    }
  return players;
}

GList *
pctl_list_player_names_on_bus (GBusType bus_type, GError **err)
{
  GError *tmp_error = NULL;
  GList *players = NULL;
  gboolean has_playerctld = FALSE;

  GDBusConnection *connection = get_bus_connection (bus_type, err);
  if (connection == NULL)
    {
      return NULL;
    }

  g_debug ("Getting list of player names from D-Bus");
  GVariant *reply = g_dbus_connection_call_sync (
      connection, "org.freedesktop.DBus", "/org/freedesktop/DBus",
      "org.freedesktop.DBus", "ListNames", NULL, G_VARIANT_TYPE ("(as)"),
      G_DBUS_CALL_FLAGS_NONE, -1, NULL, &tmp_error);

  if (tmp_error != NULL)
    {
      g_propagate_error (err, tmp_error);
      g_object_unref (connection);
      return NULL;
    }

  GVariant *reply_child = g_variant_get_child_value (reply, 0);
  gsize reply_count;
  const gchar **names = g_variant_get_strv (reply_child, &reply_count);

  // If playerctld is in the names, get the list of players from there
  // because it will be in order of activity
  if (g_strv_contains (names, PLAYERCTLD_BUS_NAME))
    {
      GVariant *playerctld_reply = playerctld_get_player_names (connection);
      if (playerctld_reply != NULL)
        {
          g_free (names);
          g_variant_unref (reply_child);
          g_variant_unref (reply);

          reply = playerctld_reply;
          reply_child = NULL;
          names = g_variant_get_strv (reply, &reply_count);
          has_playerctld = TRUE;
        }
    }

  players = append_mpris_player_names (players, names, reply_count, bus_type);

  if (!has_playerctld)
    {
      players = g_list_sort (players, (GCompareFunc)pctl_player_name_compare);
    }

  g_object_unref (connection);
  g_variant_unref (reply);
  if (reply_child != NULL)
    {
      g_variant_unref (reply_child);
    }
  g_free (names);

  return players;
}

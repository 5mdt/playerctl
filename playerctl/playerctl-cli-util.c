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

#include "playerctl-cli.h"

#include <limits.h>
#include <math.h>
#include <playerctl/playerctl.h>
#include <stdlib.h>

#include "playerctl-common.h"

/* Parses "N", "N+" or "N-". Rejects empty, non-finite and trailing garbage.
 * A "-" suffix negates the value; any suffix sets *relative. */
gboolean
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
gint
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

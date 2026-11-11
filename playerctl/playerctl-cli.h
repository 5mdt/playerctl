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

#ifndef __PLAYERCTL_CLI_H__
#define __PLAYERCTL_CLI_H__

/* Helpers of the playerctl executable that do not depend on its global state.
   Implemented in playerctl-cli-util.c. */

#include <glib.h>

/* Parses "N", "N+" or "N-" (see playerctl-cli-util.c) */
gboolean parse_relative_number (const gchar *text, gdouble *value,
                                gboolean *relative);

/* Sort functions; user_data is the GList of the names given with -p */
gint player_name_string_compare_func (gconstpointer a, gconstpointer b,
                                      gpointer user_data);

gint player_name_compare_func (gconstpointer a, gconstpointer b,
                               gpointer user_data);

gint player_name_exact_first_compare_func (gconstpointer a, gconstpointer b,
                                           gpointer user_data);

gint player_compare_func (gconstpointer a, gconstpointer b,
                          gpointer user_data);

#endif /* __PLAYERCTL_CLI_H__ */

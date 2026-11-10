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

#ifndef __PLAYERCTL_PLAYER_INTERNAL_H__
#define __PLAYERCTL_PLAYER_INTERNAL_H__

/* Internals shared by the PlayerctlPlayer implementation files. Not
   installed. */

#include <glib.h>
#include <time.h>

#include "playerctl-common.h"
#include "playerctl-generated.h"
#include "playerctl-player.h"

#define PROPERTIES_IFACE "org.freedesktop.DBus.Properties"
#define PLAYER_IFACE PLAYER_INTERFACE
#define SET_MEMBER "Set"

struct _PlayerctlPlayerPrivate
{
  OrgMprisMediaPlayer2Player *proxy;
  gchar *player_name;
  gchar *instance;
  gchar *bus_name;
  PlayerctlSource source;
  GError *init_error;
  gboolean initted;
  gboolean load_properties;
  PlayerctlPlaybackStatus cached_status;
  gint64 cached_position;
  gchar *cached_track_id;
  struct timespec cached_position_monotonic;
};

/* playerctl-player.c */
GVariant *properties_get_reply_value (GVariant *reply);
gchar *metadata_get_track_id (GVariant *metadata);
GVariant *playerctl_player_get_metadata (PlayerctlPlayer *self, GError **err);
gboolean player_propagate_init_error (PlayerctlPlayer *self, GError **err);

GQuark playerctl_player_error_quark (void);

#endif /* __PLAYERCTL_PLAYER_INTERNAL_H__ */

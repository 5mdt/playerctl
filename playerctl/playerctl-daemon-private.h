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

#ifndef __PLAYERCTL_DAEMON_PRIVATE_H__
#define __PLAYERCTL_DAEMON_PRIVATE_H__

/* Internals shared by the playerctld implementation files (player model,
   context queue, bus handling, main). Not installed. */

#include <gio/gio.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "playerctl-common.h"

#define DBUS_NAME "org.freedesktop.DBus"
#define DBUS_INTERFACE "org.freedesktop.DBus"
#define DBUS_PATH "/org/freedesktop/DBus"
#define PROPERTIES_INTERFACE "org.freedesktop.DBus.Properties"

/* The optional MPRIS interfaces (see optional_interfaces[] in
   playerctl-daemon-player.c) */
#define N_OPTIONAL 2

struct OptionalInterface
{
  const char *name;
  const gchar *const *invalidated;
};

extern const struct OptionalInterface optional_interfaces[N_OPTIONAL];

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
  // [I] is TRUE: optional interface I was announced for the active player
  gboolean announced_optional[N_OPTIONAL];
};

/* playerctl-daemon-player.c */
int optional_index (const char *interface_name);
struct Player *player_new (const char *unique, const char *well_known);
void player_set_unique_name (struct Player *player, const char *unique);
void player_free (struct Player *name);
bool player_is_usable (struct Player *player);
gint player_matches (gconstpointer a, gconstpointer b);
GVariant **player_cache_for (struct Player *player,
                             const char *interface_name);
gboolean player_update_properties (struct Player *player,
                                   const char *interface_name,
                                   GVariant *properties);
void player_update_position_sync (struct Player *player,
                                  struct PlayerctldContext *ctx,
                                  GError **error);
gboolean player_fetch_properties_sync (struct Player *player,
                                       struct PlayerctldContext *ctx,
                                       const char *interface_name,
                                       GError **error);

/* playerctl-daemon-context.c */
GVariant *context_player_names_to_gvariant (struct PlayerctldContext *ctx);
gboolean context_emit_optional_properties (struct PlayerctldContext *ctx,
                                           struct Player *player,
                                           GError **error);
void context_emit_active_player_changed (struct PlayerctldContext *ctx,
                                         GError **error);
struct Player *context_find_player (struct PlayerctldContext *ctx,
                                    const char *unique,
                                    const char *well_known);
struct Player *context_get_active_player (struct PlayerctldContext *ctx);
void context_set_active_player (struct PlayerctldContext *ctx,
                                struct Player *player);
void context_add_player (struct PlayerctldContext *ctx, struct Player *player);
void context_add_pending_player (struct PlayerctldContext *ctx,
                                 struct Player *player);
void context_remove_player (struct PlayerctldContext *ctx,
                            struct Player *player);
struct Player *context_shift_active_player (struct PlayerctldContext *ctx);
struct Player *context_unshift_active_player (struct PlayerctldContext *ctx);

/* playerctl-daemon-bus.c */
void on_name_lost (GDBusConnection *connection, const char *name,
                   gpointer user_data);
void on_bus_acquired (GDBusConnection *connection, const char *name,
                      gpointer user_data);
bool well_known_name_is_managed (const char *name);
void name_owner_changed_signal_callback (
    GDBusConnection *connection, const gchar *sender_name,
    const gchar *object_path, const gchar *interface_name,
    const gchar *signal_name, GVariant *parameters, gpointer user_data);
void player_signal_proxy_callback (GDBusConnection *connection,
                                   const gchar *sender_name,
                                   const gchar *object_path,
                                   const gchar *interface_name,
                                   const gchar *signal_name,
                                   GVariant *parameters, gpointer user_data);

#endif /* __PLAYERCTL_DAEMON_PRIVATE_H__ */

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

#include "playerctl/playerctl-formatter.h"

#include <assert.h>
#include <glib.h>
#include <inttypes.h>
#include <playerctl/playerctl-player.h>
#include <stdio.h>

#include "playerctl/playerctl-common.h"
#include "playerctl/playerctl-formatter-private.h"

// clang-format off
G_DEFINE_QUARK(playerctl-formatter-error-quark, playerctl_formatter_error);
// clang-format on

struct _PlayerctlFormatterPrivate
{
  GList *tokens;
};

// Sets the error when the function does not take "nargs" arguments.
gboolean
check_argument_count (const struct template_function *function, int nargs,
                      GError **error)
{
  if (nargs >= function->min_args && nargs <= function->max_args)
    {
      return TRUE;
    }

  if (function->min_args == function->max_args)
    {
      static const gchar *const numbers[] = { "no", "one", "two", "three" };
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function %s takes exactly %s argument%s (got %d)",
                   function->name, numbers[function->min_args],
                   function->min_args == 1 ? "" : "s", nargs);
    }
  else
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function %s takes between %d and %d arguments (got %d)",
                   function->name, function->min_args, function->max_args,
                   nargs);
    }
  return FALSE;
}

GVariant *
expand_token (struct token *token, GVariantDict *context, GError **error)
{
  GError *tmp_error = NULL;

  switch (token->type)
    {
    case TOKEN_STRING:
      return g_variant_new ("s", token->data);

    case TOKEN_NUMBER:
      return g_variant_new ("d", token->numeric_data);

    case TOKEN_VARIABLE:
      return g_variant_dict_lookup_value (context, token->data, NULL);

    case TOKEN_FUNCTION:
      {
        // TODO lift required arg assumption
        /* XXX: SUSPICIOUS: assert on parser output; with NDEBUG a function
           token without arguments would be expanded with nargs 0. The
           tokenizer rejects "f()", so this is dead today. */
        assert (token->args != NULL);

        GVariant *ret = NULL;
        int nargs = 0;
        // the tokenizer rejects more than MAX_ARGS arguments
        GVariant *args[MAX_ARGS];

        GList *t;
        for (t = token->args; t != NULL; t = t->next)
          {
            struct token *arg_token = t->data;
            assert (nargs < MAX_ARGS);
            args[nargs++] = expand_token (arg_token, context, &tmp_error);
            if (tmp_error != NULL)
              {
                g_propagate_error (error, tmp_error);
                goto func_out;
              }
          }

        for (gsize i = 0; i < LENGTH (template_functions); ++i)
          {
            if (g_strcmp0 (template_functions[i].name, token->data) == 0)
              {
                if (!check_argument_count (&template_functions[i], nargs,
                                           error))
                  {
                    goto func_out;
                  }
                ret = template_functions[i].func (token, args, nargs,
                                                  &tmp_error);
                if (tmp_error != NULL)
                  {
                    g_propagate_error (error, tmp_error);
                  }

                goto func_out;
              }
          }
        /* XXX: SUSPICIOUS: an unknown function name (and a wrong argument
           count) is only found when the format is expanded, not when it is
           parsed, so playerctl_formatter_new() accepts "{{nosuch(x)}}" and
           every later render fails. Validate at parse time. */
        g_set_error (error, playerctl_formatter_error_quark (), 1,
                     "unknown template function: %s", token->data);
      func_out:
        for (int i = 0; i < nargs; ++i)
          {
            if (args[i] != NULL)
              {
                g_variant_unref (args[i]);
              }
          }
        return ret;
      }
    }

  assert (FALSE && "not reached");
  return NULL;
}

gchar *
expand_format (GList *tokens, GVariantDict *context, GError **error)
{
  GError *tmp_error = NULL;
  GString *expanded;

  expanded = g_string_new ("");
  GList *t;
  for (t = tokens; t != NULL; t = t->next)
    {
      GVariant *value = expand_token (t->data, context, &tmp_error);
      if (tmp_error != NULL)
        {
          g_string_free (expanded, TRUE);
          g_propagate_error (error, tmp_error);
          return NULL;
        }

      if (value != NULL)
        {
          gchar *result = pctl_print_gvariant (value);
          g_string_append (expanded, result);
          g_free (result);
          g_variant_unref (value);
        }
    }
  return g_string_free (expanded, FALSE);
}

static GVariantDict *
get_default_template_context (PlayerctlPlayer *player, GVariant *base)
{
  GVariantDict *context = g_variant_dict_new (base);
  static const gchar *const aliased_names[] = { "artist", "album", "title" };
  for (gsize i = 0; i < LENGTH (aliased_names); ++i)
    {
      gchar *xesam_key = g_strconcat ("xesam:", aliased_names[i], NULL);
      if (!g_variant_dict_contains (context, aliased_names[i])
          && g_variant_dict_contains (context, xesam_key))
        {
          GVariant *value
              = g_variant_dict_lookup_value (context, xesam_key, NULL);
          g_variant_dict_insert_value (context, aliased_names[i], value);
          g_variant_unref (value);
        }
      g_free (xesam_key);
    }
  if (!g_variant_dict_contains (context, "playerName"))
    {
      gchar *player_name = NULL;
      g_object_get (player, "player-name", &player_name, NULL);
      /* FIXME: for a player created by playerctl_player_new() or
         _new_for_source(), "player-instance" is NULL (playerctl-player.c
         initable_init never sets priv->instance), so g_variant_new_string
         (NULL) and g_variant_dict_insert_value (NULL) log GLib criticals
         and the playerInstance key is missing. status_str has the same
         shape for an out-of-range enum. */
      GVariant *player_name_variant = g_variant_new_string (player_name);
      g_variant_dict_insert_value (context, "playerName", player_name_variant);
      g_free (player_name);
    }
  if (!g_variant_dict_contains (context, "playerInstance"))
    {
      gchar *instance = NULL;
      g_object_get (player, "player-instance", &instance, NULL);
      GVariant *player_instance_variant = g_variant_new_string (instance);
      g_variant_dict_insert_value (context, "playerInstance",
                                   player_instance_variant);
      g_free (instance);
    }
  if (!g_variant_dict_contains (context, "shuffle"))
    {
      gboolean shuffle = FALSE;
      g_object_get (player, "shuffle", &shuffle, NULL);
      GVariant *shuffle_variant = g_variant_new_boolean (shuffle);
      g_variant_dict_insert_value (context, "shuffle", shuffle_variant);
    }
  if (!g_variant_dict_contains (context, "status"))
    {
      PlayerctlPlaybackStatus status = 0;
      g_object_get (player, "playback-status", &status, NULL);
      const gchar *status_str = pctl_playback_status_to_string (status);
      GVariant *status_variant = g_variant_new_string (status_str);
      g_variant_dict_insert_value (context, "status", status_variant);
    }
  if (!g_variant_dict_contains (context, "loop"))
    {
      PlayerctlLoopStatus status = 0;
      g_object_get (player, "loop-status", &status, NULL);
      const gchar *status_str = pctl_loop_status_to_string (status);
      GVariant *status_variant = g_variant_new_string (status_str);
      g_variant_dict_insert_value (context, "loop", status_variant);
    }
  if (!g_variant_dict_contains (context, "volume"))
    {
      gdouble level = 0.0;
      g_object_get (player, "volume", &level, NULL);
      GVariant *volume_variant = g_variant_new_double (level);
      g_variant_dict_insert_value (context, "volume", volume_variant);
    }
  if (!g_variant_dict_contains (context, "position"))
    {
      gint64 position = 0;
      g_object_get (player, "position", &position, NULL);
      GVariant *position_variant = g_variant_new_int64 (position);
      g_variant_dict_insert_value (context, "position", position_variant);
    }

  return context;
}

/* XXX: KISS: the formatter keeps one GList in a separately allocated
   "private" struct; the priv pointer is declared in the public header, so
   holding the list in the struct directly needs a header change. */
PlayerctlFormatter *
playerctl_formatter_new (const gchar *format, GError **error)
{
  GError *tmp_error = NULL;
  GList *tokens = tokenize_format (format, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return NULL;
    }

  PlayerctlFormatter *formatter = g_new0 (PlayerctlFormatter, 1);
  formatter->priv = g_new0 (PlayerctlFormatterPrivate, 1);
  formatter->priv->tokens = tokens;

  return formatter;
}

void
playerctl_formatter_destroy (PlayerctlFormatter *formatter)
{
  if (formatter == NULL)
    {
      return;
    }

  token_list_destroy (formatter->priv->tokens);
  g_free (formatter->priv);
  g_free (formatter);
}

gboolean
playerctl_formatter_contains_key (PlayerctlFormatter *formatter,
                                  const gchar *key)
{
  return token_list_contains_key (formatter->priv->tokens, key);
}

/* STYLE: the formatter parameter is unused. */
GVariantDict *
playerctl_formatter_default_template_context (PlayerctlFormatter *formatter,
                                              PlayerctlPlayer *player,
                                              GVariant *base)
{
  return get_default_template_context (player, base);
}

gchar *
playerctl_formatter_expand_format (PlayerctlFormatter *formatter,
                                   GVariantDict *context, GError **error)
{
  GError *tmp_error = NULL;
  gchar *expanded
      = expand_format (formatter->priv->tokens, context, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (error, tmp_error);
      return NULL;
    }

  return expanded;
}

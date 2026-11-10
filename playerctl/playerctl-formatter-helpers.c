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

#include <assert.h>
#include <glib.h>
#include <inttypes.h>
#include <playerctl/playerctl-player.h>
#include <stdio.h>

#include "playerctl/playerctl-common.h"
#include "playerctl/playerctl-formatter-private.h"

/* Volumes below these levels select the low and the medium speaker emoji. */
#define VOLUME_LOW_THRESHOLD 0.3333
#define VOLUME_MEDIUM_THRESHOLD 0.6666

/* The argument count of every template function is checked once in
   expand_token () against template_functions[]; a helper can rely on it. */

gboolean
is_valid_numeric_type (GVariant *value)
{
  // This is all the types we know about for numeric operations. May be
  // expanded at a later time. MPRIS only uses INT64 and DOUBLE as numeric
  // types. Formatter constants are always DOUBLE. All other types are for
  // player workarounds.
  if (value == NULL)
    {
      return FALSE;
    }

  return g_variant_is_of_type (value, G_VARIANT_TYPE_INT64)
         || g_variant_is_of_type (value, G_VARIANT_TYPE_UINT64)
         || g_variant_is_of_type (value, G_VARIANT_TYPE_DOUBLE);
}

gdouble
get_double_value (GVariant *value)
{
  // Keep this in sync with above is_valid_numeric_type()

  if (g_variant_is_of_type (value, G_VARIANT_TYPE_INT64))
    {
      return (gdouble)g_variant_get_int64 (value);
    }
  if (g_variant_is_of_type (value, G_VARIANT_TYPE_UINT64))
    {
      return (gdouble)g_variant_get_uint64 (value);
    }
  if (g_variant_is_of_type (value, G_VARIANT_TYPE_DOUBLE))
    {
      return g_variant_get_double (value);
    }

  assert (FALSE && "not reached");
  return 0.0;
}

/* Prints the single argument and returns it transformed by "transform". */
static GVariant *
transform_single_argument (gchar *(*transform) (const gchar *, gssize),
                           GVariant **args)
{
  GVariant *value = args[0];
  if (value == NULL)
    {
      return g_variant_new ("s", "");
    }

  gchar *printed = pctl_print_gvariant (value);
  gchar *transformed = transform (printed, -1);
  GVariant *ret = g_variant_new ("s", transformed);
  g_free (printed);
  g_free (transformed);
  return ret;
}

GVariant *
helperfn_lc (struct token *token, GVariant **args, int nargs, GError **error)
{
  return transform_single_argument (g_utf8_strdown, args);
}

GVariant *
helperfn_uc (struct token *token, GVariant **args, int nargs, GError **error)
{
  return transform_single_argument (g_utf8_strup, args);
}

/* Escapes the text for the inside of a JSON string; the quotes around it are
   left to the template. */
static gchar *
json_escape_text (const gchar *text, gssize length)
{
  GString *escaped = g_string_new ("");
  for (const gchar *c = text; *c != '\0'; ++c)
    {
      switch (*c)
        {
        case '"':
          g_string_append (escaped, "\\\"");
          break;
        case '\\':
          g_string_append (escaped, "\\\\");
          break;
        case '\b':
          g_string_append (escaped, "\\b");
          break;
        case '\f':
          g_string_append (escaped, "\\f");
          break;
        case '\n':
          g_string_append (escaped, "\\n");
          break;
        case '\r':
          g_string_append (escaped, "\\r");
          break;
        case '\t':
          g_string_append (escaped, "\\t");
          break;
        default:
          if ((guchar)*c < 0x20)
            {
              g_string_append_printf (escaped, "\\u%04x", (guchar)*c);
            }
          else
            {
              g_string_append_c (escaped, *c);
            }
        }
    }
  return g_string_free (escaped, FALSE);
}

GVariant *
helperfn_json_escape (struct token *token, GVariant **args, int nargs,
                      GError **error)
{
  return transform_single_argument (json_escape_text, args);
}

// Formats a duration in microseconds as [-][h:]mm:ss.
static GVariant *
format_duration (gint64 duration)
{
  // the magnitude as unsigned, so that G_MININT64 does not overflow
  guint64 magnitude = duration < 0 ? 0 - (guint64)duration : (guint64)duration;
  guint64 total_seconds = magnitude / 1000000;
  guint64 seconds = total_seconds % 60;
  guint64 minutes = (total_seconds / 60) % 60;
  guint64 hours = total_seconds / 60 / 60;

  GString *formatted = g_string_new (duration < 0 ? "-" : "");

  if (hours != 0)
    {
      g_string_append_printf (formatted,
                              "%" PRIu64 ":%02" PRIu64 ":%02" PRIu64, hours,
                              minutes, seconds);
    }
  else
    {
      g_string_append_printf (formatted, "%" PRIu64 ":%02" PRIu64, minutes,
                              seconds);
    }

  gchar *formatted_inner = g_string_free (formatted, FALSE);
  GVariant *ret = g_variant_new ("s", formatted_inner);
  g_free (formatted_inner);

  return ret;
}

static void
set_duration_type_error (GError **error)
{
  g_set_error (
      error, playerctl_formatter_error_quark (), 1,
      "function duration can only be called on track position values");
}

GVariant *
helperfn_duration (struct token *token, GVariant **args, int nargs,
                   GError **error)
{
  GVariant *value = args[0];
  if (value == NULL)
    {
      return g_variant_new ("s", "");
    }

  gint64 duration;

  if (g_variant_type_equal (g_variant_get_type (value), G_VARIANT_TYPE_INT64))
    {
      // mpris specifies all track position values to be int64
      duration = g_variant_get_int64 (value);
    }
  else if (g_variant_type_equal (g_variant_get_type (value),
                                 G_VARIANT_TYPE_UINT64))
    {
      // XXX: spotify may give uint64
      guint64 unsigned_duration = g_variant_get_uint64 (value);
      if (unsigned_duration > G_MAXINT64)
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "function duration got a value that is out of range");
          return NULL;
        }
      duration = unsigned_duration;
    }
  else if (g_variant_type_equal (g_variant_get_type (value),
                                 G_VARIANT_TYPE_DOUBLE))
    {
      // only if supplied by a constant or position value type goes against
      // spec
      gdouble double_duration = g_variant_get_double (value);
      // 2^63 is exactly representable; this also rejects NaN
      if (!(double_duration >= -9223372036854775808.0
            && double_duration < 9223372036854775808.0))
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "function duration got a value that is out of range");
          return NULL;
        }
      duration = double_duration;
    }
  else if (g_variant_type_equal (g_variant_get_type (value),
                                 G_VARIANT_TYPE_STRING))
    {
      // XXX: some players send mpris:length as a numeric string
      if (!g_ascii_string_to_signed (g_variant_get_string (value, NULL), 10, 0,
                                     G_MAXINT64, &duration, NULL))
        {
          set_duration_type_error (error);
          return NULL;
        }
    }
  else
    {
      set_duration_type_error (error);
      return NULL;
    }

  return format_duration (duration);
}

/* STYLE: the continuation line of this comment is not aligned (GNU style: "
   * " on every line). */
/* Calls g_markup_escape_text to replace the text with appropriately escaped
characters for XML */
GVariant *
helperfn_markup_escape (struct token *token, GVariant **args, int nargs,
                        GError **error)
{
  return transform_single_argument (g_markup_escape_text, args);
}

GVariant *
helperfn_default (struct token *token, GVariant **args, int nargs,
                  GError **error)
{
  if (args[0] == NULL && args[1] == NULL)
    {
      return NULL;
    }

  if (args[0] == NULL)
    {
      g_variant_ref (args[1]);
      return args[1];
    }

  // a string or list of strings that prints as nothing counts as empty
  if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_STRING)
      || g_variant_is_of_type (args[0], G_VARIANT_TYPE_STRING_ARRAY))
    {
      gchar *printed = pctl_print_gvariant (args[0]);
      gboolean is_empty = printed[0] == '\0';
      g_free (printed);
      if (is_empty)
        {
          g_variant_ref (args[1]);
          return args[1];
        }
    }
  g_variant_ref (args[0]);
  return args[0];
}

GVariant *
helperfn_emoji (struct token *token, GVariant **args, int nargs,
                GError **error)
{
  GVariant *value = args[0];
  if (value == NULL)
    {
      return g_variant_new ("s", "");
    }

  struct token *arg_token = g_list_first (token->args)->data;

  if (arg_token->type != TOKEN_VARIABLE)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "the emoji function can only be called with a variable");
      return NULL;
    }

  gchar *key = arg_token->data;

  if (g_strcmp0 (key, "status") == 0
      && g_variant_is_of_type (value, G_VARIANT_TYPE_STRING))
    {
      const gchar *status_str = g_variant_get_string (value, NULL);
      PlayerctlPlaybackStatus status = 0;
      if (pctl_parse_playback_status (status_str, &status))
        {
          switch (status)
            {
            case PLAYERCTL_PLAYBACK_STATUS_PLAYING:
              return g_variant_new ("s", "▶️");
            case PLAYERCTL_PLAYBACK_STATUS_STOPPED:
              return g_variant_new ("s", "⏹️");
            case PLAYERCTL_PLAYBACK_STATUS_PAUSED:
              return g_variant_new ("s", "⏸️");
            }
        }
    }
  else if (g_strcmp0 (key, "loop") == 0
           && g_variant_is_of_type (value, G_VARIANT_TYPE_STRING))
    {
      PlayerctlLoopStatus loop = 0;
      if (pctl_parse_loop_status (g_variant_get_string (value, NULL), &loop))
        {
          switch (loop)
            {
            case PLAYERCTL_LOOP_STATUS_TRACK:
              return g_variant_new ("s", "🔂");
            case PLAYERCTL_LOOP_STATUS_PLAYLIST:
              return g_variant_new ("s", "🔁");
            case PLAYERCTL_LOOP_STATUS_NONE:
              return g_variant_new ("s", "➡️");
            }
        }
    }
  else if (g_strcmp0 (key, "shuffle") == 0
           && g_variant_is_of_type (value, G_VARIANT_TYPE_BOOLEAN))
    {
      return g_variant_new ("s", g_variant_get_boolean (value) ? "🔀" : "➡️");
    }
  else if (g_strcmp0 (key, "volume") == 0
           && g_variant_is_of_type (value, G_VARIANT_TYPE_DOUBLE))
    {
      const gdouble volume = g_variant_get_double (value);
      if (volume < VOLUME_LOW_THRESHOLD)
        {
          return g_variant_new ("s", "🔈");
        }
      if (volume < VOLUME_MEDIUM_THRESHOLD)
        {
          return g_variant_new ("s", "🔉");
        }
      return g_variant_new ("s", "🔊");
    }

  g_variant_ref (value);
  return value;
}

GVariant *
helperfn_trunc (struct token *token, GVariant **args, int nargs,
                GError **error)
{
  GVariant *value = args[0];
  GVariant *len = args[1];
  if (value == NULL || len == NULL)
    {
      return g_variant_new ("s", "");
    }

  if (!is_valid_numeric_type (len))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function trunc's length parameter must be a number");
      return NULL;
    }

  gdouble limit = get_double_value (len);
  if (!(limit >= 0.0))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function trunc's length parameter cannot be negative");
      return NULL;
    }

  gchar *orig = pctl_print_gvariant (value);
  glong total = g_utf8_strlen (orig, -1);
  glong end = limit < (gdouble)total ? (glong)limit : total;
  gchar *trunc = g_utf8_substring (orig, 0, end);

  GString *formatted = g_string_new (trunc);
  if (end < total)
    {
      g_string_append (formatted, "…");
    }

  gchar *formatted_inner = g_string_free (formatted, FALSE);
  GVariant *ret = g_variant_new ("s", formatted_inner);
  g_free (formatted_inner);
  g_free (trunc);
  g_free (orig);

  return ret;
}

// Type name of an operand for error messages; operands of unset variables
// are NULL.
static const gchar *
operand_type_name (GVariant *value)
{
  return value != NULL ? g_variant_get_type_string (value) : "NULL";
}

/* Reads a numeric argument of a rounding helper as a double. Numeric strings
   are accepted for the players that send numbers as strings. */
static gboolean
get_number_argument (const gchar *name, GVariant *value, gdouble *number,
                     GError **error)
{
  if (is_valid_numeric_type (value))
    {
      *number = get_double_value (value);
    }
  else if (g_variant_is_of_type (value, G_VARIANT_TYPE_STRING))
    {
      gchar *end = NULL;
      const gchar *str = g_variant_get_string (value, NULL);
      *number = g_ascii_strtod (str, &end);
      if (end == str || *end != '\0')
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "function %s can only be called on numbers", name);
          return FALSE;
        }
    }
  else
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function %s can only be called on numbers", name);
      return FALSE;
    }

  // 2^63 is exactly representable; this also rejects NaN
  if (!(*number >= -9223372036854775808.0 && *number < 9223372036854775808.0))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function %s got a value that is out of range", name);
      return FALSE;
    }
  return TRUE;
}

// Converts to int64, rounding to the nearest integer when "nearest" is set
// (halves away from zero) and toward zero otherwise.
static GVariant *
to_integer (const gchar *name, GVariant **args, gboolean nearest,
            GError **error)
{
  if (args[0] == NULL)
    {
      return g_variant_new ("s", "");
    }

  if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_INT64))
    {
      g_variant_ref (args[0]);
      return args[0];
    }

  gdouble number;
  if (!get_number_argument (name, args[0], &number, error))
    {
      return NULL;
    }

  gint64 result = (gint64)number;
  gdouble fraction = number - (gdouble)result;
  if (nearest && fraction >= 0.5)
    {
      result += 1;
    }
  else if (nearest && fraction <= -0.5)
    {
      result -= 1;
    }
  return g_variant_new ("x", result);
}

GVariant *
helperfn_round (struct token *token, GVariant **args, int nargs,
                GError **error)
{
  return to_integer ("round", args, TRUE, error);
}

GVariant *
helperfn_int (struct token *token, GVariant **args, int nargs, GError **error)
{
  return to_integer ("int", args, FALSE, error);
}

GVariant *
helperfn_replace (struct token *token, GVariant **args, int nargs,
                  GError **error)
{
  if (args[0] == NULL)
    {
      return g_variant_new ("s", "");
    }

  gchar *orig = pctl_print_gvariant (args[0]);
  gchar *from = pctl_print_gvariant (args[1]);
  gchar *to = pctl_print_gvariant (args[2]);
  gchar *result = NULL;

  if (from[0] == '\0')
    {
      result = g_strdup (orig);
    }
  else
    {
      gchar **parts = g_strsplit (orig, from, -1);
      result = g_strjoinv (to, parts);
      g_strfreev (parts);
    }

  GVariant *ret = g_variant_new ("s", result);
  g_free (result);
  g_free (orig);
  g_free (from);
  g_free (to);
  return ret;
}

GVariant *
helperfn_join (struct token *token, GVariant **args, int nargs, GError **error)
{
  if (args[0] == NULL)
    {
      return g_variant_new ("s", "");
    }

  gchar *sep = pctl_print_gvariant (args[1]);
  gchar *joined = NULL;

  if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_STRING_ARRAY))
    {
      gsize count;
      const gchar **strv = g_variant_get_strv (args[0], &count);
      // g_variant_get_strv () output is not NULL-terminated
      gchar **terminated = g_new0 (gchar *, count + 1);
      for (gsize i = 0; i < count; ++i)
        {
          terminated[i] = (gchar *)strv[i];
        }
      joined = g_strjoinv (sep, terminated);
      g_free (terminated);
      g_free (strv);
    }
  else
    {
      joined = pctl_print_gvariant (args[0]);
    }

  GVariant *ret = g_variant_new ("s", joined);
  g_free (joined);
  g_free (sep);
  return ret;
}

GVariant *
helperfn_pad (struct token *token, GVariant **args, int nargs, GError **error)
{
  if (args[0] == NULL || args[1] == NULL)
    {
      return g_variant_new ("s", "");
    }

  if (!is_valid_numeric_type (args[1]))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function pad's width parameter must be a number");
      return NULL;
    }

  gdouble width = get_double_value (args[1]);
  if (!(width > -1000000.0 && width < 1000000.0))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function pad's width parameter is out of range");
      return NULL;
    }

  gchar *orig = pctl_print_gvariant (args[0]);
  glong len = g_utf8_strlen (orig, -1);
  glong target = (glong)(width < 0 ? -width : width);
  GString *padded = g_string_new ("");

  // a negative width aligns right
  if (width < 0)
    {
      for (glong i = len; i < target; ++i)
        {
          g_string_append_c (padded, ' ');
        }
    }
  g_string_append (padded, orig);
  if (width >= 0)
    {
      for (glong i = len; i < target; ++i)
        {
          g_string_append_c (padded, ' ');
        }
    }

  gchar *padded_inner = g_string_free (padded, FALSE);
  GVariant *ret = g_variant_new ("s", padded_inner);
  g_free (padded_inner);
  g_free (orig);
  return ret;
}

GVariant *
helperfn_uri_decode (struct token *token, GVariant **args, int nargs,
                     GError **error)
{
  if (args[0] == NULL)
    {
      return g_variant_new ("s", "");
    }

  gchar *orig = pctl_print_gvariant (args[0]);
  gchar *decoded = g_uri_unescape_string (orig, NULL);
  // an invalid escape sequence leaves the string as it was
  GVariant *ret = g_variant_new ("s", decoded != NULL ? decoded : orig);
  g_free (decoded);
  g_free (orig);
  return ret;
}

/* Describes an infix operator for infix_binary (). */
struct infix_operator
{
  gchar symbol;
  const gchar *name;
  // add and sub report a NULL operand before the operand types are checked
  gboolean reports_null_operand;
};

static const struct infix_operator infix_add = { '+', "Addition", TRUE };
static const struct infix_operator infix_sub = { '-', "Subtraction", TRUE };
static const struct infix_operator infix_mul
    = { '*', "Multiplication", FALSE };
static const struct infix_operator infix_div = { '/', "Division", FALSE };

// Applies the operator to two int64 values; sets the error and returns FALSE
// on overflow or division by zero.
static gboolean
apply_int_operator (gchar symbol, gint64 val0, gint64 val1, gint64 *result,
                    GError **error)
{
  gboolean overflow = FALSE;
  switch (symbol)
    {
    case '+':
      overflow = __builtin_add_overflow (val0, val1, result);
      break;
    case '-':
      overflow = __builtin_sub_overflow (val0, val1, result);
      break;
    case '*':
      overflow = __builtin_mul_overflow (val0, val1, result);
      break;
    default:
      if (val1 == 0)
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "Divide by zero error");
          return FALSE;
        }
      overflow = val0 == G_MININT64 && val1 == -1;
      if (!overflow)
        {
          *result = val0 / val1;
        }
      break;
    }

  if (overflow)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "Numeric overflow detected");
    }
  return !overflow;
}

// Applies the operator to two doubles; sets the error and returns FALSE on
// division by zero.
static gboolean
apply_double_operator (gchar symbol, gdouble val0, gdouble val1,
                       gdouble *result, GError **error)
{
  switch (symbol)
    {
    case '+':
      *result = val0 + val1;
      break;
    case '-':
      *result = val0 - val1;
      break;
    case '*':
      *result = val0 * val1;
      break;
    default:
      if (val1 == 0.0)
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "Divide by zero error");
          return FALSE;
        }
      *result = val0 / val1;
      break;
    }
  return TRUE;
}

// The binary form of an infix operator: two numeric operands, an int64 result
// for two int64 operands and a double result otherwise.
static GVariant *
infix_binary (const struct infix_operator *op, GVariant **args, int nargs,
              GError **error)
{
  if (nargs != 2)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "%s takes two arguments (got %d). This is a bug in "
                   "Playerctl.",
                   op->name, nargs);
      return NULL;
    }

  if (op->reports_null_operand && (args[0] == NULL || args[1] == NULL))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "Got unsupported operand type for %c: NULL", op->symbol);
      return NULL;
    }

  if (!is_valid_numeric_type (args[0]) || !is_valid_numeric_type (args[1]))
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "Got unsupported operand types for %c: '%s' and '%s'",
                   op->symbol, operand_type_name (args[0]),
                   operand_type_name (args[1]));
      return NULL;
    }

  if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_INT64)
      && g_variant_is_of_type (args[1], G_VARIANT_TYPE_INT64))
    {
      gint64 result;
      if (!apply_int_operator (op->symbol, g_variant_get_int64 (args[0]),
                               g_variant_get_int64 (args[1]), &result, error))
        {
          return NULL;
        }
      return g_variant_new ("x", result);
    }

  gdouble result;
  if (!apply_double_operator (op->symbol, get_double_value (args[0]),
                              get_double_value (args[1]), &result, error))
    {
      return NULL;
    }
  return g_variant_new ("d", result);
}

/* XXX: SUSPICIOUS: __builtin_*_overflow is a GCC/Clang extension. */
GVariant *
infixfn_add (struct token *token, GVariant **args, int nargs, GError **error)
{
  if (nargs == 1)
    {
      // unary addition
      if (!is_valid_numeric_type (args[0]))
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "Got unsupported operand type for unary +: '%s'",
                       operand_type_name (args[0]));
          return NULL;
        }
      g_variant_ref (args[0]);
      return args[0];
    }

  return infix_binary (&infix_add, args, nargs, error);
}

GVariant *
infixfn_sub (struct token *token, GVariant **args, int nargs, GError **error)
{
  if (nargs == 1)
    {
      // unary negation
      if (args[0] == NULL)
        {
          g_set_error (error, playerctl_formatter_error_quark (), 1,
                       "Got unsupported operand type for unary -: NULL");
          return NULL;
        }
      if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_INT64))
        {
          gint64 result;
          if (__builtin_sub_overflow ((gint64)0, g_variant_get_int64 (args[0]),
                                      &result))
            {
              g_set_error (error, playerctl_formatter_error_quark (), 1,
                           "Numeric overflow detected");
              return NULL;
            }
          return g_variant_new ("x", result);
        }
      if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_UINT64))
        {
          guint64 value = g_variant_get_uint64 (args[0]);
          if (value <= G_MAXINT64)
            {
              return g_variant_new ("x", -(gint64)value);
            }
          return g_variant_new ("d", -(gdouble)value);
        }
      if (g_variant_is_of_type (args[0], G_VARIANT_TYPE_DOUBLE))
        {
          gdouble value = g_variant_get_double (args[0]);
          /* STYLE: "value * -1" here, "-value" in the other branches; pick
             one. */
          return g_variant_new ("d", value * -1);
        }

      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "Got unsupported operand type for unary -: '%s'",
                   operand_type_name (args[0]));
      return NULL;
    }

  return infix_binary (&infix_sub, args, nargs, error);
}

GVariant *
infixfn_mul (struct token *token, GVariant **args, int nargs, GError **error)
{
  return infix_binary (&infix_mul, args, nargs, error);
}

GVariant *
infixfn_div (struct token *token, GVariant **args, int nargs, GError **error)
{
  return infix_binary (&infix_div, args, nargs, error);
}

const struct template_function template_functions[TEMPLATE_FUNCTION_COUNT] = {
  { "lc", 1, 1, &helperfn_lc },
  { "uc", 1, 1, &helperfn_uc },
  { "duration", 1, 1, &helperfn_duration },
  { "markup_escape", 1, 1, &helperfn_markup_escape },
  { "json_escape", 1, 1, &helperfn_json_escape },
  { "default", 2, 2, &helperfn_default },
  { "emoji", 1, 1, &helperfn_emoji },
  { "trunc", 2, 2, &helperfn_trunc },
  { "round", 1, 1, &helperfn_round },
  { "int", 1, 1, &helperfn_int },
  { "replace", 3, 3, &helperfn_replace },
  { "join", 2, 2, &helperfn_join },
  { "pad", 2, 2, &helperfn_pad },
  { "uri_decode", 1, 1, &helperfn_uri_decode },
  { INFIX_ADD, 1, 2, &infixfn_add },
  { INFIX_SUB, 1, 2, &infixfn_sub },
  { INFIX_MUL, 2, 2, &infixfn_mul },
  { INFIX_DIV, 2, 2, &infixfn_div },
};

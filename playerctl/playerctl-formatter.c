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

#define MAX_ARGS 32

/* The longest format string accepted by tokenize_format (); the parse buffers
   hold one more character for the terminating NUL. */
#define MAX_FORMAT_LENGTH 1027
#define FORMAT_BUF_SIZE (MAX_FORMAT_LENGTH + 1)

/* Volumes below these levels select the low and the medium speaker emoji. */
#define VOLUME_LOW_THRESHOLD 0.3333
#define VOLUME_MEDIUM_THRESHOLD 0.6666

#define INFIX_ADD "+"
#define INFIX_SUB "-"
#define INFIX_MUL "*"
#define INFIX_DIV "/"

// clang-format off
G_DEFINE_QUARK(playerctl-formatter-error-quark, playerctl_formatter_error);
// clang-format on

enum token_type
{
  TOKEN_VARIABLE,
  TOKEN_STRING,
  TOKEN_FUNCTION,
  TOKEN_NUMBER,
};

struct token
{
  enum token_type type;
  gchar *data;
  gdouble numeric_data;
  GList *args;
};

enum parser_state
{
  STATE_EXPRESSION = 0,
  STATE_IDENTIFIER,
  STATE_STRING,
  STATE_NUMBER,
};

enum parse_level
{
  PARSE_FULL = 0,
  PARSE_NEXT_IDENT,
  PARSE_MULT_DIV,
};

struct _PlayerctlFormatterPrivate
{
  GList *tokens;
};

static struct token *
token_create (enum token_type type)
{
  struct token *token = g_new0 (struct token, 1);
  token->type = type;
  return token;
}

static void token_list_destroy (GList *tokens);

static void
token_destroy (struct token *token)
{
  if (token == NULL)
    {
      return;
    }

  token_list_destroy (token->args);
  g_free (token->data);
  g_free (token);
}

static void
token_list_destroy (GList *tokens)
{
  if (tokens == NULL)
    {
      return;
    }

  g_list_free_full (tokens, (GDestroyNotify)token_destroy);
}

static gboolean
token_list_contains_key (GList *tokens, const gchar *key)
{
  if (tokens == NULL)
    {
      return FALSE;
    }

  GList *t;
  for (t = tokens; t != NULL; t = t->next)
    {
      struct token *token = t->data;
      switch (token->type)
        {
        case TOKEN_VARIABLE:
          if (g_strcmp0 (token->data, key) == 0)
            {
              return TRUE;
            }
          break;
        case TOKEN_FUNCTION:
          if (token_list_contains_key (token->args, key))
            {
              return TRUE;
            }
        /* STYLE: TOKEN_FUNCTION falls through into default without a break
           or a fallthrough annotation. */
        default:
          break;
        }
    }
  return FALSE;
}

static gboolean
is_identifier_start_char (gchar c)
{
  return g_ascii_isalpha (c) || c == '_';
}

static gboolean
is_identifier_char (gchar c)
{
  return g_ascii_isalnum (c) || c == '_' || c == ':';
}

static gboolean
is_numeric_char (gchar c)
{
  return g_ascii_isdigit (c) || c == '.';
}

static gchar *
infix_to_identifier (gchar infix)
{
  switch (infix)
    {
    case '+':
      return g_strdup (INFIX_ADD);
    case '-':
      return g_strdup (INFIX_SUB);
    case '*':
      return g_strdup (INFIX_MUL);
    case '/':
      return g_strdup (INFIX_DIV);
    default:
      assert (false && "not reached");
      return NULL;
    }
}

/* Creates a function token for the infix operator "infix" applied to
   "left" and "right"; the new token owns both operands. */
static struct token *
create_operation (gchar infix, struct token *left, struct token *right)
{
  struct token *operation = token_create (TOKEN_FUNCTION);
  operation->data = infix_to_identifier (infix);
  operation->args = g_list_append (operation->args, left);
  operation->args = g_list_append (operation->args, right);
  return operation;
}

static struct token *tokenize_expression (const gchar *format, gint pos,
                                          gint *end, enum parse_level level,
                                          GError **error);

/* The state of one tokenize_expression () call. */
struct expression_parser
{
  const gchar *format;
  int len;
  gint *end;
  GError **error;
  /* XXX: SUSPICIOUS: no bounds check on buf_len++ in the step functions; it
     is only safe because tokenize_format() rejects formats longer than
     MAX_FORMAT_LENGTH. Use a GString. */
  char buf[FORMAT_BUF_SIZE];
  int buf_len;
  enum parser_state state;
  struct token *tok;
};

enum parser_step
{
  STEP_CONTINUE, // go on with the next character
  STEP_DONE,     // parser->tok is complete
  STEP_FAIL,     // the error is set
};

// Sets the end of the expression to the first non-space character from i.
static void
parser_set_end (struct expression_parser *parser, int i)
{
  while (i < parser->len && parser->format[i] == ' ')
    {
      i++;
    }
  *parser->end = i;
}

// ordering parens
static enum parser_step
step_parens (struct expression_parser *parser, int i)
{
  GError *tmp_error = NULL;
  parser->tok = tokenize_expression (parser->format, i + 1, parser->end,
                                     PARSE_FULL, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (parser->error, tmp_error);
      return STEP_FAIL;
    }

  if (*parser->end > parser->len - 1 || parser->format[*parser->end] != ')')
    {
      g_set_error (parser->error, playerctl_formatter_error_quark (), 1,
                   "expected \")\" (position  %d)", *parser->end);
      token_destroy (parser->tok);
      return STEP_FAIL;
    }
  *parser->end += 1;

  return STEP_DONE;
}

// unary + or -
static enum parser_step
step_unary (struct expression_parser *parser, int i)
{
  GError *tmp_error = NULL;
  struct token *operand = tokenize_expression (
      parser->format, i + 1, parser->end, PARSE_NEXT_IDENT, &tmp_error);
  if (tmp_error != NULL)
    {
      g_propagate_error (parser->error, tmp_error);
      return STEP_FAIL;
    }
  parser->tok = token_create (TOKEN_FUNCTION);
  parser->tok->data = infix_to_identifier (parser->format[i]);
  parser->tok->args = g_list_append (parser->tok->args, operand);
  return STEP_DONE;
}

static enum parser_step
step_expression (struct expression_parser *parser, int i)
{
  gchar c = parser->format[i];
  if (c == ' ')
    {
      return STEP_CONTINUE;
    }
  if (c == '(')
    {
      return step_parens (parser, i);
    }
  if (c == '+' || c == '-')
    {
      return step_unary (parser, i);
    }
  if (c == '"')
    {
      parser->state = STATE_STRING;
      return STEP_CONTINUE;
    }
  if (is_numeric_char (c))
    {
      parser->state = STATE_NUMBER;
      parser->buf[parser->buf_len++] = c;
      return STEP_CONTINUE;
    }
  if (!is_identifier_start_char (c))
    {
      g_set_error (parser->error, playerctl_formatter_error_quark (), 1,
                   "unexpected \"%c\", expected expression (position  %d)", c,
                   i);
      return STEP_FAIL;
    }
  parser->state = STATE_IDENTIFIER;
  parser->buf[parser->buf_len++] = c;
  return STEP_CONTINUE;
}

static enum parser_step
step_string (struct expression_parser *parser, int i)
{
  if (parser->format[i] != '"')
    {
      parser->buf[parser->buf_len++] = parser->format[i];
      return STEP_CONTINUE;
    }

  parser->tok = token_create (TOKEN_STRING);
  parser->buf[parser->buf_len] = '\0';
  parser->tok->data = g_strdup (parser->buf);
  parser_set_end (parser, i + 1);
  return STEP_DONE;
}

static enum parser_step
step_number (struct expression_parser *parser, int i)
{
  /* XXX: SUSPICIOUS: "i == len - 2" is an unexplained special case:
     a numeric character at that position ends the number and is not
     added to buf. */
  if (is_numeric_char (parser->format[i]) && i != parser->len - 2)
    {
      parser->buf[parser->buf_len++] = parser->format[i];
      return STEP_CONTINUE;
    }

  struct token *tok = token_create (TOKEN_NUMBER);
  parser->tok = tok;
  parser->buf[parser->buf_len] = '\0';
  tok->data = g_strdup (parser->buf);
  char *endptr = NULL;
  gdouble number = strtod (tok->data, &endptr);
  if (endptr == NULL || *endptr != '\0')
    {
      g_set_error (parser->error, playerctl_formatter_error_quark (), 1,
                   "invalid number: \"%s\" (position %d)", tok->data, i);
      token_destroy (tok);
      return STEP_FAIL;
    }
  tok->numeric_data = number;
  parser_set_end (parser, i);
  return STEP_DONE;
}

// Parses the arguments of the function call in parser->tok, from position i
// (just after the opening paren) to the closing paren.
static gboolean
parse_call_args (struct expression_parser *parser, int i)
{
  GError *tmp_error = NULL;
  const gchar *format = parser->format;
  gint *end = parser->end;
  int nargs = 0;

  while (TRUE)
    {
      struct token *arg
          = tokenize_expression (format, i, end, PARSE_FULL, &tmp_error);
      if (arg != NULL)
        {
          parser->tok->args = g_list_append (parser->tok->args, arg);
        }

      nargs++;

      if (nargs > MAX_ARGS)
        {
          g_set_error (parser->error, playerctl_formatter_error_quark (), 1,
                       "maximum args of %d exceeded", MAX_ARGS);
          token_destroy (parser->tok);
          return FALSE;
        }

      if (tmp_error != NULL)
        {
          token_destroy (parser->tok);
          g_propagate_error (parser->error, tmp_error);
          return FALSE;
        }

      while (*end < parser->len && format[*end] == ' ')
        {
          *end += 1;
        }

      if (format[*end] == ')')
        {
          *end += 1;
          return TRUE;
        }
      if (format[*end] != ',')
        {
          g_set_error (parser->error, playerctl_formatter_error_quark (), 1,
                       "expecting \")\" (position %d)", *end);
          token_destroy (parser->tok);
          return FALSE;
        }
      i = *end + 1;
    }
}

static enum parser_step
step_identifier (struct expression_parser *parser, int i)
{
  gchar c = parser->format[i];
  if (c == '(')
    {
      parser->tok = token_create (TOKEN_FUNCTION);
      parser->buf[parser->buf_len] = '\0';
      parser->tok->data = g_strdup (parser->buf);
      return parse_call_args (parser, i + 1) ? STEP_DONE : STEP_FAIL;
    }
  if (!is_identifier_char (c))
    {
      parser->tok = token_create (TOKEN_VARIABLE);
      parser->buf[parser->buf_len] = '\0';
      parser->tok->data = g_strdup (parser->buf);
      parser_set_end (parser, i);
      return STEP_DONE;
    }
  parser->buf[parser->buf_len] = c;
  ++parser->buf_len;
  return STEP_CONTINUE;
}

static enum parser_step
parser_step (struct expression_parser *parser, int i)
{
  switch (parser->state)
    {
    case STATE_EXPRESSION:
      return step_expression (parser, i);
    case STATE_STRING:
      return step_string (parser, i);
    case STATE_NUMBER:
      return step_number (parser, i);
    case STATE_IDENTIFIER:
      return step_identifier (parser, i);
    }
  return STEP_CONTINUE;
}

/* Parses the operand of the infix operator infix_id at *end with the parse
   level "operand_level" and returns the operation of tok and the operand.
   Takes ownership of tok. */
static struct token *
parse_infix_operand (const gchar *format, gchar infix_id,
                     enum parse_level operand_level, struct token *tok,
                     gint *end, GError **error)
{
  GError *tmp_error = NULL;
  struct token *operand
      = tokenize_expression (format, *end + 1, end, operand_level, &tmp_error);
  if (tmp_error != NULL)
    {
      token_destroy (tok);
      g_propagate_error (error, tmp_error);
      return NULL;
    }

  return create_operation (infix_id, tok, operand);
}

static gboolean
is_infix_char (gchar c)
{
  return c == '*' || c == '/' || c == '+' || c == '-';
}

// Parses the infix operators after the operand tok, according to the
// precedence of level. Takes ownership of tok.
static struct token *
parse_infix (const gchar *format, struct token *tok, gint *end,
             enum parse_level level, GError **error)
{
  gchar infix_id = format[*end];
  while (is_infix_char (infix_id))
    {
      while (infix_id == '*' || infix_id == '/')
        {
          tok = parse_infix_operand (format, infix_id, PARSE_NEXT_IDENT, tok,
                                     end, error);
          if (tok == NULL)
            {
              return NULL;
            }
          infix_id = format[*end];
        }

      if (level == PARSE_MULT_DIV)
        {
          return tok;
        }

      if (infix_id == '+' || infix_id == '-')
        {
          tok = parse_infix_operand (format, infix_id, PARSE_MULT_DIV, tok,
                                     end, error);
          if (tok == NULL)
            {
              return NULL;
            }
          infix_id = format[*end];
        }
    }

  return tok;
}

static struct token *
tokenize_expression (const gchar *format, gint pos, gint *end,
                     enum parse_level level, GError **error)
{
  int len = strlen (format);

  if (pos > len - 1)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "unexpected end of expression");
      return NULL;
    }

  struct expression_parser parser = {
    .format = format,
    .len = len,
    .end = end,
    .error = error,
    .state = STATE_EXPRESSION,
  };

  for (int i = pos; i < len; ++i)
    {
      enum parser_step step = parser_step (&parser, i);
      if (step == STEP_FAIL)
        {
          return NULL;
        }
      if (step == STEP_DONE)
        {
          break;
        }
    }

  struct token *tok = parser.tok;
  if (tok == NULL)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "unexpected end of expression");
      return NULL;
    }
  while (*end < len && format[*end] == ' ')
    {
      *end += 1;
    }
  if (level == PARSE_NEXT_IDENT || *end >= len - 1)
    {
      return tok;
    }

  return parse_infix (format, tok, end, level, error);
}

static GList *
tokenize_format (const char *format, GError **error)
{
  GError *tmp_error = NULL;
  GList *tokens = NULL;

  if (format == NULL)
    {
      return NULL;
    }

  int len = strlen (format);
  char buf[FORMAT_BUF_SIZE];
  int buf_len = 0;

  if (len > MAX_FORMAT_LENGTH)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "the maximum format string length is %d",
                   MAX_FORMAT_LENGTH);
      return NULL;
    }

  for (int i = 0; i < len; ++i)
    {
      if (format[i] == '{' && format[i + 1] == '{')
        {
          if (buf_len > 0)
            {
              buf[buf_len] = '\0';
              buf_len = 0;
              struct token *token = token_create (TOKEN_STRING);
              token->data = g_strdup (buf);
              tokens = g_list_append (tokens, token);
            }

          i += 2;
          int end = 0;
          struct token *token
              = tokenize_expression (format, i, &end, PARSE_FULL, &tmp_error);
          if (tmp_error != NULL)
            {
              token_destroy (token); // NULL on error; keeps analyzers happy
              token_list_destroy (tokens);
              g_propagate_error (error, tmp_error);
              return NULL;
            }
          tokens = g_list_append (tokens, token);
          i = end;

          while (i < len && format[i] == ' ')
            {
              i++;
            }

          if (i >= len || format[i] != '}' || format[i + 1] != '}')
            {
              token_list_destroy (tokens);
              g_set_error (error, playerctl_formatter_error_quark (), 1,
                           "expecting \"}}\" (position %d)", i);
              return NULL;
            }
          i += 1;
        }
      else
        {
          buf[buf_len++] = format[i];
        }
    }

  if (buf_len > 0)
    {
      buf[buf_len] = '\0';
      struct token *token = token_create (TOKEN_STRING);
      token->data = g_strdup (buf);
      tokens = g_list_append (tokens, token);
    }

  return tokens;
}

/* XXX: DRY: the nargs/NULL preamble repeats in all seven helpers; "token" is
   unused in most. */

/* Prints the single argument and returns it transformed by "transform". */
static GVariant *
transform_single_argument (const gchar *name,
                           gchar *(*transform) (const gchar *, gssize),
                           GVariant **args, int nargs, GError **error)
{
  if (nargs != 1)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function %s takes exactly one argument (got %d)", name,
                   nargs);
      return NULL;
    }

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

static GVariant *
helperfn_lc (struct token *token, GVariant **args, int nargs, GError **error)
{
  return transform_single_argument ("lc", g_utf8_strdown, args, nargs, error);
}

static GVariant *
helperfn_uc (struct token *token, GVariant **args, int nargs, GError **error)
{
  return transform_single_argument ("uc", g_utf8_strup, args, nargs, error);
}

// Formats a duration in microseconds as [h:]mm:ss.
static GVariant *
format_duration (gint64 duration)
{
  /* XXX: SUSPICIOUS: a negative duration prints something like "0:-5",
     because the modulo of a negative number keeps its sign. */
  gint64 seconds = (duration / 1000000) % 60;
  gint64 minutes = (duration / 1000000 / 60) % 60;
  gint64 hours = (duration / 1000000 / 60 / 60);

  GString *formatted = g_string_new ("");

  if (hours != 0)
    {
      g_string_append_printf (formatted,
                              "%" PRId64 ":%02" PRId64 ":%02" PRId64, hours,
                              minutes, seconds);
    }
  else
    {
      g_string_append_printf (formatted, "%" PRId64 ":%02" PRId64, minutes,
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

static GVariant *
helperfn_duration (struct token *token, GVariant **args, int nargs,
                   GError **error)
{
  if (nargs != 1)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function duration takes exactly one argument (got %d)",
                   nargs);
      return NULL;
    }

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
static GVariant *
helperfn_markup_escape (struct token *token, GVariant **args, int nargs,
                        GError **error)
{
  return transform_single_argument ("markup_escape", g_markup_escape_text,
                                    args, nargs, error);
}

static GVariant *
helperfn_default (struct token *token, GVariant **args, int nargs,
                  GError **error)
{
  if (nargs != 2)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function default takes exactly two arguments (got %d)",
                   nargs);
      return NULL;
    }

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

static GVariant *
helperfn_emoji (struct token *token, GVariant **args, int nargs,
                GError **error)
{
  if (nargs != 1)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function emoji takes exactly one argument (got %d)",
                   nargs);
      return NULL;
    }

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

static GVariant *
helperfn_trunc (struct token *token, GVariant **args, int nargs,
                GError **error)
{
  if (nargs != 2)
    {
      g_set_error (error, playerctl_formatter_error_quark (), 1,
                   "function trunc takes exactly two arguments (got %d)",
                   nargs);
      return NULL;
    }

  GVariant *value = args[0];
  GVariant *len = args[1];
  if (value == NULL || len == NULL)
    {
      return g_variant_new ("s", "");
    }

  /* XXX: stale message: trunc says "can only be called with an int" but
     checks for DOUBLE. */
  if (!g_variant_type_equal (g_variant_get_type (len), G_VARIANT_TYPE_DOUBLE))
    {
      g_set_error (
          error, playerctl_formatter_error_quark (), 1,
          "function trunc's length parameter can only be called with an int");
      return NULL;
    }

  gdouble limit = g_variant_get_double (len);
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

static gboolean
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

static gdouble
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

// Type name of an operand for error messages; operands of unset variables
// are NULL.
static const gchar *
operand_type_name (GVariant *value)
{
  return value != NULL ? g_variant_get_type_string (value) : "NULL";
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
static GVariant *
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

static GVariant *
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

static GVariant *
infixfn_mul (struct token *token, GVariant **args, int nargs, GError **error)
{
  return infix_binary (&infix_mul, args, nargs, error);
}

static GVariant *
infixfn_div (struct token *token, GVariant **args, int nargs, GError **error)
{
  return infix_binary (&infix_div, args, nargs, error);
}

/* STYLE: global table with external linkage, defined together with its
   struct tag; make it static const. */
struct template_function
{
  const gchar *name;
  GVariant *(*func) (struct token *token, GVariant **args, int nargs,
                     GError **error);
} template_functions[] = {
  { "lc", &helperfn_lc },
  { "uc", &helperfn_uc },
  { "duration", &helperfn_duration },
  { "markup_escape", &helperfn_markup_escape },
  { "default", &helperfn_default },
  { "emoji", &helperfn_emoji },
  { "trunc", &helperfn_trunc },
  { INFIX_ADD, &infixfn_add },
  { INFIX_SUB, &infixfn_sub },
  { INFIX_MUL, &infixfn_mul },
  { INFIX_DIV, &infixfn_div },
};

static GVariant *
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

static gchar *
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

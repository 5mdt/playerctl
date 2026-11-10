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

#include "playerctl/playerctl-common.h"
#include "playerctl/playerctl-formatter-private.h"

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

struct token *
token_create (enum token_type type)
{
  struct token *token = g_new0 (struct token, 1);
  token->type = type;
  return token;
}

void
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

void
token_list_destroy (GList *tokens)
{
  if (tokens == NULL)
    {
      return;
    }

  g_list_free_full (tokens, (GDestroyNotify)token_destroy);
}

gboolean
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

gchar *
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

GList *
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

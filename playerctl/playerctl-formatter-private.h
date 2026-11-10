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

#ifndef __PLAYERCTL_FORMATTER_PRIVATE_H__
#define __PLAYERCTL_FORMATTER_PRIVATE_H__

/* Internals shared by the formatter implementation files (parser, helpers,
   evaluator) and by test/c/test_formatter.c. Not installed; the symbols stay
   hidden by data/playerctl.syms. */

#include <glib.h>

#define MAX_ARGS 32

/* The longest format string accepted by tokenize_format (); the parse buffers
   hold one more character for the terminating NUL. */
#define MAX_FORMAT_LENGTH 1027
#define FORMAT_BUF_SIZE (MAX_FORMAT_LENGTH + 1)

#define INFIX_ADD "+"
#define INFIX_SUB "-"
#define INFIX_MUL "*"
#define INFIX_DIV "/"

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

/* parser */
struct token *token_create (enum token_type type);
void token_destroy (struct token *token);
void token_list_destroy (GList *tokens);
gboolean token_list_contains_key (GList *tokens, const gchar *key);
gchar *infix_to_identifier (gchar infix);
GList *tokenize_format (const char *format, GError **error);

/* helpers */
gboolean is_valid_numeric_type (GVariant *value);
gdouble get_double_value (GVariant *value);

#define DECLARE_TEMPLATE_FUNCTION(name)                                       \
  GVariant *name (struct token *token, GVariant **args, int nargs,            \
                  GError **error)

DECLARE_TEMPLATE_FUNCTION (helperfn_lc);
DECLARE_TEMPLATE_FUNCTION (helperfn_uc);
DECLARE_TEMPLATE_FUNCTION (helperfn_json_escape);
DECLARE_TEMPLATE_FUNCTION (helperfn_duration);
DECLARE_TEMPLATE_FUNCTION (helperfn_markup_escape);
DECLARE_TEMPLATE_FUNCTION (helperfn_default);
DECLARE_TEMPLATE_FUNCTION (helperfn_emoji);
DECLARE_TEMPLATE_FUNCTION (helperfn_trunc);
DECLARE_TEMPLATE_FUNCTION (helperfn_round);
DECLARE_TEMPLATE_FUNCTION (helperfn_int);
DECLARE_TEMPLATE_FUNCTION (helperfn_replace);
DECLARE_TEMPLATE_FUNCTION (helperfn_join);
DECLARE_TEMPLATE_FUNCTION (helperfn_pad);
DECLARE_TEMPLATE_FUNCTION (helperfn_uri_decode);
DECLARE_TEMPLATE_FUNCTION (infixfn_add);
DECLARE_TEMPLATE_FUNCTION (infixfn_sub);
DECLARE_TEMPLATE_FUNCTION (infixfn_mul);
DECLARE_TEMPLATE_FUNCTION (infixfn_div);

struct template_function
{
  const gchar *name;
  int min_args;
  int max_args;
  GVariant *(*func) (struct token *token, GVariant **args, int nargs,
                     GError **error);
};

#define TEMPLATE_FUNCTION_COUNT 18
extern const struct template_function
    template_functions[TEMPLATE_FUNCTION_COUNT];

/* evaluator */
gboolean check_argument_count (const struct template_function *function,
                               int nargs, GError **error);
GVariant *expand_token (struct token *token, GVariantDict *context,
                        GError **error);

gchar *expand_format (GList *tokens, GVariantDict *context, GError **error);

GQuark playerctl_formatter_error_quark (void);

#endif /* __PLAYERCTL_FORMATTER_PRIVATE_H__ */

/* Adversarial tests for the formatter (parser, helpers, evaluator).
 *
 * Every test runs in its own subprocess, so a crash or a fatal GLib
 * critical is detected and does not take the suite down.
 *
 * Known defects are registered as "known bugs": the assertion text keeps
 * the expected-correct behaviour, the test is reported as incomplete
 * (TAP "TODO") while the defect exists, and fails with "appears fixed"
 * once the defect is fixed, so the marker is then removed. Leaks cannot be
 * seen without a leak checker; those cases are always reported as
 * incomplete. See build/qa/bugs-formatter.md.
 *
 * ADV_DUMP=1 prints the outcome of every table row (used to review the
 * expected values). */

#include <glib.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

#include "playerctl/playerctl-formatter.h"
#include "playerctl/playerctl-formatter-private.h"

/* ---- harness ---- */

struct tcase {
    void (*fn)(void);
    const gchar *bug; /* NULL: a normal test */
    gboolean leak;    /* the bug is a leak: never strict */
};

static void finish_known_bug(const gchar *bug, gboolean leak) {
    if (leak) {
        g_test_incomplete(bug);
    } else if (!g_test_trap_has_passed()) {
        g_test_incomplete(bug);
    } else {
        g_test_message("%s appears fixed: remove the marker", bug);
        g_test_fail();
    }
}

/* ADV_VERBOSE=1 shows the output of the subprocesses (to see why a known
 * bug fails). */
static GTestSubprocessFlags trap_flags(void) {
    return g_getenv("ADV_VERBOSE") != NULL ? G_TEST_SUBPROCESS_INHERIT_STDERR : 0;
}

static void run_case(gconstpointer data) {
    const struct tcase *tc = data;
    if (g_test_subprocess()) {
        tc->fn();
        return;
    }
    g_test_trap_subprocess(NULL, 0, trap_flags());
    if (tc->bug == NULL) {
        g_test_trap_assert_passed();
        return;
    }
    finish_known_bug(tc->bug, tc->leak);
}

#define T(path, fn)                                                    \
    do {                                                               \
        static const struct tcase _tc = {fn, NULL, FALSE};             \
        g_test_add_data_func("/formatter-adv/" path, &_tc, run_case);  \
    } while (0)
#define TB(path, fn, bug)                                              \
    do {                                                               \
        static const struct tcase _tc = {fn, bug, FALSE};              \
        g_test_add_data_func("/formatter-adv/" path, &_tc, run_case);  \
    } while (0)
#define TL(path, fn, bug)                                              \
    do {                                                               \
        static const struct tcase _tc = {fn, bug, TRUE};               \
        g_test_add_data_func("/formatter-adv/" path, &_tc, run_case);  \
    } while (0)

static gchar *render(const gchar *format, GVariantDict *ctx, GError **err) {
    GError *new_err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(format, &new_err);
    if (new_err != NULL) {
        g_propagate_error(err, new_err);
        return NULL;
    }
    gchar *out = playerctl_formatter_expand_format(f, ctx, err);
    playerctl_formatter_destroy(f);
    return out;
}

static GVariantDict *empty_ctx(void) {
    return g_variant_dict_new(NULL);
}

static void assert_formatter_error(GError *err) {
    g_assert_nonnull(err);
    g_assert_true(g_error_matches(err, playerctl_formatter_error_quark(), 1));
}

static void assert_renders(GVariantDict *ctx, const gchar *fmt, const gchar *expected) {
    GError *err = NULL;
    gchar *s = render(fmt, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(s, ==, expected);
    g_free(s);
}

static void assert_render_fails(GVariantDict *ctx, const gchar *fmt, const gchar *glob) {
    GError *err = NULL;
    gchar *s = render(fmt, ctx, &err);
    g_assert_null(s);
    assert_formatter_error(err);
    if (!g_pattern_match_simple(glob, err->message)) {
        g_test_message("message \"%s\" does not match \"%s\"", err->message, glob);
        g_assert_not_reached();
    }
    g_clear_error(&err);
}

/* ---- the shared context of the table rows ---- */

static GVariantDict *make_ctx(void) {
    GVariantDict *d = g_variant_dict_new(NULL);
    const gchar *arr[] = {"a", "b", NULL};
    gchar *long_str = g_strnfill(2000, 'x');
    g_variant_dict_insert(d, "s", "s", "Song");
    g_variant_dict_insert(d, "estr", "s", "");
    g_variant_dict_insert(d, "i", "x", (gint64)5);
    g_variant_dict_insert(d, "neg", "x", (gint64)-7);
    g_variant_dict_insert(d, "m1", "x", (gint64)-1);
    g_variant_dict_insert(d, "zero", "x", (gint64)0);
    g_variant_dict_insert(d, "big", "x", (gint64)INT64_MAX);
    g_variant_dict_insert(d, "min", "x", (gint64)INT64_MIN);
    g_variant_dict_insert(d, "dur", "x", (gint64)3661000000);
    g_variant_dict_insert(d, "u", "t", (guint64)5);
    g_variant_dict_insert(d, "umax", "t", (guint64)UINT64_MAX);
    g_variant_dict_insert(d, "uhalf", "t", (guint64)1 << 63);
    g_variant_dict_insert(d, "d", "d", 2.5);
    g_variant_dict_insert(d, "nan", "d", (gdouble)NAN);
    g_variant_dict_insert(d, "inf", "d", (gdouble)INFINITY);
    g_variant_dict_insert(d, "ninf", "d", (gdouble)-INFINITY);
    g_variant_dict_insert(d, "nz", "d", -0.0);
    g_variant_dict_insert(d, "dbig", "d", 1e300);
    g_variant_dict_insert(d, "d2p63", "d", 9223372036854775808.0);
    g_variant_dict_insert(d, "d2p63m", "d", 9223372036854774784.0);
    g_variant_dict_insert(d, "status", "s", "Playing");
    g_variant_dict_insert(d, "loop", "s", "Track");
    g_variant_dict_insert(d, "shuffle", "b", TRUE);
    g_variant_dict_insert(d, "volume", "d", 0.5);
    g_variant_dict_insert(d, "b", "b", FALSE);
    g_variant_dict_insert(d, "arr", "^as", arr);
    g_variant_dict_insert_value(d, "earr", g_variant_new_strv(NULL, 0));
    g_variant_dict_insert_value(d, "ai", g_variant_new_parsed("[1, 2]"));
    g_variant_dict_insert_value(d, "tup", g_variant_new_parsed("(1, 'x')"));
    g_variant_dict_insert_value(d, "path", g_variant_new_object_path("/a/b"));
    g_variant_dict_insert_value(d, "boxed", g_variant_new_variant(g_variant_new_int64(9)));
    g_variant_dict_insert(d, "utf", "s", "h\xc3\xa9llo w\xc3\xb6rld");
    g_variant_dict_insert(d, "emo", "s", "\xf0\x9f\x98\x80\xf0\x9f\x91\x8dx");
    g_variant_dict_insert(d, "comb", "s", "e\xcc\x81x");
    g_variant_dict_insert(d, "ctrl", "s", "a\x01\x1f\x7f\"\\\n\t\b\f\r<>&'z");
    g_variant_dict_insert(d, "numstr", "s", "123");
    g_variant_dict_insert(d, "negstr", "s", "-5");
    g_variant_dict_insert(d, "uri", "s", "a%20b");
    g_variant_dict_insert(d, "uri0", "s", "a%00b");
    g_variant_dict_insert(d, "urix", "s", "%ff");
    g_variant_dict_insert(d, "urib", "s", "%zz");
    g_variant_dict_insert(d, "long", "s", long_str);
    g_free(long_str);
    return d;
}

/* ---- the table of rows ---- */

enum rkind { R_TBD, R_EQ, R_ERR, R_ANY, R_GLOB };

struct row {
    const gchar *name;
    const gchar *fmt;
    enum rkind kind;
    const gchar *expect; /* R_EQ: the output; R_ERR: a message glob */
    const gchar *bug;
};

#define X(n, f) {n, f, R_TBD, NULL, NULL}
#define R(n, f, e) {n, f, R_EQ, e, NULL}
#define E(n, f, g) {n, f, R_ERR, g, NULL}
#define A(n, f) {n, f, R_ANY, NULL, NULL}
#define G(n, f, g) {n, f, R_GLOB, g, NULL}
#define RB(n, f, e, b) {n, f, R_EQ, e, b}
#define EB(n, f, g, b) {n, f, R_ERR, g, b}
#define AB(n, f, b) {n, f, R_ANY, NULL, b}

/* ROWS-BEGIN */
static const struct row rows[] = {
    /* stray and lone braces */
    R("brace_lone_open", "{", "{"),
    R("brace_lone_close", "}", "}"),
    R("brace_close_pair", "}}", "}}"),
    R("brace_single_var", "{s}", "{s}"),
    E("brace_triple", "{{{s}}}", "unexpected \"{\", expected expression (position *)"),
    E("brace_quad", "{{{{s}}}}", "unexpected \"{\", expected expression (position *)"),
    R("brace_extra_close", "{{s}}}", "Song}"),
    R("brace_extra_close2", "{{s}}}}", "Song}}"),
    R("brace_space_between", "{ {s}}", "{ {s}}"),
    E("brace_missing_second_close", "{{s}", "expecting \"}}\" (position *)"),
    E("brace_close_space", "{{s} }", "expecting \"}}\" (position *)"),
    E("brace_empty", "{{}}", "unexpected \"}\", expected expression (position *)"),
    E("brace_space_only", "{{ }}", "unexpected \"}\", expected expression (position *)"),
    E("brace_only_open", "{{", "unexpected end of expression"),
    E("brace_open_space", "{{ ", "unexpected end of expression"),
    E("brace_text_open", "abc{{", "unexpected end of expression"),
    R("brace_adjacent", "{{s}}{{s}}", "SongSong"),
    R("brace_adjacent3", "{{s}}{{i}}{{u}}", "Song55"),
    R("brace_in_string", "{{ \"}}\" }}", "}}"),
    R("brace_open_in_string", "{{\"{{\"}}", "{{"),
    E("brace_nested_exprs", "{{ {{s}} }}", "unexpected \"{\", expected expression (position *)"),
    E("brace_closes_then_expr", "}}{{s}}{{", "unexpected end of expression"),
    R("brace_text_around", "x{{s}}y}}z", "xSongy}}z"),
    E("brace_unclosed_var", "{{s", "unexpected end of expression"),
    E("brace_unclosed_after_text", "text {{s", "unexpected end of expression"),
    E("brace_close_single_then_text", "{{s}x", "expecting \"}}\" (position *)"),
    /* strings and quotes */
    E("str_unterminated", "{{\"abc}}", "unexpected end of expression"),
    E("str_unterminated_empty", "{{\"}}", "unexpected end of expression"),
    E("str_only_quote", "{{\"", "unexpected end of expression"),
    R("str_empty", "{{\"\"}}", ""),
    E("str_two_adjacent", "{{\"a\" \"b\"}}", "expecting \"}}\" (position *)"),
    R("str_backslashes_literal", "{{\"a\\\\b\"}}", "a\\\\b"),
    E("str_plus_str", "{{\"a\"+\"b\"}}", "Got unsupported operand types for +: 's' and 's'"),
    E("str_plus_num", "{{\"a\"+1}}", "Got unsupported operand types for +: 's' and 'd'"),
    R("str_in_call", "{{uc(\"abc\")}}", "ABC"),
    R("str_spaces_kept", "{{\"  padded  \"}}", "  padded  "),
    E("str_then_ident", "{{\"a\"s}}", "expecting \"}}\" (position *)"),
    R("str_quote_in_text", "say \"hi\" {{s}}", "say \"hi\" Song"),
    E("str_unterminated_in_call", "{{lc(\"abc)}}", "unexpected end of expression"),
    R("str_in_parens", "{{(\"a\")}}", "a"),
    E("str_unary_minus", "{{-\"a\"}}", "Got unsupported operand type for unary -: 's'"),
    AB("str_invalid_utf8_literal", "{{\"\xff\"}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    AB("text_invalid_utf8_passthrough", "\xff{{s}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    R("str_with_newline", "{{\"a\nb\"}}", "a\nb"),
    /* numbers */
    R("num_int", "{{1}}", "1.0"),
    R("num_multi", "{{12345}}", "12345.0"),
    R("num_frac", "{{1.5}}", "1.5"),
    R("num_dot_end", "{{1.}}", "1.0"),
    R("num_dot_start", "{{.5}}", "0.5"),
    E("num_dot_only", "{{.}}", "invalid number: \".\" (position *)"),
    E("num_two_dots", "{{1.2.3}}", "invalid number: \"1.2.3\" (position *)"),
    E("num_dots_adjacent", "{{1..2}}", "invalid number: \"1..2\" (position *)"),
    R("num_leading_zeros", "{{007}}", "7.0"),
    E("num_exponent", "{{1e5}}", "expecting \"}}\" (position *)"),
    E("num_space_between", "{{1 2}}", "expecting \"}}\" (position *)"),
    E("num_letter_after", "{{1x}}", "expecting \"}}\" (position *)"),
    E("num_digit_then_ident", "{{9a}}", "expecting \"}}\" (position *)"),
    R("num_two_digits", "{{12}}", "12.0"),
    E("num_at_len_minus_2_unterminated", "{{123", "expecting \"}}\" (position *)"),
    E("num_at_len_minus_2_two", "{{12", "unexpected end of expression"),
    R("num_then_text_digits", "{{1}}12", "1.012"),
    R("num_neg_dot", "{{-.5}}", "-0.5"),
    E("num_plus_dot_only", "{{+.}}", "invalid number: \".\" (position *)"),
    E("num_dot_plus_dot", "{{.+.}}", "invalid number: \".\" (position *)"),
    R("num_zero", "{{0}}", "0.0"),
    R("num_neg_zero", "{{-0}}", "-0.0"),
    R("num_zero_times_neg", "{{0*-1}}", "-0.0"),
    R("num_zero_frac", "{{0.0}}", "0.0"),
    R("num_big_literal", "{{100000000000000000000}}", "1e+20"),
    E("num_dot_in_ident", "{{a.b}}", "expecting \"}}\" (position *)"),
    E("num_hex_literal", "{{0x10}}", "expecting \"}}\" (position *)"),
    E("num_comma", "{{1,5}}", "expecting \"}}\" (position *)"),
    R("num_trailing_space", "{{ 7 }}", "7.0"),
    E("num_tab", "{{\t7}}", "unexpected \"\t\", expected expression (position *)"),
    R("num_negative_spaces", "{{ - 7 }}", "-7.0"),
    /* arithmetic on literals */
    R("ar_prec_mul_add", "{{1+2*3}}", "7.0"),
    R("ar_prec_add_mul", "{{1*2+3}}", "5.0"),
    R("ar_left_assoc_sub", "{{1-2-3}}", "-4.0"),
    R("ar_left_assoc_div", "{{8/4/2}}", "1.0"),
    R("ar_mul_div_chain", "{{2*3/4}}", "1.5"),
    R("ar_double_unary_minus", "{{--1}}", "1.0"),
    R("ar_alternating_unary", "{{+-+-1}}", "1.0"),
    R("ar_minus_unary", "{{1--1}}", "2.0"),
    R("ar_plus_unary", "{{1+-1}}", "0.0"),
    R("ar_mul_unary", "{{2*-3}}", "-6.0"),
    R("ar_div_unary", "{{2/-4}}", "-0.5"),
    R("ar_space_after_unary", "{{- 1}}", "-1.0"),
    R("ar_unary_paren_mul", "{{ - ( 1 + 2 ) * 3 }}", "-9.0"),
    R("ar_deep_parens", "{{(((1)))}}", "1.0"),
    E("ar_paren_juxtaposed", "{{(1)(2)}}", "expecting \"}}\" (position *)"),
    E("ar_empty_parens", "{{()}}", "unexpected \")\", expected expression (position *)"),
    E("ar_open_paren_only", "{{(}}", "unexpected \"}\", expected expression (position *)"),
    E("ar_close_paren_only", "{{)}}", "unexpected \")\", expected expression (position *)"),
    E("ar_unbalanced_close", "{{1)}}", "expecting \"}}\" (position *)"),
    E("ar_double_close", "{{(1))}}", "expecting \"}}\" (position *)"),
    E("ar_trailing_plus", "{{1 +}}", "unexpected \"}\", expected expression (position *)"),
    E("ar_plus_plus", "{{+ +}}", "unexpected \"}\", expected expression (position *)"),
    R("ar_binary_then_unary_plus", "{{1 + + 2}}", "3.0"),
    E("ar_double_star", "{{1 ** 2}}", "unexpected \"*\", expected expression (position *)"),
    E("ar_leading_star", "{{*1}}", "unexpected \"*\", expected expression (position *)"),
    E("ar_leading_slash", "{{/1}}", "unexpected \"/\", expected expression (position *)"),
    E("ar_double_slash", "{{1 // 2}}", "unexpected \"/\", expected expression (position *)"),
    E("ar_div_zero_literal", "{{1/0}}", "Divide by zero error"),
    E("ar_div_zero_double", "{{1/0.0}}", "Divide by zero error"),
    E("ar_zero_div_zero", "{{0/0}}", "Divide by zero error"),
    E("ar_div_zero_expr", "{{1/(1-1)}}", "Divide by zero error"),
    E("ar_div_neg_zero", "{{1/-0}}", "Divide by zero error"),
    R("ar_mixed_prec_long", "{{1+2*3-4/2+5*6-7}}", "28.0"),
    R("ar_paren_in_mul_chain", "{{2*(3+4)*5}}", "70.0"),
    E("ar_missing_operand_right_paren", "{{(1+)}}", "unexpected \")\", expected expression (position *)"),
    R("ar_space_everywhere", "{{ ( 1 + ( 2 * 3 ) ) / 7 }}", "1.0"),
    R("ar_inf_literal_mul", "{{100000000000000000000*100000000000000000000}}", "1e+40"),
    /* arithmetic with int64 / uint64 / double variables */
    R("i64_max_plus_one", "{{big+1}}", "9.2233720368547758e+18"),
    E("i64_max_plus_i64", "{{big+i}}", "Numeric overflow detected"),
    E("i64_min_minus_one_var", "{{min-i}}", "Numeric overflow detected"),
    E("i64_min_plus_min", "{{min+min}}", "Numeric overflow detected"),
    E("i64_min_times_m1", "{{min*m1}}", "Numeric overflow detected"),
    E("i64_min_div_m1", "{{min/m1}}", "Numeric overflow detected"),
    E("i64_neg_min", "{{-min}}", "Numeric overflow detected"),
    R("i64_neg_max", "{{-big}}", "-9223372036854775807"),
    E("i64_min_minus_max", "{{min-big}}", "Numeric overflow detected"),
    E("i64_max_minus_min", "{{big-min}}", "Numeric overflow detected"),
    R("i64_max_times_double", "{{big*2}}", "1.8446744073709552e+19"),
    E("i64_max_times_i64", "{{big*i}}", "Numeric overflow detected"),
    R("i64_max_div_i64", "{{big/i}}", "1844674407370955161"),
    R("i64_min_div_i64", "{{min/i}}", "-1844674407370955161"),
    E("i64_div_zero_i64", "{{i/zero}}", "Divide by zero error"),
    E("i64_zero_div_zero", "{{zero/zero}}", "Divide by zero error"),
    E("i64_div_double_zero", "{{i/0}}", "Divide by zero error"),
    R("i64_zero_times_min", "{{zero*min}}", "0"),
    R("i64_max_plus_double_zero", "{{big+0}}", "9.2233720368547758e+18"),
    R("i64_max_plus_zero", "{{big+zero}}", "9223372036854775807"),
    R("i64_neg_zero", "{{-zero}}", "0"),
    R("i64_neg_div_trunc", "{{neg/2*1}}", "-3.5"),
    R("i64_div_truncates_toward_zero", "{{neg/i}}", "-1"),
    R("i64_sub_neg", "{{i-neg}}", "12"),
    R("i64_mul_neg", "{{neg*neg}}", "49"),
    R("i64_unary_plus", "{{+min}}", "-9223372036854775808"),
    R("u64_max_plus_one", "{{umax+1}}", "1.8446744073709552e+19"),
    R("u64_max_plus_max", "{{umax+umax}}", "3.6893488147419103e+19"),
    R("u64_max_minus_max", "{{umax-umax}}", "0.0"),
    R("u64_max_times_max", "{{umax*umax}}", "3.4028236692093846e+38"),
    R("u64_max_div_u64", "{{umax/u}}", "3.6893488147419105e+18"),
    E("u64_div_zero_double", "{{u/0}}", "Divide by zero error"),
    E("u64_div_zero_i64", "{{u/zero}}", "Divide by zero error"),
    R("u64_neg_max", "{{-umax}}", "-1.8446744073709552e+19"),
    R("u64_neg_half", "{{-uhalf}}", "-9.2233720368547758e+18"),
    R("u64_neg_small", "{{-u}}", "-5"),
    R("u64_unary_plus_max", "{{+umax}}", "18446744073709551615"),
    R("u64_plus_i64", "{{umax+i}}", "1.8446744073709552e+19"),
    R("u64_plus_u64", "{{u+u}}", "10.0"),
    G("dbl_nan_plus_one", "{{nan+1}}", "*nan"),
    G("dbl_nan_times_zero", "{{nan*0}}", "*nan"),
    G("dbl_inf_minus_inf", "{{inf-inf}}", "*nan"),
    G("dbl_inf_times_zero", "{{inf*0}}", "*nan"),
    G("dbl_inf_div_inf", "{{inf/inf}}", "*nan"),
    R("dbl_one_div_inf", "{{1/inf}}", "0.0"),
    G("dbl_neg_nan", "{{-nan}}", "*nan"),
    R("dbl_neg_neg_zero", "{{-nz}}", "0.0"),
    R("dbl_negzero_plus_zero", "{{nz+0}}", "0.0"),
    R("dbl_negzero_div_one", "{{nz/1}}", "-0.0"),
    E("dbl_one_div_negzero", "{{1/nz}}", "Divide by zero error"),
    R("dbl_overflow_to_inf", "{{dbig*dbig}}", "inf"),
    R("dbl_neg_overflow_to_inf", "{{dbig*-dbig}}", "-inf"),
    G("dbl_div_nan", "{{1/nan}}", "*nan"),
    R("dbl_ninf_neg", "{{-ninf}}", "inf"),
    G("dbl_zero_times_inf_literal", "{{0*inf}}", "*nan"),
    E("type_str_plus_int", "{{s+1}}", "Got unsupported operand types for +: 's' and 'd'"),
    E("type_str_times", "{{s*2}}", "Got unsupported operand types for *: 's' and 'd'"),
    E("type_neg_str", "{{-s}}", "Got unsupported operand type for unary -: 's'"),
    E("type_pos_str", "{{+s}}", "Got unsupported operand type for unary +: 's'"),
    E("type_str_div_str", "{{s/s}}", "Got unsupported operand types for /: 's' and 's'"),
    E("type_missing_plus", "{{missing+1}}", "Got unsupported operand type for +: NULL"),
    E("type_plus_missing", "{{1+missing}}", "Got unsupported operand type for +: NULL"),
    E("type_missing_times", "{{missing*1}}", "Got unsupported operand types for *: 'NULL' and 'd'"),
    E("type_neg_missing", "{{-missing}}", "Got unsupported operand type for unary -: NULL"),
    E("type_pos_missing", "{{+missing}}", "Got unsupported operand type for unary +: 'NULL'"),
    E("type_missing_div", "{{missing/1}}", "Got unsupported operand types for /: 'NULL' and 'd'"),
    E("type_arr_plus", "{{arr+1}}", "Got unsupported operand types for +: 'as' and 'd'"),
    E("type_bool_plus", "{{b+1}}", "Got unsupported operand types for +: 'b' and 'd'"),
    E("type_tuple_times", "{{tup*2}}", "Got unsupported operand types for *: '(is)' and 'd'"),
    E("type_neg_bool", "{{-b}}", "Got unsupported operand type for unary -: 'b'"),
    E("type_pos_bool", "{{+b}}", "Got unsupported operand type for unary +: 'b'"),
    E("type_intarray_plus", "{{ai+1}}", "Got unsupported operand types for +: 'ai' and 'd'"),
    E("type_boxed_plus", "{{boxed+1}}", "Got unsupported operand types for +: 'v' and 'd'"),
    E("type_path_plus", "{{path+1}}", "Got unsupported operand types for +: 'o' and 'd'"),
    E("type_neg_arr", "{{-arr}}", "Got unsupported operand type for unary -: 'as'"),
    /* lc / uc */
    R("lc_basic", "{{lc(s)}}", "song"),
    R("uc_basic", "{{uc(s)}}", "SONG"),
    R("lc_utf8", "{{lc(utf)}}", "h\303\251llo w\303\266rld"),
    R("uc_utf8", "{{uc(utf)}}", "H\303\211LLO W\303\226RLD"),
    R("uc_sharp_s", "{{uc(\"\xc3\x9f\")}}", "SS"),
    R("lc_dotted_capital_i", "{{lc(\"\xc4\xb0\")}}", "i\314\207"),
    R("uc_emoji", "{{uc(emo)}}", "\360\237\230\200\360\237\221\215X"),
    R("lc_combining", "{{lc(comb)}}", "e\314\201x"),
    R("uc_combining", "{{uc(comb)}}", "E\314\201X"),
    R("lc_missing", "{{lc(missing)}}", ""),
    R("uc_int", "{{uc(i)}}", "5"),
    R("lc_array", "{{lc(arr)}}", "a, b"),
    R("uc_array", "{{uc(arr)}}", "A, B"),
    R("lc_double", "{{lc(d)}}", "2.5"),
    R("lc_nan", "{{lc(nan)}}", "nan"),
    R("uc_bool", "{{uc(shuffle)}}", "TRUE"),
    R("uc_tuple", "{{uc(tup)}}", "(1, 'X')"),
    E("lc_no_args", "{{lc()}}", "unexpected \")\", expected expression (position *)"),
    E("lc_two_args", "{{lc(s,s)}}", "function lc takes exactly one argument (got 2)"),
    R("lc_as_variable", "{{lc}}", ""),
    E("lc_wrong_case_name", "{{LC(s)}}", "unknown template function: LC"),
    E("lc_space_before_paren", "{{lc (s)}}", "expecting \"}}\" (position *)"),
    R("lc_nested_deep", "{{lc(lc(lc(uc(s))))}}", "song"),
    R("uc_object_path", "{{uc(path)}}", "/A/B"),
    R("lc_boxed_variant", "{{lc(boxed)}}", "<int64 9>"),
    /* json_escape / markup_escape */
    R("json_ctrl", "{{json_escape(ctrl)}}", "a\\u0001\\u001f\177\\\"\\\\\\n\\t\\b\\f\\r<>&'z"),
    R("json_utf8", "{{json_escape(utf)}}", "h\303\251llo w\303\266rld"),
    R("json_emoji", "{{json_escape(emo)}}", "\360\237\230\200\360\237\221\215x"),
    R("json_missing", "{{json_escape(missing)}}", ""),
    R("json_array", "{{json_escape(arr)}}", "a, b"),
    R("json_int", "{{json_escape(i)}}", "5"),
    R("json_empty", "{{json_escape(\"\")}}", ""),
    E("json_quote_only", "{{json_escape(\"\\\"\")}}", "expecting \")\" (position *)"),
    R("json_in_text_context", "{\"t\":\"{{json_escape(ctrl)}}\"}", "{\"t\":\"a\\u0001\\u001f\177\\\"\\\\\\n\\t\\b\\f\\r<>&'z\"}"),
    R("json_u2028", "{{json_escape(\"\xe2\x80\xa8\")}}", "\342\200\250"),
    R("markup_ctrl", "{{markup_escape(ctrl)}}", "a&#x1;&#x1f;&#x7f;&quot;\\\n\t&#x8;&#xc;\r&lt;&gt;&amp;&apos;z"),
    R("markup_utf8", "{{markup_escape(utf)}}", "h\303\251llo w\303\266rld"),
    R("markup_tags", "{{markup_escape(\"<a href='x'>&amp;</a>\")}}", "&lt;a href=&apos;x&apos;&gt;&amp;amp;&lt;/a&gt;"),
    R("markup_missing", "{{markup_escape(missing)}}", ""),
    R("markup_array", "{{markup_escape(arr)}}", "a, b"),
    R("markup_double", "{{markup_escape(d)}}", "2.5"),
    /* duration */
    R("dur_int", "{{duration(i)}}", "0:00"),
    R("dur_hour", "{{duration(dur)}}", "1:01:01"),
    R("dur_literal_double", "{{duration(3661000000)}}", "1:01:01"),
    R("dur_negative_literal", "{{duration(-3661000000)}}", "-1:01:01"),
    R("dur_min", "{{duration(min)}}", "-2562047788:00:54"),
    R("dur_max", "{{duration(big)}}", "2562047788:00:54"),
    E("dur_u64_max", "{{duration(umax)}}", "function duration got a value that is out of range"),
    E("dur_u64_half", "{{duration(uhalf)}}", "function duration got a value that is out of range"),
    R("dur_u64_small", "{{duration(u)}}", "0:00"),
    E("dur_nan", "{{duration(nan)}}", "function duration got a value that is out of range"),
    E("dur_inf", "{{duration(inf)}}", "function duration got a value that is out of range"),
    E("dur_neg_inf", "{{duration(ninf)}}", "function duration got a value that is out of range"),
    E("dur_2p63", "{{duration(d2p63)}}", "function duration got a value that is out of range"),
    R("dur_below_2p63", "{{duration(d2p63m)}}", "2562047788:00:54"),
    R("dur_neg_zero", "{{duration(nz)}}", "0:00"),
    R("dur_numeric_string", "{{duration(numstr)}}", "0:00"),
    E("dur_negative_string", "{{duration(negstr)}}", "function duration can only be called on track position values"),
    E("dur_empty_string", "{{duration(\"\")}}", "function duration can only be called on track position values"),
    E("dur_leading_space_string", "{{duration(\" 5\")}}", "function duration can only be called on track position values"),
    E("dur_trailing_space_string", "{{duration(\"5 \")}}", "function duration can only be called on track position values"),
    E("dur_hex_string", "{{duration(\"0x10\")}}", "function duration can only be called on track position values"),
    E("dur_exp_string", "{{duration(\"1e3\")}}", "function duration can only be called on track position values"),
    R("dur_plus_string", "{{duration(\"+5\")}}", "0:00"),
    E("dur_overflow_string", "{{duration(\"99999999999999999999\")}}", "function duration can only be called on track position values"),
    E("dur_text_string", "{{duration(s)}}", "function duration can only be called on track position values"),
    R("dur_missing", "{{duration(missing)}}", ""),
    E("dur_array", "{{duration(arr)}}", "function duration can only be called on track position values"),
    E("dur_bool", "{{duration(b)}}", "function duration can only be called on track position values"),
    R("dur_minus_one_us", "{{duration(-1)}}", "-0:00"),
    R("dur_59_999999", "{{duration(59999999)}}", "0:59"),
    R("dur_exact_hour", "{{duration(3600000000)}}", "1:00:00"),
    R("dur_100_days", "{{duration(8640000000000)}}", "2400:00:00"),
    E("dur_expression", "{{duration(position-position)}}", "Got unsupported operand type for -: NULL"),
    R("dur_sub_expression", "{{duration(dur-dur)}}", "0:00"),
    /* default */
    R("def_missing_string", "{{default(missing,\"x\")}}", "x"),
    R("def_present", "{{default(s,\"x\")}}", "Song"),
    R("def_empty_string", "{{default(estr,\"x\")}}", "x"),
    R("def_empty_array", "{{default(earr,\"x\")}}", "x"),
    R("def_array", "{{default(arr,\"x\")}}", "a, b"),
    R("def_zero_not_empty", "{{default(zero,\"x\")}}", "0"),
    R("def_both_missing", "{{default(missing,missing)}}", ""),
    RB("def_empty_then_missing", "{{default(estr,missing)}}", "", "BUG-F1: helperfn_default refs a NULL fallback and logs a GLib critical"),
    RB("def_empty_array_then_missing", "{{default(earr,missing)}}", "", "BUG-F1: helperfn_default refs a NULL fallback and logs a GLib critical"),
    R("def_present_then_missing", "{{default(s,missing)}}", "Song"),
    R("def_missing_then_number", "{{default(missing,5)}}", "5.0"),
    R("def_nested_missing", "{{default(default(missing,missing),\"z\")}}", "z"),
    R("def_empty_empty", "{{default(\"\",\"\")}}", ""),
    R("def_nested_fallback", "{{default(missing,default(missing,\"deep\"))}}", "deep"),
    R("def_lc_missing", "{{default(lc(missing),\"x\")}}", "x"),
    E("def_fallback_evaluated_eagerly", "{{default(s,1/0)}}", "Divide by zero error"),
    R("def_bool", "{{default(b,\"x\")}}", "false"),
    R("def_nan", "{{default(nan,\"x\")}}", "nan"),
    RB("def_empty_then_nested_missing", "{{default(estr,default(missing,missing))}}", "", "BUG-F1: helperfn_default refs a NULL fallback and logs a GLib critical"),
    E("def_one_arg", "{{default(s)}}", "function default takes exactly two arguments (got 1)"),
    E("def_three_args", "{{default(s,s,s)}}", "function default takes exactly two arguments (got 3)"),
    /* emoji */
    R("emoji_status", "{{emoji(status)}}", "\342\226\266\357\270\217"),
    R("emoji_loop", "{{emoji(loop)}}", "\360\237\224\202"),
    R("emoji_shuffle", "{{emoji(shuffle)}}", "\360\237\224\200"),
    R("emoji_volume", "{{emoji(volume)}}", "\360\237\224\211"),
    R("emoji_other_variable", "{{emoji(s)}}", "Song"),
    E("emoji_string_literal", "{{emoji(\"x\")}}", "the emoji function can only be called with a variable"),
    E("emoji_function_arg", "{{emoji(lc(status))}}", "the emoji function can only be called with a variable"),
    R("emoji_missing", "{{emoji(missing)}}", ""),
    E("emoji_number_literal", "{{emoji(1)}}", "the emoji function can only be called with a variable"),
    E("emoji_unary_arg", "{{emoji(-status)}}", "Got unsupported operand type for unary -: 's'"),
    E("emoji_infix_arg", "{{emoji(status+0)}}", "Got unsupported operand types for +: 's' and 'd'"),
    R("emoji_paren_variable", "{{emoji((status))}}", "\342\226\266\357\270\217"),
    R("emoji_int_variable", "{{emoji(i)}}", "5"),
    E("emoji_two_args", "{{emoji(status,status)}}", "function emoji takes exactly one argument (got 2)"),
    E("emoji_no_args", "{{emoji()}}", "unexpected \")\", expected expression (position *)"),
    R("emoji_nested_in_uc", "{{uc(emoji(status))}}", "\342\226\266\357\270\217"),
    E("emoji_missing_function_arg", "{{emoji(lc(missing))}}", "the emoji function can only be called with a variable"),
    /* trunc */
    R("trunc_basic", "{{trunc(s, 2)}}", "So\342\200\246"),
    R("trunc_zero", "{{trunc(s, 0)}}", "\342\200\246"),
    R("trunc_exact", "{{trunc(s, 4)}}", "Song"),
    R("trunc_larger", "{{trunc(s, 100)}}", "Song"),
    E("trunc_negative", "{{trunc(s, -1)}}", "function trunc's length parameter cannot be negative"),
    E("trunc_nan", "{{trunc(s, nan)}}", "function trunc's length parameter cannot be negative"),
    R("trunc_inf", "{{trunc(s, inf)}}", "Song"),
    E("trunc_neg_inf", "{{trunc(s, ninf)}}", "function trunc's length parameter cannot be negative"),
    R("trunc_neg_zero", "{{trunc(s, nz)}}", "\342\200\246"),
    R("trunc_fraction", "{{trunc(s, 2.9)}}", "So\342\200\246"),
    R("trunc_half", "{{trunc(s, 0.5)}}", "\342\200\246"),
    R("trunc_i64_max", "{{trunc(s, big)}}", "Song"),
    R("trunc_u64_max", "{{trunc(s, umax)}}", "Song"),
    E("trunc_i64_min", "{{trunc(s, min)}}", "function trunc's length parameter cannot be negative"),
    E("trunc_string_length", "{{trunc(s, \"2\")}}", "function trunc's length parameter must be a number"),
    R("trunc_missing_length", "{{trunc(s, missing)}}", ""),
    R("trunc_missing_value", "{{trunc(missing, 2)}}", ""),
    R("trunc_utf8", "{{trunc(utf, 3)}}", "h\303\251l\342\200\246"),
    R("trunc_emoji_one", "{{trunc(emo, 1)}}", "\360\237\230\200\342\200\246"),
    R("trunc_emoji_two", "{{trunc(emo, 2)}}", "\360\237\230\200\360\237\221\215\342\200\246"),
    R("trunc_combining_two", "{{trunc(comb, 2)}}", "e\314\201\342\200\246"),
    R("trunc_combining_one", "{{trunc(comb, 1)}}", "e\342\200\246"),
    R("trunc_array", "{{trunc(arr, 3)}}", "a, \342\200\246"),
    R("trunc_int_zero", "{{trunc(i, 0)}}", "\342\200\246"),
    R("trunc_empty_zero", "{{trunc(\"\", 0)}}", ""),
    R("trunc_ctrl", "{{trunc(ctrl, 3)}}", "a\001\037\342\200\246"),
    E("trunc_bool_length", "{{trunc(s, b)}}", "function trunc's length parameter must be a number"),
    E("trunc_array_length", "{{trunc(s, arr)}}", "function trunc's length parameter must be a number"),
    R("trunc_big_double_length", "{{trunc(s, dbig)}}", "Song"),
    R("trunc_expression_length", "{{trunc(s, 1+1)}}", "So\342\200\246"),
    R("trunc_nested", "{{trunc(trunc(s, 3), 2)}}", "So\342\200\246"),
    E("trunc_one_arg", "{{trunc(s)}}", "function trunc takes exactly two arguments (got 1)"),
    E("trunc_three_args", "{{trunc(s,1,2)}}", "function trunc takes exactly two arguments (got 3)"),
    /* round / int */
    R("round_up", "{{round(2.5)}}", "3"),
    R("round_neg_half", "{{round(-2.5)}}", "-3"),
    R("round_down", "{{round(2.4)}}", "2"),
    R("round_neg_down", "{{round(-2.4)}}", "-2"),
    R("round_half", "{{round(0.5)}}", "1"),
    R("round_neg_half_small", "{{round(-0.5)}}", "-1"),
    R("round_neg_zero", "{{round(nz)}}", "0"),
    E("round_nan", "{{round(nan)}}", "function round got a value that is out of range"),
    E("round_inf", "{{round(inf)}}", "function round got a value that is out of range"),
    E("round_neg_inf", "{{round(ninf)}}", "function round got a value that is out of range"),
    E("round_2p63", "{{round(d2p63)}}", "function round got a value that is out of range"),
    R("round_below_2p63", "{{round(d2p63m)}}", "9223372036854774784"),
    R("round_neg_2p63", "{{round(-9223372036854775808)}}", "-9223372036854775808"),
    R("round_i64", "{{round(i)}}", "5"),
    R("round_i64_min", "{{round(min)}}", "-9223372036854775808"),
    R("round_i64_max", "{{round(big)}}", "9223372036854775807"),
    R("round_u64", "{{round(u)}}", "5"),
    E("round_u64_max", "{{round(umax)}}", "function round got a value that is out of range"),
    E("round_u64_half", "{{round(uhalf)}}", "function round got a value that is out of range"),
    R("round_numeric_string", "{{round(numstr)}}", "123"),
    R("round_decimal_string", "{{round(\"2.5\")}}", "3"),
    E("round_text_string", "{{round(\"abc\")}}", "function round can only be called on numbers"),
    E("round_empty_string", "{{round(\"\")}}", "function round can only be called on numbers"),
    E("round_nan_string", "{{round(\"nan\")}}", "function round got a value that is out of range"),
    E("round_huge_exp_string", "{{round(\"1e400\")}}", "function round got a value that is out of range"),
    R("round_leading_space_string", "{{round(\" 5\")}}", "5"),
    E("round_trailing_space_string", "{{round(\"5 \")}}", "function round can only be called on numbers"),
    R("round_hex_string", "{{round(\"0x10\")}}", "16"),
    E("round_comma_string", "{{round(\"1,5\")}}", "function round can only be called on numbers"),
    R("round_missing", "{{round(missing)}}", ""),
    E("round_text", "{{round(s)}}", "function round can only be called on numbers"),
    E("round_array", "{{round(arr)}}", "function round can only be called on numbers"),
    E("round_bool", "{{round(b)}}", "function round can only be called on numbers"),
    R("round_just_below_half", "{{round(0.49999999999999994)}}", "0"),
    R("round_volume", "{{round(volume)}}", "1"),
    E("round_two_args", "{{round(1,2)}}", "function round takes exactly one argument (got 2)"),
    R("int_positive", "{{int(2.9)}}", "2"),
    R("int_negative", "{{int(-2.9)}}", "-2"),
    E("int_nan", "{{int(nan)}}", "function int got a value that is out of range"),
    R("int_i64", "{{int(i)}}", "5"),
    R("int_i64_max", "{{int(big)}}", "9223372036854775807"),
    E("int_u64_max", "{{int(umax)}}", "function int got a value that is out of range"),
    R("int_u64", "{{int(u)}}", "5"),
    R("int_string", "{{int(\"7.9\")}}", "7"),
    E("int_text_string", "{{int(\"abc\")}}", "function int can only be called on numbers"),
    R("int_below_2p63", "{{int(d2p63m)}}", "9223372036854774784"),
    E("int_2p63", "{{int(d2p63)}}", "function int got a value that is out of range"),
    E("int_huge_literal", "{{int(100000000000000000000)}}", "function int got a value that is out of range"),
    R("int_neg_zero", "{{int(nz)}}", "0"),
    R("int_neg_fraction", "{{int(-0.5)}}", "0"),
    R("int_missing", "{{int(missing)}}", ""),
    E("int_bool", "{{int(b)}}", "function int can only be called on numbers"),
    /* replace / join */
    R("replace_basic", "{{replace(s, \"o\", \"0\")}}", "S0ng"),
    R("replace_empty_from", "{{replace(s,\"\",\"x\")}}", "Song"),
    R("replace_to_empty", "{{replace(s,\"Song\",\"\")}}", ""),
    R("replace_grow", "{{replace(s,\"o\",\"oo\")}}", "Soong"),
    R("replace_no_match", "{{replace(s,\"xyz\",\"q\")}}", "Song"),
    R("replace_missing_value", "{{replace(missing,\"a\",\"b\")}}", ""),
    R("replace_missing_from", "{{replace(s,missing,\"b\")}}", "Song"),
    R("replace_missing_to", "{{replace(s,\"o\",missing)}}", "Sng"),
    R("replace_utf8", "{{replace(utf,\"\xc3\xa9\",\"e\")}}", "hello w\303\266rld"),
    R("replace_array", "{{replace(arr,\", \",\"/\")}}", "a/b"),
    R("replace_int", "{{replace(i,\"5\",\"five\")}}", "five"),
    R("replace_all_self", "{{replace(s,s,s)}}", "Song"),
    R("replace_overlap", "{{replace(\"aaa\",\"aa\",\"b\")}}", "ba"),
    R("replace_emoji", "{{replace(emo,\"\xf0\x9f\x91\x8d\",\"+\")}}", "\360\237\230\200+x"),
    R("replace_number_args", "{{replace(s,1,2)}}", "Song"),
    R("replace_remove_all", "{{replace(\"a\",\"a\",\"\")}}", ""),
    E("replace_two_args", "{{replace(s,\"S\")}}", "function replace takes exactly three arguments (got 2)"),
    R("replace_from_longer", "{{replace(\"a\",\"abc\",\"x\")}}", "a"),
    R("replace_result_contains_from", "{{replace(\"ab\",\"a\",\"aa\")}}", "aab"),
    AB("replace_split_utf8_bytes", "{{replace(emo,\"\xf0\",\"?\")}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    R("join_array", "{{join(arr,\"-\")}}", "a-b"),
    R("join_empty_sep", "{{join(arr,\"\")}}", "ab"),
    R("join_missing_sep", "{{join(arr,missing)}}", "ab"),
    R("join_empty_array", "{{join(earr,\",\")}}", ""),
    R("join_string", "{{join(s,\",\")}}", "Song"),
    R("join_missing_value", "{{join(missing,\",\")}}", ""),
    R("join_int_array", "{{join(ai,\",\")}}", "[1, 2]"),
    R("join_int", "{{join(i,\",\")}}", "5"),
    R("join_number_sep", "{{join(arr,1)}}", "a1.0b"),
    R("join_array_sep", "{{join(arr,arr)}}", "aa, bb"),
    R("join_utf8", "{{join(utf,\"-\")}}", "h\303\251llo w\303\266rld"),
    E("join_one_arg", "{{join(arr)}}", "function join takes exactly two arguments (got 1)"),
    R("join_tuple", "{{join(tup,\"-\")}}", "(1, 'x')"),
    /* pad */
    R("pad_right", "{{pad(s,8)}}|", "Song    |"),
    R("pad_left", "{{pad(s,-8)}}|", "    Song|"),
    R("pad_shorter", "{{pad(s,2)}}|", "Song|"),
    R("pad_zero", "{{pad(s,0)}}|", "Song|"),
    R("pad_neg_zero", "{{pad(s,nz)}}|", "Song|"),
    E("pad_nan", "{{pad(s,nan)}}", "function pad's width parameter is out of range"),
    E("pad_inf", "{{pad(s,inf)}}", "function pad's width parameter is out of range"),
    E("pad_neg_inf", "{{pad(s,ninf)}}", "function pad's width parameter is out of range"),
    E("pad_million", "{{pad(s,1000000)}}", "function pad's width parameter is out of range"),
    E("pad_neg_million", "{{pad(s,-1000000)}}", "function pad's width parameter is out of range"),
    E("pad_string_width", "{{pad(s,\"3\")}}", "function pad's width parameter must be a number"),
    R("pad_missing_value", "{{pad(missing,3)}}", ""),
    R("pad_missing_width", "{{pad(s,missing)}}", ""),
    R("pad_utf8", "{{pad(utf,12)}}|", "h\303\251llo w\303\266rld |"),
    R("pad_emoji", "{{pad(emo,5)}}|", "\360\237\230\200\360\237\221\215x  |"),
    R("pad_combining", "{{pad(comb,5)}}|", "e\314\201x  |"),
    R("pad_fraction", "{{pad(s,0.9)}}|", "Song|"),
    R("pad_neg_fraction", "{{pad(s,-0.9)}}|", "Song|"),
    E("pad_i64_max", "{{pad(s,big)}}", "function pad's width parameter is out of range"),
    E("pad_i64_min", "{{pad(s,min)}}", "function pad's width parameter is out of range"),
    E("pad_u64_max", "{{pad(s,umax)}}", "function pad's width parameter is out of range"),
    R("pad_u64", "{{pad(s,u)}}|", "Song |"),
    R("pad_array", "{{pad(arr,6)}}|", "a, b  |"),
    E("pad_one_arg", "{{pad(s)}}", "function pad takes exactly two arguments (got 1)"),
    E("pad_bool_width", "{{pad(s,b)}}", "function pad's width parameter must be a number"),
    R("pad_int_value", "{{pad(i,3)}}|", "5  |"),
    /* uri_decode */
    R("uri_space", "{{uri_decode(uri)}}", "a b"),
    R("uri_nul", "{{uri_decode(uri0)}}", "a%00b"),
    AB("uri_invalid_utf8", "{{uri_decode(urix)}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    R("uri_bad_hex", "{{uri_decode(urib)}}", "%zz"),
    R("uri_lone_percent", "{{uri_decode(\"%\")}}", "%"),
    R("uri_truncated_escape", "{{uri_decode(\"%4\")}}", "%4"),
    R("uri_two_escapes", "{{uri_decode(\"%41%42\")}}", "AB"),
    R("uri_utf8_escape", "{{uri_decode(\"%C3%A9\")}}", "\303\251"),
    AB("uri_truncated_utf8", "{{uri_decode(\"%E0%80\")}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    R("uri_plus_kept", "{{uri_decode(\"a+b\")}}", "a+b"),
    R("uri_file_url", "{{uri_decode(\"file:///a%20b\")}}", "file:///a b"),
    R("uri_missing", "{{uri_decode(missing)}}", ""),
    R("uri_int", "{{uri_decode(i)}}", "5"),
    R("uri_slash", "{{uri_decode(\"%2F\")}}", "/"),
    R("uri_newline", "{{uri_decode(\"%0a\")}}", "\n"),
    R("uri_percent", "{{uri_decode(\"%25\")}}", "%"),
    R("uri_double_encoded", "{{uri_decode(\"%2500\")}}", "%00"),
    R("uri_empty", "{{uri_decode(\"\")}}", ""),
    R("uri_array", "{{uri_decode(arr)}}", "a, b"),
    R("uri_json_escape_chain", "{{json_escape(uri_decode(\"%22%5C\"))}}", "\\\"\\\\"),
    R("uri_nul_double", "{{uri_decode(\"%00\")}}", "%00"),
    AB("uri_overlong_utf8", "{{uri_decode(\"%C0%80\")}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    AB("uri_surrogate_utf8", "{{uri_decode(\"%ED%A0%80\")}}", "BUG-F5: invalid UTF-8 reaches g_variant_new (\"s\", ...), which logs a GLib critical and drops the value"),
    /* unknown functions, call syntax */
    E("fn_unknown", "{{nosuch(1)}}", "unknown template function: nosuch"),
    E("fn_unknown_var_arg", "{{nosuch(s)}}", "unknown template function: nosuch"),
    E("fn_unknown_spaces", "{{ lc2(s) }}", "unknown template function: lc2"),
    E("fn_call_on_variable_name", "{{s(1)}}", "unknown template function: s"),
    E("fn_trailing_comma", "{{default(s,)}}", "unexpected \")\", expected expression (position *)"),
    E("fn_leading_comma", "{{default(,s)}}", "unexpected \",\", expected expression (position *)"),
    E("fn_only_comma", "{{default(,)}}", "unexpected \",\", expected expression (position *)"),
    E("fn_double_comma", "{{default(s,,s)}}", "unexpected \",\", expected expression (position *)"),
    E("fn_unclosed", "{{lc(s}}", "expecting \")\" (position *)"),
    E("fn_unclosed_eof", "{{lc(s", "unexpected end of expression"),
    E("fn_unclosed_comma_eof", "{{lc(s,", "unexpected end of expression"),
    E("fn_open_paren_eof", "{{lc(", "unexpected end of expression"),
    E("fn_extra_close", "{{lc(s))}}", "expecting \"}}\" (position *)"),
    R("fn_space_in_args", "{{default( s , \"x\" )}}", "Song"),
    R("fn_no_space_after_comma", "{{default(missing,\"x\")}}", "x"),
    E("fn_argument_two_exprs", "{{lc(s s)}}", "expecting \")\" (position *)"),
    R("fn_infix_in_args", "{{trunc(s, 1+1*2)}}", "Son\342\200\246"),
    R("fn_infix_after_call", "{{round(d)+1}}", "4.0"),
    R("fn_call_times_call", "{{round(d)*round(d)}}", "9"),
    R("fn_call_in_infix_chain", "{{1+round(d)*2-int(d)}}", "5.0"),
    E("fn_arg_error_propagates", "{{lc(1/0)}}", "Divide by zero error"),
    E("fn_arg_error_second", "{{trunc(s, 1/0)}}", "Divide by zero error"),
    E("fn_arg_error_first", "{{trunc(1/0, 2)}}", "Divide by zero error"),
    E("fn_arg_error_nested", "{{lc(uc(lc(1/0)))}}", "Divide by zero error"),
    E("fn_duration_wrong_type_nested", "{{lc(duration(s))}}", "function duration can only be called on track position values"),
    R("fn_colon_variable", "{{xesam:title}}", ""),
    E("fn_colon_start", "{{:s}}", "unexpected \":\", expected expression (position *)"),
    E("fn_colon_in_call_name", "{{a:b(1)}}", "unknown template function: a:b"),
    R("fn_underscore", "{{_x}}", ""),
    R("fn_digit_in_name", "{{a1}}", ""),
    E("fn_non_ascii_identifier", "{{\xc3\xa9}}", "unexpected \"\303\", expected expression (position *)"),
    E("fn_tab_in_expr", "{{\ts}}", "unexpected \"\t\", expected expression (position *)"),
    E("fn_newline_in_expr", "{{\ns}}", "unexpected \"\n\", expected expression (position *)"),
    E("fn_percent", "{{5%2}}", "expecting \"}}\" (position *)"),
    E("fn_at_sign", "{{@}}", "unexpected \"@\", expected expression (position *)"),
    E("fn_dollar", "{{$s}}", "unexpected \"$\", expected expression (position *)"),
    E("fn_semicolon", "{{s;}}", "expecting \"}}\" (position *)"),
    E("fn_bang", "{{!s}}", "unexpected \"!\", expected expression (position *)"),
    E("fn_brackets", "{{s[0]}}", "expecting \"}}\" (position *)"),
    E("fn_dot_member", "{{s.x}}", "expecting \"}}\" (position *)"),
    /* mixed text */
    R("mix_text_and_vars", "[{{s}}] {{lc(s)}} - {{i}}", "[Song] song - 5"),
    R("mix_percent_text", "100% {{s}} %s %d", "100% Song %s %d"),
    R("mix_backslash_text", "a\\nb {{s}}", "a\\nb Song"),
    R("mix_newline_text", "a\nb{{s}}\n", "a\nbSong\n"),
    R("mix_utf8_text", "\xe2\x99\xaa {{s}} \xf0\x9f\x8e\xb5", "\342\231\252 Song \360\237\216\265"),
    R("mix_empty_vars", "{{missing}}{{missing}}", ""),
    R("mix_var_types", "{{b}} {{d}} {{u}} {{arr}} {{tup}} {{ai}} {{path}} {{boxed}}", "false 2.5 5 a, b (1, 'x') [1, 2] /a/b <int64 9>"),
    R("mix_var_nan_inf", "{{nan}} {{inf}} {{ninf}} {{nz}}", "nan inf -inf -0.0"),
};
/* ROWS-END */

static void check_row(const struct row *r) {
    GVariantDict *ctx = make_ctx();
    GError *err = NULL;
    gchar *out = render(r->fmt, ctx, &err);
    switch (r->kind) {
    case R_TBD:
        g_assert_not_reached();
        break;
    case R_EQ:
        g_assert_no_error(err);
        g_assert_cmpstr(out, ==, r->expect);
        break;
    case R_ERR:
        g_assert_null(out);
        assert_formatter_error(err);
        g_assert_true(g_pattern_match_simple(r->expect, err->message));
        break;
    case R_ANY:
        g_assert_true((out != NULL) != (err != NULL));
        break;
    case R_GLOB:
        g_assert_no_error(err);
        g_assert_true(g_pattern_match_simple(r->expect, out));
        break;
    }
    g_clear_error(&err);
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void run_row(gconstpointer data) {
    const struct row *r = data;
    if (g_test_subprocess()) {
        check_row(r);
        return;
    }
    g_test_trap_subprocess(NULL, 0, trap_flags());
    if (r->bug == NULL) {
        g_test_trap_assert_passed();
        return;
    }
    finish_known_bug(r->bug, FALSE);
}

static void dump_rows(void) {
    for (gsize i = 0; i < G_N_ELEMENTS(rows); i++) {
        fflush(stdout);
        pid_t pid = fork();
        if (pid == 0) {
            GVariantDict *ctx = make_ctx();
            GError *err = NULL;
            gchar *out = render(rows[i].fmt, ctx, &err);
            gchar *esc = g_strescape(out != NULL ? out : err->message, NULL);
            printf("%zu\t%s\t%s\t%s\n", i, rows[i].name, out != NULL ? "OK" : "ERR", esc);
            fflush(stdout);
            _exit(0);
        }
        int status = 0;
        waitpid(pid, &status, 0);
        if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
            printf("%zu\t%s\tCRASH\tstatus=%d\n", i, rows[i].name, status);
        }
    }
}

/* ---- tokenizer: lengths ---- */

static void test_len_text_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *fmt = g_strnfill(1027, 'x');
    assert_renders(ctx, fmt, fmt);
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

static void test_len_text_1028_rejected(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *fmt = g_strnfill(1028, 'x');
    assert_render_fails(ctx, fmt, "*maximum format string length*");
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

static void test_len_huge_rejected(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *fmt = g_strnfill(1 << 20, '{');
    assert_render_fails(ctx, fmt, "*maximum format string length*");
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

/* One expression token filling the whole format (1027 bytes). */
static void test_len_variable_token_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *name = g_strnfill(1023, 'a');
    g_variant_dict_insert(ctx, name, "s", "found");
    gchar *fmt = g_strdup_printf("{{%s}}", name);
    g_assert_cmpint(strlen(fmt), ==, 1027);
    assert_renders(ctx, fmt, "found");
    g_free(fmt);
    g_free(name);
    g_variant_dict_unref(ctx);
}

static void test_len_variable_token_1028_rejected(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *name = g_strnfill(1024, 'a');
    gchar *fmt = g_strdup_printf("{{%s}}", name);
    g_assert_cmpint(strlen(fmt), ==, 1028);
    assert_render_fails(ctx, fmt, "*maximum format string length*");
    g_free(fmt);
    g_free(name);
    g_variant_dict_unref(ctx);
}

static void test_len_string_literal_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *body = g_strnfill(1021, 'q');
    gchar *fmt = g_strdup_printf("{{\"%s\"}}", body);
    g_assert_cmpint(strlen(fmt), ==, 1027);
    assert_renders(ctx, fmt, body);
    g_free(fmt);
    g_free(body);
    g_variant_dict_unref(ctx);
}

static void test_len_string_literal_unterminated_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *body = g_strnfill(1024, 'q');
    gchar *fmt = g_strdup_printf("{{\"%s", body);
    g_assert_cmpint(strlen(fmt), ==, 1027);
    assert_render_fails(ctx, fmt, "unexpected end of expression");
    g_free(fmt);
    g_free(body);
    g_variant_dict_unref(ctx);
}

static void test_len_unterminated_identifier_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *body = g_strnfill(1025, 'a');
    gchar *fmt = g_strdup_printf("{{%s", body);
    GError *err = NULL;
    gchar *out = render(fmt, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_free(fmt);
    g_free(body);
    g_variant_dict_unref(ctx);
}

static void test_len_number_token_1021_digits(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *digits = g_strnfill(1021, '1');
    gchar *fmt = g_strdup_printf("{{%s}}", digits);
    g_assert_cmpint(strlen(fmt), ==, 1025);
    GError *err = NULL;
    gchar *out = render(fmt, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(out, ==, "inf");
    g_free(out);
    g_free(fmt);
    g_free(digits);
    g_variant_dict_unref(ctx);
}

static void test_len_number_token_unterminated(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *digits = g_strnfill(1025, '1');
    gchar *fmt = g_strdup_printf("{{%s", digits);
    GError *err = NULL;
    gchar *out = render(fmt, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_free(fmt);
    g_free(digits);
    g_variant_dict_unref(ctx);
}

static void test_len_text_then_expr_1027(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "s", "s", "S");
    gchar *text = g_strnfill(1022, 't');
    gchar *fmt = g_strdup_printf("%s{{s}}", text);
    g_assert_cmpint(strlen(fmt), ==, 1027);
    gchar *expected = g_strdup_printf("%sS", text);
    assert_renders(ctx, fmt, expected);
    g_free(expected);
    g_free(fmt);
    g_free(text);
    g_variant_dict_unref(ctx);
}

static void test_len_many_tokens(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "s", "s", "S");
    GString *fmt = g_string_new("");
    GString *expected = g_string_new("");
    for (int i = 0; i < 205; i++) {
        g_string_append(fmt, "{{s}}");
        g_string_append(expected, "S");
    }
    g_assert_cmpint(fmt->len, ==, 1025);
    assert_renders(ctx, fmt->str, expected->str);
    g_string_free(fmt, TRUE);
    g_string_free(expected, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_len_all_open_braces_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *fmt = g_strnfill(1027, '{');
    GError *err = NULL;
    gchar *out = render(fmt, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

static void test_len_all_close_braces_1027(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *fmt = g_strnfill(1027, '}');
    assert_renders(ctx, fmt, fmt);
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

static void test_len_utf8_text_1027_bytes(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("");
    while (fmt->len + 3 <= 1027) {
        g_string_append(fmt, "\xe2\x82\xac");
    }
    g_assert_cmpint(fmt->len, ==, 1026);
    g_string_append_c(fmt, 'x');
    assert_renders(ctx, fmt->str, fmt->str);
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_len_args_filling_format(void) {
    /* a call whose arguments fill the format up to 1027 bytes */
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{default(\"\"");
    while (fmt->len < 1027 - 6) {
        g_string_append(fmt, ",\"\"");
    }
    g_string_append(fmt, ")}}");
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

/* ---- tokenizer: nesting (stack depth) ---- */

static void test_nest_parens_max(void) {
    /* 511 levels is the deepest nesting that fits in 1027 bytes */
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 511; i++) {
        g_string_append_c(fmt, '(');
    }
    g_string_append_c(fmt, '7');
    for (int i = 0; i < 511; i++) {
        g_string_append_c(fmt, ')');
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, ==, 1027);
    assert_renders(ctx, fmt->str, "7.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_parens_unbalanced(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 510; i++) {
        g_string_append_c(fmt, '(');
    }
    g_string_append(fmt, "7}}");
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_parens_only_open_to_limit(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    while (fmt->len < 1027) {
        g_string_append_c(fmt, '(');
    }
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_unary_minus_1020(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 1020; i++) {
        g_string_append_c(fmt, '-');
    }
    g_string_append(fmt, "1}}");
    g_assert_cmpint(fmt->len, ==, 1025);
    assert_renders(ctx, fmt->str, "1.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_unary_minus_odd(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 1021; i++) {
        g_string_append_c(fmt, '-');
    }
    g_string_append(fmt, "1}}");
    assert_renders(ctx, fmt->str, "-1.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_unary_plus_1020(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 1020; i++) {
        g_string_append_c(fmt, '+');
    }
    g_string_append(fmt, "3}}");
    assert_renders(ctx, fmt->str, "3.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_unary_without_operand(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 1020; i++) {
        g_string_append_c(fmt, '-');
    }
    g_string_append(fmt, "}}");
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_unary_mixed_parens(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 300; i++) {
        g_string_append(fmt, "-(");
    }
    g_string_append_c(fmt, '2');
    for (int i = 0; i < 300; i++) {
        g_string_append_c(fmt, ')');
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "2.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_calls_250(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "s", "s", "MiXed");
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 250; i++) {
        g_string_append(fmt, i % 2 ? "uc(" : "lc(");
    }
    g_string_append_c(fmt, 's');
    for (int i = 0; i < 250; i++) {
        g_string_append_c(fmt, ')');
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "mixed");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_calls_with_extra_args(void) {
    /* default(default(default(...,"a"),"a"),"a") */
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 70; i++) {
        g_string_append(fmt, "default(");
    }
    g_string_append(fmt, "missing");
    for (int i = 0; i < 70; i++) {
        g_string_append(fmt, ",\"a\")");
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "a");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_long_add_chain(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{1");
    for (int i = 0; i < 500; i++) {
        g_string_append(fmt, "+1");
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "501.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_long_mul_chain(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{1");
    for (int i = 0; i < 500; i++) {
        g_string_append(fmt, "*1");
    }
    g_string_append(fmt, "}}");
    assert_renders(ctx, fmt->str, "1.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_long_alternating_chain(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{0");
    for (int i = 0; i < 160; i++) {
        g_string_append(fmt, "+2*3-1");
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "800.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_right_deep_parens_chain(void) {
    GVariantDict *ctx = empty_ctx();
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 250; i++) {
        g_string_append(fmt, "1+(");
    }
    g_string_append_c(fmt, '0');
    for (int i = 0; i < 250; i++) {
        g_string_append_c(fmt, ')');
    }
    g_string_append(fmt, "}}");
    g_assert_cmpint(fmt->len, <=, 1027);
    assert_renders(ctx, fmt->str, "250.0");
    g_string_free(fmt, TRUE);
    g_variant_dict_unref(ctx);
}

static void test_nest_contains_key_deep(void) {
    GString *fmt = g_string_new("{{");
    for (int i = 0; i < 250; i++) {
        g_string_append(fmt, "lc(");
    }
    g_string_append(fmt, "deepkey");
    for (int i = 0; i < 250; i++) {
        g_string_append_c(fmt, ')');
    }
    g_string_append(fmt, "}}");
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt->str, &err);
    g_assert_no_error(err);
    g_assert_true(playerctl_formatter_contains_key(f, "deepkey"));
    g_assert_false(playerctl_formatter_contains_key(f, "other"));
    playerctl_formatter_destroy(f);
    g_string_free(fmt, TRUE);
}

/* ---- argument counts ---- */

static GString *call_with_n_args(const gchar *name, int n, const gchar *arg) {
    GString *fmt = g_string_new("{{");
    g_string_append_printf(fmt, "%s(", name);
    for (int i = 0; i < n; i++) {
        g_string_append_printf(fmt, "%s%s", i ? "," : "", arg);
    }
    g_string_append(fmt, ")}}");
    return fmt;
}

static void test_args_32_accepted_by_parser(void) {
    GString *fmt = call_with_n_args("nosuch", 32, "1");
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt->str, &err);
    g_assert_no_error(err);
    g_assert_nonnull(f);
    GVariantDict *ctx = empty_ctx();
    gchar *out = playerctl_formatter_expand_format(f, ctx, &err);
    g_assert_null(out);
    g_assert_true(g_pattern_match_simple("unknown template function: nosuch", err->message));
    g_clear_error(&err);
    g_variant_dict_unref(ctx);
    playerctl_formatter_destroy(f);
    g_string_free(fmt, TRUE);
}

static void test_args_32_to_real_function(void) {
    GString *fmt = call_with_n_args("default", 32, "1");
    GVariantDict *ctx = empty_ctx();
    assert_render_fails(ctx, fmt->str, "function default takes exactly two arguments (got 32)");
    g_variant_dict_unref(ctx);
    g_string_free(fmt, TRUE);
}

static void test_args_33_rejected(void) {
    GString *fmt = call_with_n_args("default", 33, "1");
    GVariantDict *ctx = empty_ctx();
    assert_render_fails(ctx, fmt->str, "maximum args of 32 exceeded");
    g_variant_dict_unref(ctx);
    g_string_free(fmt, TRUE);
}

static void test_args_100_rejected(void) {
    GString *fmt = call_with_n_args("lc", 100, "s");
    GVariantDict *ctx = empty_ctx();
    assert_render_fails(ctx, fmt->str, "maximum args of 32 exceeded");
    g_variant_dict_unref(ctx);
    g_string_free(fmt, TRUE);
}

static void test_args_33_unterminated(void) {
    GString *fmt = g_string_new("{{f(1");
    for (int i = 0; i < 40; i++) {
        g_string_append(fmt, ",1");
    }
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_variant_dict_unref(ctx);
    g_string_free(fmt, TRUE);
}

static void test_args_33rd_is_malformed(void) {
    /* The 33rd argument fails to parse while the count limit is also hit:
     * the argument error is dropped without being freed (leak). Only the
     * result (an error) is asserted. */
    GString *fmt = g_string_new("{{f(1");
    for (int i = 0; i < 31; i++) {
        g_string_append(fmt, ",1");
    }
    g_string_append(fmt, ",@)}}");
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    gchar *out = render(fmt->str, ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_clear_error(&err);
    g_variant_dict_unref(ctx);
    g_string_free(fmt, TRUE);
}

static void test_args_33rd_malformed_leak_loop(void) {
    /* repeated so that a leak is unmistakable under a leak checker */
    for (int i = 0; i < 50; i++) {
        test_args_33rd_is_malformed();
    }
}

static gboolean is_infix_fn(const struct template_function *fn) {
    return fn->func == infixfn_add || fn->func == infixfn_sub || fn->func == infixfn_mul ||
           fn->func == infixfn_div;
}

static void test_args_every_function_every_count(void) {
    GVariantDict *ctx = make_ctx();
    for (gsize f = 0; f < G_N_ELEMENTS(template_functions); f++) {
        const struct template_function *fn = &template_functions[f];
        if (is_infix_fn(fn)) {
            continue; /* the parser cannot spell an infix as a call */
        }
        for (int n = 1; n <= MAX_ARGS; n++) {
            GString *fmt = call_with_n_args(fn->name, n, "s");
            GError *err = NULL;
            gchar *out = render(fmt->str, ctx, &err);
            if (n >= fn->min_args && n <= fn->max_args) {
                if (out == NULL) {
                    /* a type error is fine, a count error is not */
                    g_assert_nonnull(err);
                    g_assert_false(g_pattern_match_simple("*takes*argument*", err->message));
                }
            } else {
                g_assert_null(out);
                g_assert_nonnull(err);
                g_assert_true(g_pattern_match_simple("function * takes*argument*(got *)", err->message));
            }
            g_clear_error(&err);
            g_free(out);
            g_string_free(fmt, TRUE);
        }
    }
    g_variant_dict_unref(ctx);
}

static void test_args_zero_rejected_everywhere(void) {
    GVariantDict *ctx = make_ctx();
    for (gsize f = 0; f < G_N_ELEMENTS(template_functions); f++) {
        if (is_infix_fn(&template_functions[f])) {
            continue;
        }
        gchar *fmt = g_strdup_printf("{{%s()}}", template_functions[f].name);
        GError *err = NULL;
        gchar *out = render(fmt, ctx, &err);
        g_assert_null(out);
        assert_formatter_error(err);
        g_clear_error(&err);
        g_free(fmt);
    }
    g_variant_dict_unref(ctx);
}

static void test_check_argument_count_messages(void) {
    for (gsize f = 0; f < G_N_ELEMENTS(template_functions); f++) {
        const struct template_function *fn = &template_functions[f];
        for (int n = 0; n <= MAX_ARGS + 1; n++) {
            GError *err = NULL;
            gboolean ok = check_argument_count(fn, n, &err);
            if (n >= fn->min_args && n <= fn->max_args) {
                g_assert_true(ok);
                g_assert_no_error(err);
            } else {
                g_assert_false(ok);
                assert_formatter_error(err);
                gchar *got = g_strdup_printf("*(got %d)", n);
                g_assert_true(g_pattern_match_simple(got, err->message));
                g_free(got);
                g_assert_true(g_utf8_validate(err->message, -1, NULL));
                g_clear_error(&err);
            }
        }
    }
}

static void test_check_argument_count_null_error(void) {
    /* the error pointer is optional in GLib convention */
    g_assert_false(check_argument_count(&template_functions[0], 7, NULL));
    g_assert_true(check_argument_count(&template_functions[0], 1, NULL));
}

static void test_template_table_consistent(void) {
    g_assert_cmpint(G_N_ELEMENTS(template_functions), ==, TEMPLATE_FUNCTION_COUNT);
    for (gsize i = 0; i < G_N_ELEMENTS(template_functions); i++) {
        g_assert_nonnull(template_functions[i].name);
        g_assert_nonnull(template_functions[i].func);
        g_assert_cmpint(template_functions[i].min_args, >=, 1);
        g_assert_cmpint(template_functions[i].min_args, <=, template_functions[i].max_args);
        g_assert_cmpint(template_functions[i].max_args, <=, MAX_ARGS);
        /* the count message indexes a table of four number words */
        g_assert_cmpint(template_functions[i].min_args, <=, 3);
        for (gsize j = i + 1; j < G_N_ELEMENTS(template_functions); j++) {
            g_assert_cmpstr(template_functions[i].name, !=, template_functions[j].name);
        }
    }
}

static void test_infix_call_spelling(void) {
    /* "+" is a table entry; the tokenizer has no syntax for calling it */
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    gchar *out = render("{{+(1,2)}}", ctx, &err);
    g_assert_true((out != NULL) != (err != NULL));
    g_clear_error(&err);
    g_free(out);
    g_variant_dict_unref(ctx);
}

/* ---- NULL arguments and API misuse ---- */

static void test_new_null_format(void) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(NULL, &err);
    g_assert_no_error(err);
    g_assert_nonnull(f);
    GVariantDict *ctx = empty_ctx();
    gchar *out = playerctl_formatter_expand_format(f, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(out, ==, "");
    g_free(out);
    g_variant_dict_unref(ctx);
    playerctl_formatter_destroy(f);
}

static void test_new_empty_format(void) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new("", &err);
    g_assert_no_error(err);
    g_assert_nonnull(f);
    GVariantDict *ctx = empty_ctx();
    gchar *out = playerctl_formatter_expand_format(f, ctx, &err);
    g_assert_cmpstr(out, ==, "");
    g_free(out);
    g_variant_dict_unref(ctx);
    playerctl_formatter_destroy(f);
}

static void test_new_null_error_pointer(void) {
    /* the GError out parameter may be NULL */
    PlayerctlFormatter *f = playerctl_formatter_new("{{", NULL);
    g_assert_null(f);
    f = playerctl_formatter_new("ok", NULL);
    g_assert_nonnull(f);
    GVariantDict *ctx = empty_ctx();
    gchar *out = playerctl_formatter_expand_format(f, ctx, NULL);
    g_assert_cmpstr(out, ==, "ok");
    g_free(out);
    playerctl_formatter_destroy(f);
    f = playerctl_formatter_new("{{1/0}}", NULL);
    g_assert_nonnull(f);
    out = playerctl_formatter_expand_format(f, ctx, NULL);
    g_assert_null(out);
    playerctl_formatter_destroy(f);
    g_variant_dict_unref(ctx);
}

static void test_new_null_error_pointer_arg_count(void) {
    GVariantDict *ctx = empty_ctx();
    PlayerctlFormatter *f = playerctl_formatter_new("{{lc(1,2)}}", NULL);
    g_assert_nonnull(f);
    g_assert_null(playerctl_formatter_expand_format(f, ctx, NULL));
    playerctl_formatter_destroy(f);
    g_variant_dict_unref(ctx);
}

static void test_destroy_null(void) {
    playerctl_formatter_destroy(NULL);
}

static void test_expand_null_formatter(void) {
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    /* expected: a NULL result without a crash (g_return_val_if_fail) */
    g_assert_null(playerctl_formatter_expand_format(NULL, ctx, &err));
    g_variant_dict_unref(ctx);
}

static void test_contains_key_null_formatter(void) {
    g_assert_false(playerctl_formatter_contains_key(NULL, "x"));
}

static void test_contains_key_null_key(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("{{a}}{{lc(b)}}", NULL);
    g_assert_false(playerctl_formatter_contains_key(f, NULL));
    g_assert_false(playerctl_formatter_contains_key(f, ""));
    playerctl_formatter_destroy(f);
}

static void test_contains_key_empty_format(void) {
    PlayerctlFormatter *f = playerctl_formatter_new(NULL, NULL);
    g_assert_false(playerctl_formatter_contains_key(f, "a"));
    playerctl_formatter_destroy(f);
    f = playerctl_formatter_new("", NULL);
    g_assert_false(playerctl_formatter_contains_key(f, ""));
    playerctl_formatter_destroy(f);
}

static void test_contains_key_branches(void) {
    PlayerctlFormatter *f = playerctl_formatter_new(
        "{{ \"lit\" }}{{ 1 + n }}{{ default(x, trunc(y, 3)) }}{{ -(z) }}", NULL);
    g_assert_nonnull(f);
    g_assert_true(playerctl_formatter_contains_key(f, "n"));
    g_assert_true(playerctl_formatter_contains_key(f, "x"));
    g_assert_true(playerctl_formatter_contains_key(f, "y"));
    g_assert_true(playerctl_formatter_contains_key(f, "z"));
    g_assert_false(playerctl_formatter_contains_key(f, "lit"));
    g_assert_false(playerctl_formatter_contains_key(f, "default"));
    g_assert_false(playerctl_formatter_contains_key(f, "trunc"));
    g_assert_false(playerctl_formatter_contains_key(f, "+"));
    g_assert_false(playerctl_formatter_contains_key(f, "3"));
    playerctl_formatter_destroy(f);
}

static void test_contains_key_unknown_function(void) {
    /* accepted at parse time, so contains_key still finds the key */
    PlayerctlFormatter *f = playerctl_formatter_new("{{nosuch(k)}}", NULL);
    g_assert_nonnull(f);
    g_assert_true(playerctl_formatter_contains_key(f, "k"));
    g_assert_false(playerctl_formatter_contains_key(f, "nosuch"));
    playerctl_formatter_destroy(f);
}

static void test_expand_text_only_with_null_context(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("plain text", NULL);
    gchar *out = playerctl_formatter_expand_format(f, NULL, NULL);
    g_assert_cmpstr(out, ==, "plain text");
    g_free(out);
    playerctl_formatter_destroy(f);
}

static void test_expand_literals_with_null_context(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("{{1+2}}{{\"x\"}}", NULL);
    gchar *out = playerctl_formatter_expand_format(f, NULL, NULL);
    g_assert_cmpstr(out, ==, "3.0x");
    g_free(out);
    playerctl_formatter_destroy(f);
}

static void test_expand_variable_with_null_context(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("{{s}}", NULL);
    GError *err = NULL;
    gchar *out = playerctl_formatter_expand_format(f, NULL, &err);
    /* expected: no crash and no GLib critical: an empty result or an error */
    g_assert_true(out != NULL || err != NULL);
    g_free(out);
    g_clear_error(&err);
    playerctl_formatter_destroy(f);
}

static void test_reuse_formatter_many_times(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("{{s}}|{{lc(s)}}|{{trunc(s,2)}}|{{i+1}}", NULL);
    for (int n = 0; n < 1000; n++) {
        GVariantDict *ctx = g_variant_dict_new(NULL);
        g_variant_dict_insert(ctx, "s", "s", "ABCD");
        g_variant_dict_insert(ctx, "i", "x", (gint64)n);
        gchar *out = playerctl_formatter_expand_format(f, ctx, NULL);
        gchar *expected = g_strdup_printf("ABCD|abcd|AB\xe2\x80\xa6|%d.0", n + 1);
        g_assert_cmpstr(out, ==, expected);
        g_free(expected);
        g_free(out);
        g_variant_dict_unref(ctx);
    }
    playerctl_formatter_destroy(f);
}

static void test_reuse_formatter_after_error(void) {
    PlayerctlFormatter *f = playerctl_formatter_new("{{100/d}}", NULL);
    GVariantDict *bad = g_variant_dict_new(NULL);
    g_variant_dict_insert(bad, "d", "d", 0.0);
    GVariantDict *good = g_variant_dict_new(NULL);
    g_variant_dict_insert(good, "d", "d", 4.0);
    for (int n = 0; n < 50; n++) {
        GError *err = NULL;
        g_assert_null(playerctl_formatter_expand_format(f, bad, &err));
        g_assert_nonnull(err);
        g_clear_error(&err);
        gchar *out = playerctl_formatter_expand_format(f, good, &err);
        g_assert_no_error(err);
        g_assert_cmpstr(out, ==, "25.0");
        g_free(out);
    }
    g_variant_dict_unref(bad);
    g_variant_dict_unref(good);
    playerctl_formatter_destroy(f);
}

/* ---- direct token API ---- */

static void test_token_create_destroy(void) {
    token_destroy(NULL);
    token_list_destroy(NULL);
    struct token *t = token_create(TOKEN_FUNCTION);
    g_assert_cmpint(t->type, ==, TOKEN_FUNCTION);
    g_assert_null(t->data);
    g_assert_null(t->args);
    t->data = g_strdup("f");
    struct token *c = token_create(TOKEN_NUMBER);
    c->numeric_data = 1.0;
    t->args = g_list_append(NULL, c);
    token_destroy(t);
}

static void test_tokenize_format_returns_tokens(void) {
    GError *err = NULL;
    GList *tokens = tokenize_format("a{{s}}b{{1+2}}c", &err);
    g_assert_no_error(err);
    g_assert_cmpint(g_list_length(tokens), ==, 5);
    struct token *t0 = tokens->data;
    g_assert_cmpint(t0->type, ==, TOKEN_STRING);
    g_assert_cmpstr(t0->data, ==, "a");
    struct token *t1 = g_list_nth_data(tokens, 1);
    g_assert_cmpint(t1->type, ==, TOKEN_VARIABLE);
    struct token *t3 = g_list_nth_data(tokens, 3);
    g_assert_cmpint(t3->type, ==, TOKEN_FUNCTION);
    g_assert_cmpstr(t3->data, ==, "+");
    g_assert_cmpint(g_list_length(t3->args), ==, 2);
    token_list_destroy(tokens);
}

static void test_tokenize_format_null(void) {
    GError *err = NULL;
    g_assert_null(tokenize_format(NULL, &err));
    g_assert_no_error(err);
}

static void test_tokenize_format_error(void) {
    GError *err = NULL;
    GList *tokens = tokenize_format("a{{s}}b{{(}}c", &err);
    g_assert_null(tokens);
    assert_formatter_error(err);
    g_clear_error(&err);
}

static void test_expand_token_types(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "x", (gint64)3);
    GError *err = NULL;

    struct token *num = token_create(TOKEN_NUMBER);
    num->numeric_data = -0.0;
    GVariant *r = expand_token(num, ctx, &err);
    g_assert_no_error(err);
    g_assert_true(g_variant_is_of_type(r, G_VARIANT_TYPE_DOUBLE));
    g_assert_true(signbit(g_variant_get_double(r)));
    g_variant_unref(r);
    token_destroy(num);

    struct token *str = token_create(TOKEN_STRING);
    str->data = g_strdup("lit");
    r = expand_token(str, ctx, &err);
    g_assert_cmpstr(g_variant_get_string(r, NULL), ==, "lit");
    g_variant_unref(r);
    token_destroy(str);

    struct token *var = token_create(TOKEN_VARIABLE);
    var->data = g_strdup("v");
    r = expand_token(var, ctx, &err);
    g_assert_cmpint(g_variant_get_int64(r), ==, 3);
    g_variant_unref(r);
    g_free(var->data);
    var->data = g_strdup("absent");
    r = expand_token(var, ctx, &err);
    g_assert_null(r);
    g_assert_no_error(err);
    token_destroy(var);
    g_variant_dict_unref(ctx);
}

static void test_expand_token_32_args(void) {
    GVariantDict *ctx = empty_ctx();
    struct token *fn = token_create(TOKEN_FUNCTION);
    fn->data = g_strdup("default");
    for (int i = 0; i < MAX_ARGS; i++) {
        struct token *a = token_create(TOKEN_NUMBER);
        fn->args = g_list_append(fn->args, a);
    }
    GError *err = NULL;
    GVariant *r = expand_token(fn, ctx, &err);
    g_assert_null(r);
    assert_formatter_error(err);
    g_assert_true(g_pattern_match_simple("*takes exactly two arguments (got 32)", err->message));
    g_clear_error(&err);
    token_destroy(fn);
    g_variant_dict_unref(ctx);
}

static void test_expand_token_arg_error_cleans_earlier_args(void) {
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    GList *tokens = tokenize_format("{{trunc(replace(\"a\",\"a\",\"b\"), 1/0)}}", &err);
    g_assert_no_error(err);
    g_assert_null(expand_format(tokens, ctx, &err));
    assert_formatter_error(err);
    g_clear_error(&err);
    token_list_destroy(tokens);
    g_variant_dict_unref(ctx);
}

static void test_expand_format_empty_list(void) {
    GVariantDict *ctx = empty_ctx();
    gchar *out = expand_format(NULL, ctx, NULL);
    g_assert_cmpstr(out, ==, "");
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void test_get_double_value_and_valid_types(void) {
    GVariant *i = g_variant_ref_sink(g_variant_new_int64(INT64_MIN));
    GVariant *u = g_variant_ref_sink(g_variant_new_uint64(UINT64_MAX));
    GVariant *d = g_variant_ref_sink(g_variant_new_double(-0.0));
    GVariant *s = g_variant_ref_sink(g_variant_new_string("1"));
    GVariant *b = g_variant_ref_sink(g_variant_new_boolean(TRUE));
    GVariant *y = g_variant_ref_sink(g_variant_new_byte(3));
    GVariant *i32 = g_variant_ref_sink(g_variant_new_int32(3));
    GVariant *u32 = g_variant_ref_sink(g_variant_new_uint32(3));
    g_assert_true(is_valid_numeric_type(i));
    g_assert_true(is_valid_numeric_type(u));
    g_assert_true(is_valid_numeric_type(d));
    g_assert_false(is_valid_numeric_type(s));
    g_assert_false(is_valid_numeric_type(b));
    g_assert_false(is_valid_numeric_type(y));
    g_assert_false(is_valid_numeric_type(i32));
    g_assert_false(is_valid_numeric_type(u32));
    g_assert_false(is_valid_numeric_type(NULL));
    g_assert_cmpfloat(get_double_value(i), ==, -9223372036854775808.0);
    g_assert_cmpfloat(get_double_value(u), ==, 18446744073709551616.0);
    g_assert_true(signbit(get_double_value(d)));
    g_variant_unref(i);
    g_variant_unref(u);
    g_variant_unref(d);
    g_variant_unref(s);
    g_variant_unref(b);
    g_variant_unref(y);
    g_variant_unref(i32);
    g_variant_unref(u32);
}

static void test_other_numeric_types_in_context(void) {
    /* int32/uint32/byte/int16 are not "valid numeric types": every helper
     * answers with a result or an error and never crashes */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "i32", "i", 3);
    g_variant_dict_insert(ctx, "u32", "u", 3u);
    g_variant_dict_insert(ctx, "by", "y", 3);
    g_variant_dict_insert(ctx, "i16", "n", 3);
    const gchar *names[] = {"i32", "u32", "by", "i16"};
    const gchar *ops[] = {"{{%s+1}}", "{{-%s}}", "{{%s*2}}", "{{%s/2}}", "{{+%s}}",
                          "{{round(%s)}}", "{{int(%s)}}", "{{trunc(\"x\",%s)}}",
                          "{{pad(\"x\",%s)}}", "{{duration(%s)}}", "{{lc(%s)}}", "{{default(%s,1)}}"};
    for (gsize k = 0; k < G_N_ELEMENTS(names); k++) {
        for (gsize o = 0; o < G_N_ELEMENTS(ops); o++) {
            gchar *fmt = g_strdup_printf(ops[o], names[k]);
            GError *err = NULL;
            gchar *out = render(fmt, ctx, &err);
            g_assert_true((out != NULL) != (err != NULL));
            g_clear_error(&err);
            g_free(out);
            g_free(fmt);
        }
    }
    assert_renders(ctx, "{{i32}} {{u32}} {{by}} {{i16}}", "3 3 0x03 3");
    g_variant_dict_unref(ctx);
}

/* ---- error messages ---- */

static void test_errors_are_utf8_for_ascii_input(void) {
    static const gchar *bad[] = {"{{", "{{@}}", "{{(}}", "{{1.2.3}}", "{{lc()}}", "{{1/0}}",
                                 "{{\"x}}", "{{f(1,}}", "{{nosuch(1)}}", "{{s+1}}"};
    GVariantDict *ctx = make_ctx();
    for (gsize i = 0; i < G_N_ELEMENTS(bad); i++) {
        GError *err = NULL;
        gchar *out = render(bad[i], ctx, &err);
        g_assert_null(out);
        assert_formatter_error(err);
        g_assert_true(g_utf8_validate(err->message, -1, NULL));
        g_clear_error(&err);
    }
    g_variant_dict_unref(ctx);
}

static void test_error_message_for_non_ascii_character_is_utf8(void) {
    /* the tokenizer formats the offending *byte* with %c, so a multi-byte
     * character produces an invalid UTF-8 message */
    GVariantDict *ctx = empty_ctx();
    GError *err = NULL;
    gchar *out = render("{{\xc3\xa9}}", ctx, &err);
    g_assert_null(out);
    assert_formatter_error(err);
    g_assert_true(g_utf8_validate(err->message, -1, NULL));
    g_clear_error(&err);
    g_variant_dict_unref(ctx);
}

static void test_error_positions_are_in_range(void) {
    GVariantDict *ctx = empty_ctx();
    const gchar *bad[] = {"{{ @", "{{ (1", "{{1.2.3}}", "{{s} }", "xx{{ @ }}"};
    for (gsize i = 0; i < G_N_ELEMENTS(bad); i++) {
        GError *err = NULL;
        g_assert_null(render(bad[i], ctx, &err));
        assert_formatter_error(err);
        const gchar *p = strstr(err->message, "position");
        if (p != NULL) {
            int pos = -1;
            g_assert_cmpint(sscanf(p, "position %d", &pos), ==, 1);
            g_assert_cmpint(pos, >=, 0);
            g_assert_cmpint(pos, <=, (int)strlen(bad[i]));
        }
        g_clear_error(&err);
    }
    g_variant_dict_unref(ctx);
}

static void test_error_domain_and_code_for_all_row_errors(void) {
    GVariantDict *ctx = make_ctx();
    gsize errors = 0;
    for (gsize i = 0; i < G_N_ELEMENTS(rows); i++) {
        if (rows[i].kind != R_ERR || rows[i].bug != NULL) {
            continue;
        }
        GError *err = NULL;
        gchar *out = render(rows[i].fmt, ctx, &err);
        g_assert_null(out);
        assert_formatter_error(err);
        g_assert_nonnull(err->message);
        g_assert_cmpint(strlen(err->message), >, 0);
        g_clear_error(&err);
        errors++;
    }
    g_assert_cmpint(errors, >, 100);
    g_variant_dict_unref(ctx);
}

/* ---- helpers: emoji with other values ---- */

static void emoji_for(const gchar *key, GVariant *value, const gchar *expected) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert_value(ctx, key, value);
    gchar *fmt = g_strdup_printf("{{emoji(%s)}}", key);
    assert_renders(ctx, fmt, expected);
    g_free(fmt);
    g_variant_dict_unref(ctx);
}

static void test_emoji_status_values(void) {
    emoji_for("status", g_variant_new_string("Playing"), "\xe2\x96\xb6\xef\xb8\x8f");
    emoji_for("status", g_variant_new_string("playing"), "\xe2\x96\xb6\xef\xb8\x8f");
    emoji_for("status", g_variant_new_string("PAUSED"), "\xe2\x8f\xb8\xef\xb8\x8f");
    emoji_for("status", g_variant_new_string("Stopped"), "\xe2\x8f\xb9\xef\xb8\x8f");
    emoji_for("status", g_variant_new_string("Bogus"), "Bogus");
    emoji_for("status", g_variant_new_string(""), "");
    emoji_for("status", g_variant_new_string("Playing "), "Playing ");
    emoji_for("status", g_variant_new_int64(1), "1");
    emoji_for("status", g_variant_new_boolean(TRUE), "true");
}

static void test_emoji_loop_values(void) {
    emoji_for("loop", g_variant_new_string("Track"), "\xf0\x9f\x94\x82");
    emoji_for("loop", g_variant_new_string("Playlist"), "\xf0\x9f\x94\x81");
    emoji_for("loop", g_variant_new_string("None"), "\xe2\x9e\xa1\xef\xb8\x8f");
    emoji_for("loop", g_variant_new_string("none"), "\xe2\x9e\xa1\xef\xb8\x8f");
    emoji_for("loop", g_variant_new_string("forever"), "forever");
    emoji_for("loop", g_variant_new_boolean(FALSE), "false");
}

static void test_emoji_shuffle_values(void) {
    emoji_for("shuffle", g_variant_new_boolean(TRUE), "\xf0\x9f\x94\x80");
    emoji_for("shuffle", g_variant_new_boolean(FALSE), "\xe2\x9e\xa1\xef\xb8\x8f");
    emoji_for("shuffle", g_variant_new_string("true"), "true");
    emoji_for("shuffle", g_variant_new_int64(1), "1");
}

static void test_emoji_volume_boundaries(void) {
    emoji_for("volume", g_variant_new_double(0.0), "\xf0\x9f\x94\x88");
    emoji_for("volume", g_variant_new_double(-5.0), "\xf0\x9f\x94\x88");
    emoji_for("volume", g_variant_new_double(0.3332), "\xf0\x9f\x94\x88");
    emoji_for("volume", g_variant_new_double(0.3333), "\xf0\x9f\x94\x89");
    emoji_for("volume", g_variant_new_double(0.6665), "\xf0\x9f\x94\x89");
    emoji_for("volume", g_variant_new_double(0.6666), "\xf0\x9f\x94\x8a");
    emoji_for("volume", g_variant_new_double(1.0), "\xf0\x9f\x94\x8a");
    emoji_for("volume", g_variant_new_double(100.0), "\xf0\x9f\x94\x8a");
    emoji_for("volume", g_variant_new_double(INFINITY), "\xf0\x9f\x94\x8a");
    emoji_for("volume", g_variant_new_double(-INFINITY), "\xf0\x9f\x94\x88");
    emoji_for("volume", g_variant_new_double(NAN), "\xf0\x9f\x94\x8a");
    emoji_for("volume", g_variant_new_int64(1), "1");
    emoji_for("volume", g_variant_new_string("0.5"), "0.5");
}

static void test_emoji_other_keys_pass_through(void) {
    emoji_for("title", g_variant_new_string("Playing"), "Playing");
    emoji_for("Status", g_variant_new_string("Playing"), "Playing");
    emoji_for("xesam:status", g_variant_new_string("Playing"), "Playing");
    emoji_for("playerName", g_variant_new_string("mpv"), "mpv");
}

/* ---- helpers: byte-level properties ---- */

static gchar *json_unescape(const gchar *in) {
    GString *out = g_string_new("");
    for (const gchar *p = in; *p != '\0'; p++) {
        if (*p != '\\') {
            g_assert_cmpuint((guchar)*p, >=, 0x20);
            g_assert_true(*p != '"');
            g_string_append_c(out, *p);
            continue;
        }
        p++;
        switch (*p) {
        case '"': g_string_append_c(out, '"'); break;
        case '\\': g_string_append_c(out, '\\'); break;
        case '/': g_string_append_c(out, '/'); break;
        case 'b': g_string_append_c(out, '\b'); break;
        case 'f': g_string_append_c(out, '\f'); break;
        case 'n': g_string_append_c(out, '\n'); break;
        case 'r': g_string_append_c(out, '\r'); break;
        case 't': g_string_append_c(out, '\t'); break;
        case 'u': {
            guint v = 0;
            g_assert_cmpint(sscanf(p + 1, "%4x", &v), ==, 1);
            g_assert_cmpuint(v, <, 0x80);
            g_string_append_c(out, (gchar)v);
            p += 4;
            break;
        }
        default:
            g_assert_not_reached();
        }
    }
    return g_string_free(out, FALSE);
}

static void test_json_escape_roundtrip_every_ascii_char(void) {
    for (int c = 1; c < 128; c++) {
        gchar raw[4] = {'a', (gchar)c, 'z', 0};
        GVariantDict *ctx = empty_ctx();
        g_variant_dict_insert(ctx, "v", "s", raw);
        GError *err = NULL;
        gchar *out = render("{{json_escape(v)}}", ctx, &err);
        g_assert_no_error(err);
        gchar *back = json_unescape(out);
        g_assert_cmpstr(back, ==, raw);
        g_free(back);
        g_free(out);
        g_variant_dict_unref(ctx);
    }
}

static void test_json_escape_all_controls_in_one_string(void) {
    GString *raw = g_string_new("");
    for (int c = 1; c < 0x20; c++) {
        g_string_append_c(raw, (gchar)c);
    }
    g_string_append(raw, "\x7f\xc3\xa9\xe2\x80\xa8");
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", raw->str);
    GError *err = NULL;
    gchar *out = render("{{json_escape(v)}}", ctx, &err);
    g_assert_no_error(err);
    for (const gchar *p = out; *p; p++) {
        g_assert_cmpuint((guchar)*p, >=, 0x20);
    }
    gchar *back = json_unescape(out);
    g_assert_cmpstr(back, ==, raw->str);
    g_free(back);
    g_free(out);
    g_variant_dict_unref(ctx);
    g_string_free(raw, TRUE);
}

static void test_json_escape_del_not_escaped(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "\x7f");
    assert_renders(ctx, "{{json_escape(v)}}", "\x7f");
    g_variant_dict_unref(ctx);
}

static void test_json_escape_twice(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "\"");
    assert_renders(ctx, "{{json_escape(json_escape(v))}}", "\\\\\\\"");
    g_variant_dict_unref(ctx);
}

static void test_markup_escape_no_raw_specials_every_ascii_char(void) {
    for (int c = 1; c < 128; c++) {
        gchar raw[4] = {'a', (gchar)c, 'z', 0};
        GVariantDict *ctx = empty_ctx();
        g_variant_dict_insert(ctx, "v", "s", raw);
        GError *err = NULL;
        gchar *out = render("{{markup_escape(v)}}", ctx, &err);
        g_assert_no_error(err);
        g_assert_null(strpbrk(out, "<>\"'"));
        /* every '&' starts an entity */
        for (const gchar *p = out; (p = strchr(p, '&')) != NULL; p++) {
            g_assert_nonnull(strchr(p, ';'));
        }
        g_free(out);
        g_variant_dict_unref(ctx);
    }
}

static void test_markup_escape_exact_entities(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "<>&'\"");
    assert_renders(ctx, "{{markup_escape(v)}}", "&lt;&gt;&amp;&apos;&quot;");
    g_variant_dict_unref(ctx);
}

static void test_markup_escape_del_and_c1(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "\x7f\xc2\x85");
    GError *err = NULL;
    gchar *out = render("{{markup_escape(v)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_null(strchr(out, '\x7f'));
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void test_pad_999999_width(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "ab");
    GError *err = NULL;
    gchar *out = render("{{pad(v,999999)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpint(strlen(out), ==, 999999);
    g_assert_true(g_str_has_prefix(out, "ab  "));
    g_free(out);
    out = render("{{pad(v,-999999)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpint(strlen(out), ==, 999999);
    g_assert_true(g_str_has_suffix(out, "  ab"));
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void test_pad_999999_point_5(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "");
    GError *err = NULL;
    gchar *out = render("{{pad(v,999999.5)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpint(strlen(out), ==, 999999);
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void test_pad_counts_codepoints_not_bytes(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "\xc3\xa9\xc3\xa9");
    assert_renders(ctx, "{{pad(v,4)}}|", "\xc3\xa9\xc3\xa9  |");
    assert_renders(ctx, "{{pad(v,-4)}}|", "  \xc3\xa9\xc3\xa9|");
    g_variant_dict_unref(ctx);
}

static void test_trunc_long_string_exact(void) {
    GVariantDict *ctx = make_ctx();
    GError *err = NULL;
    gchar *out = render("{{trunc(long, 1999)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpint(g_utf8_strlen(out, -1), ==, 2000);
    g_free(out);
    out = render("{{trunc(long, 2000)}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpint(strlen(out), ==, 2000);
    g_assert_false(g_str_has_suffix(out, "\xe2\x80\xa6"));
    g_free(out);
    g_variant_dict_unref(ctx);
}

static void test_utf8_case_mapping_keeps_validity(void) {
    GVariantDict *ctx = make_ctx();
    const gchar *vars[] = {"utf", "emo", "comb", "ctrl", "long"};
    for (gsize i = 0; i < G_N_ELEMENTS(vars); i++) {
        for (int pass = 0; pass < 2; pass++) {
            gchar *fmt = g_strdup_printf("{{%s(%s)}}", pass ? "uc" : "lc", vars[i]);
            GError *err = NULL;
            gchar *out = render(fmt, ctx, &err);
            g_assert_no_error(err);
            g_assert_true(g_utf8_validate(out, -1, NULL));
            g_free(out);
            g_free(fmt);
        }
    }
    g_variant_dict_unref(ctx);
}

static void test_uri_decode_every_byte_escape(void) {
    GVariantDict *ctx = empty_ctx();
    for (int c = 1; c < 128; c++) {
        gchar *enc = g_strdup_printf("%%%02X", c);
        g_variant_dict_insert(ctx, "v", "s", enc);
        GError *err = NULL;
        gchar *out = render("{{uri_decode(v)}}", ctx, &err);
        g_assert_no_error(err);
        g_assert_cmpint(strlen(out), ==, 1);
        g_assert_cmpint((guchar)out[0], ==, c);
        g_free(out);
        g_free(enc);
    }
    g_variant_dict_unref(ctx);
}

static void test_duration_small_values(void) {
    GVariantDict *ctx = empty_ctx();
    for (gint64 s = 0; s < 7300; s += 37) {
        g_variant_dict_insert(ctx, "v", "x", s * 1000000);
        gchar *expected;
        if (s >= 3600) {
            expected = g_strdup_printf("%" G_GINT64_FORMAT ":%02" G_GINT64_FORMAT ":%02" G_GINT64_FORMAT,
                                       s / 3600, (s / 60) % 60, s % 60);
        } else {
            expected = g_strdup_printf("%" G_GINT64_FORMAT ":%02" G_GINT64_FORMAT, s / 60, s % 60);
        }
        assert_renders(ctx, "{{duration(v)}}", expected);
        g_free(expected);
    }
    g_variant_dict_unref(ctx);
}

/* ---- randomized: differential check of the arithmetic ---- */

struct gen {
    GRand *rand;
    GString *out;
    int depth;
};

/* Generates a template fragment and returns its value; *div0 is set when
 * the evaluation divides by zero. Mirrors the documented precedence:
 * unary binds tightest, then * and /, then + and -, all left-associative. */
static double gen_expr(struct gen *g, gboolean *div0);

static double gen_atom(struct gen *g, gboolean *div0) {
    gint32 r = g_rand_int_range(g->rand, 0, 10);
    if (r < 2 && g->depth < 4) {
        g_string_append_c(g->out, '(');
        g->depth++;
        double v = gen_expr(g, div0);
        g->depth--;
        g_string_append_c(g->out, ')');
        return v;
    }
    if (r < 3) {
        g_string_append_c(g->out, '-');
        return -gen_atom(g, div0);
    }
    if (r < 4) {
        g_string_append_c(g->out, '+');
        return gen_atom(g, div0);
    }
    int n = g_rand_int_range(g->rand, 0, 100);
    g_string_append_printf(g->out, "%d", n);
    if (g_rand_boolean(g->rand)) {
        int f = g_rand_int_range(g->rand, 0, 100);
        g_string_append_printf(g->out, ".%d", f);
        char buf[32];
        snprintf(buf, sizeof buf, "%d.%d", n, f);
        return g_ascii_strtod(buf, NULL);
    }
    return n;
}

static double gen_term(struct gen *g, gboolean *div0) {
    double v = gen_atom(g, div0);
    while (g_rand_int_range(g->rand, 0, 3) == 0) {
        gboolean mul = g_rand_boolean(g->rand);
        g_string_append(g->out, g_rand_boolean(g->rand) ? (mul ? "*" : "/") : (mul ? " * " : " / "));
        double r = gen_atom(g, div0);
        if (mul) {
            v = v * r;
        } else {
            if (r == 0.0) {
                *div0 = TRUE;
            }
            v = v / r;
        }
    }
    return v;
}

static double gen_expr(struct gen *g, gboolean *div0) {
    double v = gen_term(g, div0);
    while (g_rand_int_range(g->rand, 0, 3) == 0) {
        gboolean add = g_rand_boolean(g->rand);
        g_string_append(g->out, g_rand_boolean(g->rand) ? (add ? "+" : "-") : (add ? " + " : " - "));
        double r = gen_term(g, div0);
        v = add ? v + r : v - r;
    }
    return v;
}

static void test_random_arithmetic_matches_oracle(void) {
    GRand *rand = g_rand_new_with_seed(20260101);
    GVariantDict *ctx = empty_ctx();
    for (int n = 0; n < 4000; n++) {
        struct gen g = {rand, g_string_new("{{"), 0};
        gboolean div0 = FALSE;
        double expected = gen_expr(&g, &div0);
        g_string_append(g.out, "}}");
        GError *err = NULL;
        gchar *out = render(g.out->str, ctx, &err);
        if (div0) {
            if (out != NULL) {
                g_test_message("expected a division error for %s, got %s", g.out->str, out);
            }
            g_assert_null(out);
            assert_formatter_error(err);
            g_assert_true(g_pattern_match_simple("Divide by zero error", err->message));
        } else {
            if (err != NULL) {
                g_test_message("unexpected error for %s: %s", g.out->str, err->message);
            }
            g_assert_no_error(err);
            double got = g_ascii_strtod(out, NULL);
            if (!(got == expected)) {
                g_test_message("%s: got %s expected %.17g", g.out->str, out, expected);
            }
            g_assert_true(got == expected || (isnan(got) && isnan(expected)));
        }
        g_clear_error(&err);
        g_free(out);
        g_string_free(g.out, TRUE);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
}

static void test_random_int64_ops_match_wide_arithmetic(void) {
    /* int64 operands near the limits against __int128 */
    GRand *rand = g_rand_new_with_seed(77);
    static const gint64 edges[] = {INT64_MIN, INT64_MIN + 1, -2, -1, 0, 1, 2, INT64_MAX - 1, INT64_MAX,
                                   3037000499LL, 3037000500LL, -3037000500LL, 4611686018427387904LL};
    GVariantDict *ctx = empty_ctx();
    const gchar ops[] = {'+', '-', '*', '/'};
    for (int n = 0; n < 2000; n++) {
        gint64 a = g_rand_boolean(rand) ? edges[g_rand_int_range(rand, 0, G_N_ELEMENTS(edges))]
                                        : (gint64)(((guint64)g_rand_int(rand) << 32) | g_rand_int(rand));
        gint64 b = g_rand_boolean(rand) ? edges[g_rand_int_range(rand, 0, G_N_ELEMENTS(edges))]
                                        : (gint64)(((guint64)g_rand_int(rand) << 32) | g_rand_int(rand));
        char op = ops[g_rand_int_range(rand, 0, 4)];
        g_variant_dict_insert(ctx, "a", "x", a);
        g_variant_dict_insert(ctx, "b", "x", b);
        gchar *fmt = g_strdup_printf("{{a %c b}}", op);
        GError *err = NULL;
        gchar *out = render(fmt, ctx, &err);
        __int128 wide = 0;
        gboolean invalid = FALSE;
        switch (op) {
        case '+': wide = (__int128)a + b; break;
        case '-': wide = (__int128)a - b; break;
        case '*': wide = (__int128)a * b; break;
        default:
            if (b == 0) {
                invalid = TRUE;
            } else {
                wide = (__int128)a / b;
            }
        }
        if (invalid || wide > INT64_MAX || wide < INT64_MIN) {
            g_assert_null(out);
            assert_formatter_error(err);
        } else {
            g_assert_no_error(err);
            gchar *expected = g_strdup_printf("%" G_GINT64_FORMAT, (gint64)wide);
            g_assert_cmpstr(out, ==, expected);
            g_free(expected);
        }
        g_clear_error(&err);
        g_free(out);
        g_free(fmt);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
}

/* ---- randomized: fuzzing with a token alphabet ---- */

static const gchar *const fuzz_alphabet[] = {
    "{{", "}}", "{", "}", "(", ")", ",", "+", "-", "*", "/", "\"", " ", "  ", ".", "1", "0", "2.5", "12",
    "s", "i", "u", "d", "arr", "missing", "estr", "x:y", "_", "lc", "uc", "trunc", "pad", "default", "emoji",
    "join", "replace", "round", "int", "duration", "json_escape", "markup_escape", "uri_decode", "status",
    "nosuch", "lc(", "default(", "trunc(", "pad(", "replace(", "join(", "emoji(", "duration(", "{{s}}",
    "{{lc(s)}}", "{{1+2}}", "\xc3\xa9", "\xf0\x9f\x98\x80", "\\", "%", "@", "\t", "\n", "nan", "inf", "big",
    "min", "umax", "\"a\"", "\"\"", "-1", "99999999999", "1e5", "(1+2)", "-(", "+(", "*(", "/(", "))", "((",
    ",,", ", ", "uri", "urix", "ctrl", "long", "dbig", "zero", "m1",
};

/* known critical messages the fuzz tolerates (each is a recorded bug) */
static const gchar *const allowed_criticals[] = {
    "g_variant_ref: assertion 'value != NULL' failed",
    "g_variant_new_string: assertion 'g_utf8_validate",
    "g_variant_new_string: assertion 'string != NULL' failed",
    "g_variant_new: assertion",
    "g_variant_dict_insert_value: assertion",
    "g_variant_dict_lookup_value: assertion",
};

static GHashTable *seen_criticals;

static void fuzz_log_handler(const gchar *domain, GLogLevelFlags level, const gchar *message,
                             gpointer data) {
    (void)domain;
    (void)data;
    if (level & (G_LOG_LEVEL_CRITICAL | G_LOG_LEVEL_WARNING)) {
        g_hash_table_add(seen_criticals, g_strdup(message));
    }
}

static void fuzz_begin(void) {
    seen_criticals = g_hash_table_new_full(g_str_hash, g_str_equal, g_free, NULL);
    g_log_set_always_fatal(G_LOG_FATAL_MASK);
    g_log_set_default_handler(fuzz_log_handler, NULL);
}

/* Returns TRUE when every critical logged was one of the known ones. */
static gboolean fuzz_end(void) {
    gboolean all_known = TRUE;
    GHashTableIter it;
    gpointer key;
    g_hash_table_iter_init(&it, seen_criticals);
    while (g_hash_table_iter_next(&it, &key, NULL)) {
        gboolean known = FALSE;
        for (gsize i = 0; i < G_N_ELEMENTS(allowed_criticals); i++) {
            if (strstr(key, allowed_criticals[i]) != NULL) {
                known = TRUE;
            }
        }
        if (!known) {
            fprintf(stderr, "UNKNOWN critical during fuzz: %s\n", (gchar *)key);
            all_known = FALSE;
        }
    }
    g_hash_table_destroy(seen_criticals);
    return all_known;
}

static void fuzz_one(const gchar *fmt, GVariantDict *ctx) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt, &err);
    if (f == NULL) {
        g_assert_nonnull(err);
        g_assert_true(g_error_matches(err, playerctl_formatter_error_quark(), 1));
        g_clear_error(&err);
        return;
    }
    g_assert_no_error(err);
    (void)playerctl_formatter_contains_key(f, "s");
    (void)playerctl_formatter_contains_key(f, "x:y");
    gchar *out = playerctl_formatter_expand_format(f, ctx, &err);
    if (out == NULL) {
        g_assert_nonnull(err);
        g_assert_true(g_error_matches(err, playerctl_formatter_error_quark(), 1));
        g_clear_error(&err);
    } else {
        g_assert_no_error(err);
        g_free(out);
    }
    playerctl_formatter_destroy(f);
}

static void fuzz_alphabet_batch(guint32 seed, int count) {
    fuzz_begin();
    GRand *rand = g_rand_new_with_seed(seed);
    GVariantDict *ctx = make_ctx();
    g_variant_dict_insert(ctx, "x:y", "s", "colon");
    for (int n = 0; n < count; n++) {
        GString *fmt = g_string_new("");
        int pieces = g_rand_int_range(rand, 1, 14);
        gboolean wrap = g_rand_int_range(rand, 0, 3) != 0;
        if (wrap) {
            g_string_append(fmt, "{{");
        }
        for (int p = 0; p < pieces; p++) {
            g_string_append(fmt, fuzz_alphabet[g_rand_int_range(rand, 0, G_N_ELEMENTS(fuzz_alphabet))]);
        }
        if (wrap && g_rand_int_range(rand, 0, 4) != 0) {
            g_string_append(fmt, "}}");
        }
        fuzz_one(fmt->str, ctx);
        g_string_free(fmt, TRUE);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
    g_assert_true(fuzz_end());
}

#define FUZZ_BATCH(name, seed) \
    static void name(void) { fuzz_alphabet_batch(seed, 5000); }
FUZZ_BATCH(test_fuzz_alphabet_0, 1001)
FUZZ_BATCH(test_fuzz_alphabet_1, 1002)
FUZZ_BATCH(test_fuzz_alphabet_2, 1003)
FUZZ_BATCH(test_fuzz_alphabet_3, 1004)
FUZZ_BATCH(test_fuzz_alphabet_4, 1005)
FUZZ_BATCH(test_fuzz_alphabet_5, 1006)
FUZZ_BATCH(test_fuzz_alphabet_6, 1007)
FUZZ_BATCH(test_fuzz_alphabet_7, 1008)

/* Structured generator: well-formed calls with random (mostly valid)
 * arguments, so the evaluator is exercised and not only the parser. */
static const gchar *const fuzz_atoms[] = {"s", "estr", "missing", "i", "u", "d", "nan", "inf", "nz", "big",
                                          "min", "umax", "arr", "earr", "utf", "emo", "comb", "ctrl",
                                          "status", "loop", "shuffle", "volume", "urix", "uri", "b", "tup",
                                          "\"txt\"", "\"\"", "0", "1", "-1", "2.5", "1000000", "dur"};
static const gchar *const fuzz_funcs[] = {"lc", "uc", "json_escape", "markup_escape", "duration", "emoji",
                                          "round", "int", "uri_decode"};
static const gchar *const fuzz_funcs2[] = {"default", "trunc", "pad", "join"};

static void gen_call(GRand *rand, GString *out, int depth) {
    gint32 r = g_rand_int_range(rand, 0, 12);
    if (depth > 4 || r < 4) {
        g_string_append(out, fuzz_atoms[g_rand_int_range(rand, 0, G_N_ELEMENTS(fuzz_atoms))]);
    } else if (r < 7) {
        g_string_append_printf(out, "%s(", fuzz_funcs[g_rand_int_range(rand, 0, G_N_ELEMENTS(fuzz_funcs))]);
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ')');
    } else if (r < 9) {
        g_string_append_printf(out, "%s(", fuzz_funcs2[g_rand_int_range(rand, 0, G_N_ELEMENTS(fuzz_funcs2))]);
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ',');
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ')');
    } else if (r < 10) {
        g_string_append(out, "replace(");
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ',');
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ',');
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ')');
    } else {
        const gchar *ops[] = {"+", "-", "*", "/"};
        g_string_append_c(out, '(');
        gen_call(rand, out, depth + 1);
        g_string_append(out, ops[g_rand_int_range(rand, 0, 4)]);
        gen_call(rand, out, depth + 1);
        g_string_append_c(out, ')');
    }
}

static void fuzz_structured_batch(guint32 seed, int count) {
    fuzz_begin();
    GRand *rand = g_rand_new_with_seed(seed);
    GVariantDict *ctx = make_ctx();
    for (int n = 0; n < count; n++) {
        GString *fmt = g_string_new("");
        int exprs = g_rand_int_range(rand, 1, 4);
        for (int e = 0; e < exprs; e++) {
            g_string_append(fmt, "{{");
            gen_call(rand, fmt, 0);
            g_string_append(fmt, "}}");
            if (g_rand_boolean(rand)) {
                g_string_append(fmt, " | ");
            }
        }
        if (fmt->len <= MAX_FORMAT_LENGTH) {
            fuzz_one(fmt->str, ctx);
        }
        g_string_free(fmt, TRUE);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
    g_assert_true(fuzz_end());
}

static void test_fuzz_structured_0(void) { fuzz_structured_batch(2001, 5000); }
static void test_fuzz_structured_1(void) { fuzz_structured_batch(2002, 5000); }

static void test_fuzz_random_ascii_noise(void) {
    fuzz_begin();
    GRand *rand = g_rand_new_with_seed(3001);
    GVariantDict *ctx = make_ctx();
    static const gchar noise[] = "{}(),+-*/\" .:_abcsiu019%\\@\t";
    for (int n = 0; n < 5000; n++) {
        int len = g_rand_int_range(rand, 0, 80);
        gchar *fmt = g_malloc(len + 1);
        for (int k = 0; k < len; k++) {
            fmt[k] = noise[g_rand_int_range(rand, 0, sizeof noise - 1)];
        }
        fmt[len] = '\0';
        fuzz_one(fmt, ctx);
        g_free(fmt);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
    g_assert_true(fuzz_end());
}

static void test_fuzz_random_full_length(void) {
    fuzz_begin();
    GRand *rand = g_rand_new_with_seed(3002);
    GVariantDict *ctx = make_ctx();
    static const gchar noise[] = "{{}}(),+-*/\"  .:_lcsiu019";
    for (int n = 0; n < 500; n++) {
        int len = g_rand_int_range(rand, 900, 1030);
        gchar *fmt = g_malloc(len + 1);
        for (int k = 0; k < len; k++) {
            fmt[k] = noise[g_rand_int_range(rand, 0, sizeof noise - 1)];
        }
        fmt[len] = '\0';
        fuzz_one(fmt, ctx);
        g_free(fmt);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
    g_assert_true(fuzz_end());
}

static void test_fuzz_random_bytes(void) {
    fuzz_begin();
    GRand *rand = g_rand_new_with_seed(3003);
    GVariantDict *ctx = make_ctx();
    for (int n = 0; n < 3000; n++) {
        int len = g_rand_int_range(rand, 0, 60);
        gchar *fmt = g_malloc(len + 1);
        for (int k = 0; k < len; k++) {
            fmt[k] = (gchar)g_rand_int_range(rand, 1, 256);
        }
        fmt[len] = '\0';
        /* start expressions at random places */
        if (len > 4 && g_rand_boolean(rand)) {
            fmt[0] = '{';
            fmt[1] = '{';
        }
        fuzz_one(fmt, ctx);
        g_free(fmt);
    }
    g_variant_dict_unref(ctx);
    g_rand_free(rand);
    g_assert_true(fuzz_end());
}

static void test_fuzz_prefixes_and_mutations(void) {
    /* every prefix and suffix of valid templates, plus every single-byte
     * deletion and duplication: truncation at each position (the
     * step_number "len-2" boundary and unterminated tokens) */
    static const gchar *const valid[] = {
        "{{default(trunc(lc(s), 3), \"x\")}} - {{ 1 + 2 * (3 - 4) / 5 }} {{pad(s, -8)}}",
        "{{replace(\"abc\", \"b\", \"12345\")}}{{join(arr, \", \")}}{{round(2.5)}}",
        "{{-(-(1.5)) * +2 - 3}}{{12}}{{ 7 }}{{9.}}{{.9}}",
        "{{emoji(status)}} {{duration(dur)}} {{uri_decode(uri)}} {{json_escape(ctrl)}}",
    };
    fuzz_begin();
    GVariantDict *ctx = make_ctx();
    for (gsize v = 0; v < G_N_ELEMENTS(valid); v++) {
        gsize len = strlen(valid[v]);
        for (gsize cut = 0; cut <= len; cut++) {
            gchar *prefix = g_strndup(valid[v], cut);
            fuzz_one(prefix, ctx);
            g_free(prefix);
            fuzz_one(valid[v] + cut, ctx);
        }
        for (gsize k = 0; k < len; k++) {
            gchar *mut = g_strdup(valid[v]);
            memmove(mut + k, mut + k + 1, len - k);
            fuzz_one(mut, ctx);
            g_free(mut);
        }
        for (gsize k = 0; k < len; k++) {
            gchar *mut = g_strdup_printf("%.*s%c%s", (int)k, valid[v], valid[v][k], valid[v] + k);
            fuzz_one(mut, ctx);
            g_free(mut);
        }
    }
    g_variant_dict_unref(ctx);
    g_assert_true(fuzz_end());
}

/* ---- registration ---- */

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);

    if (g_getenv("ADV_DUMP") != NULL) {
        dump_rows();
        return 0;
    }

    for (gsize i = 0; i < G_N_ELEMENTS(rows); i++) {
        gchar *path = g_strdup_printf("/formatter-adv/row/%s", rows[i].name);
        g_test_add_data_func(path, &rows[i], run_row);
        g_free(path);
    }

    T("len/text-1027", test_len_text_1027);
    T("len/text-1028-rejected", test_len_text_1028_rejected);
    T("len/huge-rejected", test_len_huge_rejected);
    T("len/variable-token-1027", test_len_variable_token_1027);
    T("len/variable-token-1028-rejected", test_len_variable_token_1028_rejected);
    T("len/string-literal-1027", test_len_string_literal_1027);
    T("len/string-literal-unterminated-1027", test_len_string_literal_unterminated_1027);
    T("len/unterminated-identifier-1027", test_len_unterminated_identifier_1027);
    T("len/number-token-1021-digits", test_len_number_token_1021_digits);
    T("len/number-token-unterminated", test_len_number_token_unterminated);
    T("len/text-then-expr-1027", test_len_text_then_expr_1027);
    T("len/many-tokens", test_len_many_tokens);
    T("len/all-open-braces", test_len_all_open_braces_1027);
    T("len/all-close-braces", test_len_all_close_braces_1027);
    T("len/utf8-text-1027-bytes", test_len_utf8_text_1027_bytes);
    T("len/args-filling-format", test_len_args_filling_format);

    T("nest/parens-max-511", test_nest_parens_max);
    T("nest/parens-unbalanced", test_nest_parens_unbalanced);
    T("nest/parens-only-open", test_nest_parens_only_open_to_limit);
    T("nest/unary-minus-1020", test_nest_unary_minus_1020);
    T("nest/unary-minus-odd", test_nest_unary_minus_odd);
    T("nest/unary-plus-1020", test_nest_unary_plus_1020);
    T("nest/unary-without-operand", test_nest_unary_without_operand);
    T("nest/unary-mixed-parens", test_nest_unary_mixed_parens);
    T("nest/calls-250", test_nest_calls_250);
    T("nest/calls-with-extra-args", test_nest_calls_with_extra_args);
    T("nest/long-add-chain", test_nest_long_add_chain);
    T("nest/long-mul-chain", test_nest_long_mul_chain);
    T("nest/long-alternating-chain", test_nest_long_alternating_chain);
    T("nest/right-deep-parens-chain", test_nest_right_deep_parens_chain);
    T("nest/contains-key-deep", test_nest_contains_key_deep);

    T("args/32-accepted-by-parser", test_args_32_accepted_by_parser);
    T("args/32-to-real-function", test_args_32_to_real_function);
    T("args/33-rejected", test_args_33_rejected);
    T("args/100-rejected", test_args_100_rejected);
    T("args/33-unterminated", test_args_33_unterminated);
    TL("args/33rd-malformed", test_args_33rd_is_malformed,
       "BUG-F2: parse_call_args leaks tmp_error when the 33rd argument fails to parse");
    TL("args/33rd-malformed-loop", test_args_33rd_malformed_leak_loop,
       "BUG-F2: parse_call_args leaks tmp_error when the 33rd argument fails to parse");
    T("args/every-function-every-count", test_args_every_function_every_count);
    T("args/zero-rejected-everywhere", test_args_zero_rejected_everywhere);
    T("args/check-argument-count-messages", test_check_argument_count_messages);
    T("args/check-argument-count-null-error", test_check_argument_count_null_error);
    T("args/template-table-consistent", test_template_table_consistent);
    T("args/infix-call-spelling", test_infix_call_spelling);

    T("api/new-null-format", test_new_null_format);
    T("api/new-empty-format", test_new_empty_format);
    T("api/null-error-pointer", test_new_null_error_pointer);
    T("api/null-error-pointer-arg-count", test_new_null_error_pointer_arg_count);
    T("api/destroy-null", test_destroy_null);
    TB("api/expand-null-formatter", test_expand_null_formatter,
       "BUG-F3: playerctl_formatter_expand_format (NULL) dereferences NULL");
    TB("api/contains-key-null-formatter", test_contains_key_null_formatter,
       "BUG-F3: playerctl_formatter_contains_key (NULL) dereferences NULL");
    T("api/contains-key-null-key", test_contains_key_null_key);
    T("api/contains-key-empty-format", test_contains_key_empty_format);
    T("api/contains-key-branches", test_contains_key_branches);
    T("api/contains-key-unknown-function", test_contains_key_unknown_function);
    T("api/expand-text-null-context", test_expand_text_only_with_null_context);
    T("api/expand-literals-null-context", test_expand_literals_with_null_context);
    TB("api/expand-variable-null-context", test_expand_variable_with_null_context,
       "BUG-F4: expanding a variable with a NULL context logs a GLib critical");
    T("api/reuse-many-times", test_reuse_formatter_many_times);
    T("api/reuse-after-error", test_reuse_formatter_after_error);

    T("token/create-destroy", test_token_create_destroy);
    T("token/tokenize-returns-tokens", test_tokenize_format_returns_tokens);
    T("token/tokenize-null", test_tokenize_format_null);
    T("token/tokenize-error", test_tokenize_format_error);
    T("token/expand-types", test_expand_token_types);
    T("token/expand-32-args", test_expand_token_32_args);
    T("token/expand-arg-error-cleanup", test_expand_token_arg_error_cleans_earlier_args);
    T("token/expand-format-empty-list", test_expand_format_empty_list);
    T("token/numeric-types", test_get_double_value_and_valid_types);
    T("token/other-numeric-types-in-context", test_other_numeric_types_in_context);

    T("errors/ascii-input-is-utf8", test_errors_are_utf8_for_ascii_input);
    TB("errors/non-ascii-char-message-is-utf8", test_error_message_for_non_ascii_character_is_utf8,
       "BUG-F6: the tokenizer error prints one byte of a multi-byte character with %c (invalid UTF-8)");
    T("errors/positions-in-range", test_error_positions_are_in_range);
    T("errors/domain-and-code-for-all-rows", test_error_domain_and_code_for_all_row_errors);

    T("emoji/status-values", test_emoji_status_values);
    T("emoji/loop-values", test_emoji_loop_values);
    T("emoji/shuffle-values", test_emoji_shuffle_values);
    T("emoji/volume-boundaries", test_emoji_volume_boundaries);
    T("emoji/other-keys-pass-through", test_emoji_other_keys_pass_through);

    T("bytes/json-roundtrip-every-ascii", test_json_escape_roundtrip_every_ascii_char);
    T("bytes/json-all-controls", test_json_escape_all_controls_in_one_string);
    T("bytes/json-del", test_json_escape_del_not_escaped);
    T("bytes/json-twice", test_json_escape_twice);
    T("bytes/markup-every-ascii", test_markup_escape_no_raw_specials_every_ascii_char);
    T("bytes/markup-entities", test_markup_escape_exact_entities);
    T("bytes/markup-del-c1", test_markup_escape_del_and_c1);
    T("bytes/pad-999999", test_pad_999999_width);
    T("bytes/pad-999999-point-5", test_pad_999999_point_5);
    T("bytes/pad-codepoints", test_pad_counts_codepoints_not_bytes);
    T("bytes/trunc-long", test_trunc_long_string_exact);
    T("bytes/case-mapping-valid-utf8", test_utf8_case_mapping_keeps_validity);
    T("bytes/uri-every-byte", test_uri_decode_every_byte_escape);
    T("bytes/duration-small-values", test_duration_small_values);

    T("random/arithmetic-oracle", test_random_arithmetic_matches_oracle);
    T("random/int64-wide-oracle", test_random_int64_ops_match_wide_arithmetic);

    T("fuzz/alphabet-0", test_fuzz_alphabet_0);
    T("fuzz/alphabet-1", test_fuzz_alphabet_1);
    T("fuzz/alphabet-2", test_fuzz_alphabet_2);
    T("fuzz/alphabet-3", test_fuzz_alphabet_3);
    T("fuzz/alphabet-4", test_fuzz_alphabet_4);
    T("fuzz/alphabet-5", test_fuzz_alphabet_5);
    T("fuzz/alphabet-6", test_fuzz_alphabet_6);
    T("fuzz/alphabet-7", test_fuzz_alphabet_7);
    T("fuzz/structured-0", test_fuzz_structured_0);
    T("fuzz/structured-1", test_fuzz_structured_1);
    T("fuzz/ascii-noise", test_fuzz_random_ascii_noise);
    T("fuzz/full-length", test_fuzz_random_full_length);
    T("fuzz/random-bytes", test_fuzz_random_bytes);
    T("fuzz/prefixes-and-mutations", test_fuzz_prefixes_and_mutations);

    return g_test_run();
}

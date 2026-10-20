/* Unit tests for playerctl-formatter.c. The implementation is included so the
 * static tokenizer / template functions can be called directly. */

#include <glib.h>
#include <math.h>
#include <stdint.h>

#include "playerctl/playerctl-formatter.c"

/* ---- helpers ---- */

/* Formats `format` against ctx. Returns the expansion, or NULL with *err set. */
/* Every test runs in its own subprocess: a failing assertion or a fatal
 * g_critical in one test then cannot take the remaining tests down with it. */
static void run_isolated(gconstpointer fn) {
    if (g_test_subprocess()) {
        ((void (*)(void))fn)();
        return;
    }
    g_test_trap_subprocess(NULL, 0, 0);
    g_test_trap_assert_passed();
}

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

#define ASSERT_RENDERS(format, ctx, expected) \
    G_STMT_START {                            \
        GError *_e = NULL;                    \
        gchar *_s = render(format, ctx, &_e); \
        g_assert_no_error(_e);                \
        g_assert_cmpstr(_s, ==, expected);    \
        g_free(_s);                           \
    }                                         \
    G_STMT_END

#define ASSERT_RENDER_FAILS(format, ctx, msg_glob)                    \
    G_STMT_START {                                                    \
        GError *_e = NULL;                                            \
        gchar *_s = render(format, ctx, &_e);                         \
        g_assert_null(_s);                                            \
        g_assert_nonnull(_e);                                         \
        g_assert_true(g_pattern_match_simple(msg_glob, _e->message)); \
        g_clear_error(&_e);                                           \
    }                                                                 \
    G_STMT_END

static GVariantDict *empty_ctx(void) {
    return g_variant_dict_new(NULL);
}

/* Calls a template function with the given (floating or full) variants and
 * releases them. `tok` may be NULL for functions that ignore it. */
static GVariant *call_fn(GVariant *(*fn)(struct token *, GVariant **, int, GError **),
                         struct token *tok, GError **err, int nargs, ...) {
    GVariant *args[MAX_ARGS + 1];
    va_list ap;
    va_start(ap, nargs);
    for (int i = 0; i < nargs; i++) {
        GVariant *v = va_arg(ap, GVariant *);
        args[i] = v != NULL ? g_variant_ref_sink(v) : NULL;
    }
    va_end(ap);
    GVariant *ret = fn(tok, args, nargs, err);
    if (ret != NULL) {
        g_variant_ref_sink(ret);
    }
    for (int i = 0; i < nargs; i++) {
        if (args[i] != NULL) {
            g_variant_unref(args[i]);
        }
    }
    return ret;
}

static void assert_string_result(GVariant *ret, const gchar *expected) {
    g_assert_nonnull(ret);
    g_assert_true(g_variant_is_of_type(ret, G_VARIANT_TYPE_STRING));
    g_assert_cmpstr(g_variant_get_string(ret, NULL), ==, expected);
    g_variant_unref(ret);
}

static void assert_fails(GVariant *ret, GError *err, const gchar *msg_glob) {
    g_assert_null(ret);
    g_assert_nonnull(err);
    if (err != NULL) {
        g_assert_true(g_pattern_match_simple(msg_glob, err->message));
        g_error_free(err);
    }
}

#define CALL(fn, tok, err, ...) \
    call_fn(fn, tok, err, G_N_ELEMENTS(((GVariant *[]){__VA_ARGS__})), __VA_ARGS__)

static GVariant *V_i64(gint64 v) {
    return g_variant_new_int64(v);
}
static GVariant *V_u64(guint64 v) {
    return g_variant_new_uint64(v);
}
static GVariant *V_d(gdouble v) {
    return g_variant_new_double(v);
}
static GVariant *V_s(const gchar *v) {
    return g_variant_new_string(v);
}

/* ---- tokenizer: structure ---- */

static void test_plain_text(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDERS("just text", ctx, "just text");
    ASSERT_RENDERS("", ctx, "");
    ASSERT_RENDERS("a { b } c", ctx, "a { b } c");
    g_variant_dict_unref(ctx);
}

static void test_null_format(void) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(NULL, &err);
    g_assert_no_error(err);
    g_assert_nonnull(f);
    g_assert_false(playerctl_formatter_contains_key(f, "anything"));
    GVariantDict *ctx = empty_ctx();
    gchar *out = playerctl_formatter_expand_format(f, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(out, ==, "");
    g_free(out);
    g_variant_dict_unref(ctx);
    playerctl_formatter_destroy(f);
}

static void test_destroy_null(void) {
    playerctl_formatter_destroy(NULL);
}

static void test_format_too_long(void) {
    gchar *fmt = g_strnfill(1028, 'x');
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt, &err);
    g_assert_null(f);
    g_assert_nonnull(err);
    g_assert_true(g_pattern_match_simple("*maximum format string length*", err->message));
    g_clear_error(&err);
    g_free(fmt);

    /* one shorter is still accepted */
    gchar *ok = g_strnfill(1027, 'x');
    f = playerctl_formatter_new(ok, &err);
    g_assert_no_error(err);
    g_assert_nonnull(f);
    playerctl_formatter_destroy(f);
    g_free(ok);
}

static void test_format_max_length_message(void) {
    /* Intended: the error names the real limit, 1027 (len >= 1028 is
     * rejected), not 1028. */
    gchar *fmt = g_strnfill(1028, 'x');
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt, &err);
    g_assert_null(f);
    g_assert_nonnull(err);
    g_assert_true(g_pattern_match_simple("*1027*", err->message));
    g_clear_error(&err);
    g_free(fmt);
}

static void test_expand_format_error_frees_buffer(void) {
    /* expand_format leaks its GString when a token fails. Passes on its own;
     * LSan reports the leak under `make test-asan`. */
    GVariantDict *ctx = empty_ctx();
    for (int i = 0; i < 100; i++) {
        ASSERT_RENDER_FAILS("prefix {{missing_fn(1)}} suffix", ctx, "*");
    }
    g_variant_dict_unref(ctx);
}

static void test_variables_and_whitespace(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "title", "s", "Song");
    g_variant_dict_insert(ctx, "xesam:artist", "s", "Band");
    ASSERT_RENDERS("{{title}}", ctx, "Song");
    ASSERT_RENDERS("{{ title }}", ctx, "Song");
    ASSERT_RENDERS("[{{title}}] by {{xesam:artist}}", ctx, "[Song] by Band");
    ASSERT_RENDERS("{{missing}}", ctx, "");
    ASSERT_RENDERS("{{title}}{{title}}", ctx, "SongSong");
    g_variant_dict_unref(ctx);
}

static void test_string_literals(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDERS("{{\"hi there\"}}", ctx, "hi there");
    ASSERT_RENDERS("{{ \"x\" }}", ctx, "x");
    ASSERT_RENDERS("{{\"\"}}", ctx, "");
    g_variant_dict_unref(ctx);
}

/* ---- tokenizer: error branches ---- */

static void test_tokenizer_errors(void) {
    static const struct {
        const gchar *format;
        const gchar *msg;
    } cases[] = {
        {"{{", "unexpected end of expression"},
        {"{{}}", "unexpected \"}\"*"},
        {"{{ }}", "unexpected \"}\"*"},
        {"{{@}}", "unexpected \"@\"*"},
        {"{{ # }}", "unexpected \"#\"*"},
        {"{{\"abc", "unexpected end of expression"},
        {"{{\"abc}}", "unexpected end of expression"},
        {"{{foo", "*"},
        {"{{title}", "expecting \"}}\"*"},
        {"{{title", "*"},
        {"{{foo(}}", "*"},
        {"{{foo(1}}", "expecting \")\"*"},
        {"{{foo(1,}}", "*"},
        {"{{foo(1 2)}}", "expecting \")\"*"},
        {"{{(1}}", "expected \")\"*"},
        {"{{(1+2}}", "expected \")\"*"},
        {"{{1.2.3}}", "invalid number*"},
        {"{{1 +}}", "unexpected \"}\"*"},
        {"{{1 * }}", "unexpected \"}\"*"},
        {"{{-}}", "unexpected \"}\"*"},
        {"{{+}}", "unexpected \"}\"*"},
        {"{{1 + @}}", "unexpected \"@\"*"},
        {"{{foo(@)}}", "unexpected \"@\"*"},
        {"{{(@)}}", "unexpected \"@\"*"},
        {"{{-@}}", "unexpected \"@\"*"},
        {"{{1 * @}}", "unexpected \"@\"*"},
    };
    for (gsize i = 0; i < G_N_ELEMENTS(cases); i++) {
        GError *err = NULL;
        PlayerctlFormatter *f = playerctl_formatter_new(cases[i].format, &err);
        if (f != NULL || err == NULL) {
            g_test_message("format %s unexpectedly accepted", cases[i].format);
        }
        g_assert_null(f);
        g_assert_nonnull(err);
        if (err != NULL) {
            if (!g_pattern_match_simple(cases[i].msg, err->message)) {
                g_test_message("format %s: got message \"%s\"", cases[i].format, err->message);
            }
            g_assert_true(g_pattern_match_simple(cases[i].msg, err->message));
            g_clear_error(&err);
        }
    }
}

static void test_too_many_args(void) {
    GString *fmt = g_string_new("{{f(1");
    for (int i = 0; i < MAX_ARGS + 1; i++) {
        g_string_append(fmt, ",1");
    }
    g_string_append(fmt, ")}}");
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(fmt->str, &err);
    g_assert_null(f);
    g_assert_nonnull(err);
    g_assert_true(g_pattern_match_simple("maximum args*", err->message));
    g_clear_error(&err);
    g_string_free(fmt, TRUE);
}

static void test_infix_to_identifier(void) {
    gchar *s;
    s = infix_to_identifier('+');
    g_assert_cmpstr(s, ==, "+");
    g_free(s);
    s = infix_to_identifier('-');
    g_assert_cmpstr(s, ==, "-");
    g_free(s);
    s = infix_to_identifier('*');
    g_assert_cmpstr(s, ==, "*");
    g_free(s);
    s = infix_to_identifier('/');
    g_assert_cmpstr(s, ==, "/");
    g_free(s);
}

/* ---- contains_key / token_list_contains_key ---- */

static void test_contains_key(void) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new(
        "{{title}} {{lc(artist)}} {{uc(default(album, \"none\"))}} {{position * 2}} {{ \"lit\" }}",
        &err);
    g_assert_no_error(err);
    g_assert_true(playerctl_formatter_contains_key(f, "title"));
    g_assert_true(playerctl_formatter_contains_key(f, "artist"));   /* inside function */
    g_assert_true(playerctl_formatter_contains_key(f, "album"));    /* nested function */
    g_assert_true(playerctl_formatter_contains_key(f, "position")); /* inside infix */
    g_assert_false(playerctl_formatter_contains_key(f, "lit"));     /* string literal */
    g_assert_false(playerctl_formatter_contains_key(f, "none"));
    g_assert_false(playerctl_formatter_contains_key(f, "volume"));
    g_assert_false(playerctl_formatter_contains_key(f, NULL));
    playerctl_formatter_destroy(f);
}

static void test_contains_key_unary_and_nested_arith(void) {
    GError *err = NULL;
    PlayerctlFormatter *f = playerctl_formatter_new("{{ -(a + b * c) }}", &err);
    g_assert_no_error(err);
    g_assert_true(playerctl_formatter_contains_key(f, "a"));
    g_assert_true(playerctl_formatter_contains_key(f, "b"));
    g_assert_true(playerctl_formatter_contains_key(f, "c"));
    g_assert_false(playerctl_formatter_contains_key(f, "d"));
    playerctl_formatter_destroy(f);
}

static void test_token_list_contains_key_direct(void) {
    g_assert_false(token_list_contains_key(NULL, "x"));
    struct token *num = token_create(TOKEN_NUMBER);
    struct token *var = token_create(TOKEN_VARIABLE);
    var->data = g_strdup("v");
    GList *l = g_list_append(NULL, num);
    l = g_list_append(l, var);
    g_assert_true(token_list_contains_key(l, "v"));
    g_assert_false(token_list_contains_key(l, "w"));
    token_list_destroy(l);
}

/* ---- arithmetic through the tokenizer ---- */

static void test_arithmetic_literals(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDERS("{{1+2}}", ctx, "3.0");
    ASSERT_RENDERS("{{ 2 * 3 + 1 }}", ctx, "7.0");
    ASSERT_RENDERS("{{1+2*3}}", ctx, "7.0");
    ASSERT_RENDERS("{{(1+2)*3}}", ctx, "9.0");
    ASSERT_RENDERS("{{10/4}}", ctx, "2.5");
    ASSERT_RENDERS("{{10-4-3}}", ctx, "3.0");
    ASSERT_RENDERS("{{8/2/2}}", ctx, "2.0");
    ASSERT_RENDERS("{{-3}}", ctx, "-3.0");
    ASSERT_RENDERS("{{+3}}", ctx, "3.0");
    ASSERT_RENDERS("{{1.5*2}}", ctx, "3.0");
    ASSERT_RENDERS("{{2 * -3}}", ctx, "-6.0");
    g_variant_dict_unref(ctx);
}

static void test_arithmetic_with_variables(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "a", "x", (gint64)6);
    g_variant_dict_insert(ctx, "b", "x", (gint64)2);
    g_variant_dict_insert(ctx, "u", "t", (guint64)5);
    g_variant_dict_insert(ctx, "d", "d", 0.5);
    ASSERT_RENDERS("{{a+b}}", ctx, "8");
    ASSERT_RENDERS("{{a-b}}", ctx, "4");
    ASSERT_RENDERS("{{a/b}}", ctx, "3");
    ASSERT_RENDERS("{{-a}}", ctx, "-6");
    ASSERT_RENDERS("{{a+d}}", ctx, "6.5");  /* int64 + double -> double */
    ASSERT_RENDERS("{{u+d}}", ctx, "5.5");  /* uint64 + double */
    ASSERT_RENDERS("{{u+a}}", ctx, "11.0"); /* uint64 + int64 -> double */
    ASSERT_RENDERS("{{+u}}", ctx, "5");     /* unary + keeps uint64 */
    g_variant_dict_unref(ctx);
}

static void test_int64_multiplication(void) {
    /* Intended: int64 * int64 yields the product. */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "a", "x", (gint64)3);
    g_variant_dict_insert(ctx, "b", "x", (gint64)4);
    ASSERT_RENDERS("{{a*b}}", ctx, "12");
    ASSERT_RENDERS("{{b*a}}", ctx, "12");
    g_variant_dict_unref(ctx);
}

static void test_int64_overflow(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "max", "x", (gint64)INT64_MAX);
    g_variant_dict_insert(ctx, "min", "x", (gint64)INT64_MIN);
    g_variant_dict_insert(ctx, "one", "x", (gint64)1);
    g_variant_dict_insert(ctx, "two", "x", (gint64)2);
    ASSERT_RENDER_FAILS("{{max+one}}", ctx, "*overflow*");
    ASSERT_RENDER_FAILS("{{min-one}}", ctx, "*overflow*");
    ASSERT_RENDER_FAILS("{{max-min}}", ctx, "*overflow*");
    ASSERT_RENDER_FAILS("{{max*two}}", ctx, "*overflow*");
    g_variant_dict_unref(ctx);
}

static void test_int64_add_min_min(void) {
    /* INT64_MIN + INT64_MIN wraps to 0, which the sign-based overflow check
     * (result > 0) does not notice. */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "min", "x", (gint64)INT64_MIN);
    ASSERT_RENDER_FAILS("{{min+min}}", ctx, "*overflow*");
    g_variant_dict_unref(ctx);
}

static void test_int64_min_negation(void) {
    /* Intended: -INT64_MIN is an overflow error (INT64_MIN * -1 is UB). */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "min", "x", (gint64)INT64_MIN);
    ASSERT_RENDER_FAILS("{{-min}}", ctx, "*overflow*");
    g_variant_dict_unref(ctx);
}

static void test_int64_min_div_minus_one(void) {
    /* Intended: INT64_MIN / -1 is an overflow error (it raises SIGFPE on x86). */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "min", "x", (gint64)INT64_MIN);
    g_variant_dict_insert(ctx, "m1", "x", (gint64)-1);
    ASSERT_RENDER_FAILS("{{min/m1}}", ctx, "*overflow*");
    g_variant_dict_unref(ctx);
}

static void test_divide_by_zero(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "a", "x", (gint64)6);
    g_variant_dict_insert(ctx, "z", "x", (gint64)0);
    ASSERT_RENDER_FAILS("{{1/0}}", ctx, "*Divide by zero*");
    ASSERT_RENDER_FAILS("{{a/z}}", ctx, "*Divide by zero*");
    ASSERT_RENDER_FAILS("{{a/0}}", ctx, "*Divide by zero*");
    g_variant_dict_unref(ctx);
}

static void test_arithmetic_type_errors(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "s", "s", "text");
    g_variant_dict_insert(ctx, "b", "b", TRUE);
    g_variant_dict_insert(ctx, "n", "x", (gint64)1);
    ASSERT_RENDER_FAILS("{{s+n}}", ctx, "*unsupported operand types for +*");
    ASSERT_RENDER_FAILS("{{n+s}}", ctx, "*unsupported operand types for +*");
    ASSERT_RENDER_FAILS("{{s-n}}", ctx, "*unsupported operand types for -*");
    ASSERT_RENDER_FAILS("{{b*n}}", ctx, "*unsupported operand types for **");
    ASSERT_RENDER_FAILS("{{n/s}}", ctx, "*unsupported operand types for /*");
    ASSERT_RENDER_FAILS("{{+s}}", ctx, "*unsupported operand type for unary +*");
    ASSERT_RENDER_FAILS("{{-s}}", ctx, "*unsupported operand type for unary -*");
    ASSERT_RENDER_FAILS("{{-b}}", ctx, "*unsupported operand type for unary -*");
    g_variant_dict_unref(ctx);
}

static void test_arithmetic_null_operand_binary(void) {
    /* missing variables expand to NULL: + and - report it cleanly */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "n", "x", (gint64)1);
    ASSERT_RENDER_FAILS("{{missing+n}}", ctx, "*unsupported operand type for +: NULL*");
    ASSERT_RENDER_FAILS("{{n-missing}}", ctx, "*unsupported operand type for -: NULL*");
    g_variant_dict_unref(ctx);
}

/* Intended: NULL operands of * and / and of the unary operators are a clean
 * error rather than a g_critical (g_variant_get_type_string(NULL)). These run
 * in subprocesses because a critical aborts the test binary. */
static void test_mul_null_operand(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "n", "x", (gint64)1);
    ASSERT_RENDER_FAILS("{{missing*n}}", ctx, "*unsupported operand*");
    g_variant_dict_unref(ctx);
}

static void test_div_null_operand(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "n", "x", (gint64)1);
    ASSERT_RENDER_FAILS("{{n/missing}}", ctx, "*unsupported operand*");
    g_variant_dict_unref(ctx);
}

static void test_unary_add_null_operand(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDER_FAILS("{{+missing}}", ctx, "*unsupported operand*");
    g_variant_dict_unref(ctx);
}

static void test_unary_sub_null_operand(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDER_FAILS("{{-missing}}", ctx, "*unsupported operand*");
    g_variant_dict_unref(ctx);
}

static void test_unary_sub_uint64(void) {
    /* Intended: unary minus accepts every numeric type unary plus does
     * (int64, uint64, double). */
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "u", "t", (guint64)5);
    GError *err = NULL;
    gchar *s = render("{{-u}}", ctx, &err);
    g_assert_no_error(err);
    g_assert_nonnull(s);
    g_free(s);
    g_variant_dict_unref(ctx);
}

static void test_infix_wrong_nargs(void) {
    GError *err = NULL;
    GVariant *r;
    r = CALL(infixfn_add, NULL, &err, V_i64(1), V_i64(2), V_i64(3));
    assert_fails(r, err, "Addition takes two arguments*");
    err = NULL;
    r = CALL(infixfn_sub, NULL, &err, V_i64(1), V_i64(2), V_i64(3));
    assert_fails(r, err, "Subtraction takes two arguments*");
    err = NULL;
    r = CALL(infixfn_mul, NULL, &err, V_i64(1));
    assert_fails(r, err, "Multiplication takes two arguments*");
    err = NULL;
    r = CALL(infixfn_div, NULL, &err, V_i64(1));
    assert_fails(r, err, "Division takes two arguments*");
}

static void test_infix_direct_types(void) {
    GError *err = NULL;
    GVariant *r = CALL(infixfn_add, NULL, &err, V_u64(2), V_u64(3));
    g_assert_no_error(err);
    g_assert_true(g_variant_is_of_type(r, G_VARIANT_TYPE_DOUBLE));
    g_assert_cmpfloat(g_variant_get_double(r), ==, 5.0);
    g_variant_unref(r);

    r = CALL(infixfn_sub, NULL, &err, V_d(2.5), V_i64(1));
    g_assert_no_error(err);
    g_assert_cmpfloat(g_variant_get_double(r), ==, 1.5);
    g_variant_unref(r);

    r = CALL(infixfn_sub, NULL, &err, V_d(2.5));
    g_assert_no_error(err);
    g_assert_cmpfloat(g_variant_get_double(r), ==, -2.5);
    g_variant_unref(r);

    r = CALL(infixfn_div, NULL, &err, V_d(1.0), V_d(0.0));
    assert_fails(r, err, "Divide by zero*");
    err = NULL;

    r = CALL(infixfn_div, NULL, &err, V_i64(7), V_i64(2));
    g_assert_no_error(err);
    g_assert_cmpint(g_variant_get_int64(r), ==, 3);
    g_variant_unref(r);
}

static void test_numeric_helpers(void) {
    g_assert_false(is_valid_numeric_type(NULL));
    GVariant *i = g_variant_ref_sink(V_i64(1));
    GVariant *u = g_variant_ref_sink(V_u64(1));
    GVariant *d = g_variant_ref_sink(V_d(1));
    GVariant *s = g_variant_ref_sink(V_s("1"));
    GVariant *b = g_variant_ref_sink(g_variant_new_boolean(TRUE));
    g_assert_true(is_valid_numeric_type(i));
    g_assert_true(is_valid_numeric_type(u));
    g_assert_true(is_valid_numeric_type(d));
    g_assert_false(is_valid_numeric_type(s));
    g_assert_false(is_valid_numeric_type(b));
    g_assert_cmpfloat(get_double_value(i), ==, 1.0);
    g_assert_cmpfloat(get_double_value(u), ==, 1.0);
    g_assert_cmpfloat(get_double_value(d), ==, 1.0);
    g_variant_unref(i);
    g_variant_unref(u);
    g_variant_unref(d);
    g_variant_unref(s);
    g_variant_unref(b);
}

/* ---- helper functions ---- */

static void test_lc_uc(void) {
    GError *err = NULL;
    assert_string_result(CALL(helperfn_lc, NULL, &err, V_s("HeLLo")), "hello");
    assert_string_result(CALL(helperfn_uc, NULL, &err, V_s("HeLLo")), "HELLO");
    assert_string_result(CALL(helperfn_lc, NULL, &err, V_i64(42)), "42");
    assert_string_result(CALL(helperfn_uc, NULL, &err, V_d(1.5)), "1.5");
    assert_string_result(CALL(helperfn_lc, NULL, &err, g_variant_new_boolean(TRUE)), "true");
    const gchar *strv[] = {"A", "B", NULL};
    assert_string_result(CALL(helperfn_lc, NULL, &err, g_variant_new_strv(strv, -1)), "a, b");
    assert_string_result(CALL(helperfn_uc, NULL, &err, g_variant_new_strv(strv, -1)), "A, B");
    assert_string_result(CALL(helperfn_lc, NULL, &err, (GVariant *)NULL), "");
    assert_string_result(CALL(helperfn_uc, NULL, &err, (GVariant *)NULL), "");
    assert_string_result(CALL(helperfn_uc, NULL, &err, V_s("ünï")), "ÜNÏ");
    g_assert_no_error(err);
}

static void test_lc_uc_wrong_nargs(void) {
    GError *err = NULL;
    GVariant *r = CALL(helperfn_lc, NULL, &err, V_s("a"), V_s("b"));
    assert_fails(r, err, "function lc takes exactly one argument*");
    err = NULL;
    r = CALL(helperfn_uc, NULL, &err, V_s("a"), V_s("b"));
    assert_fails(r, err, "function uc takes exactly one argument*");
    err = NULL;
    r = CALL(helperfn_markup_escape, NULL, &err, V_s("a"), V_s("b"));
    assert_fails(r, err, "function markup_escape takes exactly one argument*");
}

static void test_markup_escape(void) {
    GError *err = NULL;
    assert_string_result(CALL(helperfn_markup_escape, NULL, &err, V_s("<a&b>")), "&lt;a&amp;b&gt;");
    assert_string_result(CALL(helperfn_markup_escape, NULL, &err, V_i64(5)), "5");
    assert_string_result(CALL(helperfn_markup_escape, NULL, &err, (GVariant *)NULL), "");
    g_assert_no_error(err);

    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "title", "s", "Tom & \"Jerry\"");
    ASSERT_RENDERS("{{markup_escape(title)}}", ctx, "Tom &amp; &quot;Jerry&quot;");
    g_variant_dict_unref(ctx);
}

static void test_duration(void) {
    GError *err = NULL;
    assert_string_result(CALL(helperfn_duration, NULL, &err, V_i64(125000000)), "2:05");
    assert_string_result(CALL(helperfn_duration, NULL, &err, V_i64(0)), "0:00");
    assert_string_result(CALL(helperfn_duration, NULL, &err, V_i64(3725000000)), "1:02:05");
    assert_string_result(CALL(helperfn_duration, NULL, &err, V_u64(61000000)), "1:01");
    assert_string_result(CALL(helperfn_duration, NULL, &err, V_d(59000000.0)), "0:59");
    assert_string_result(CALL(helperfn_duration, NULL, &err, (GVariant *)NULL), "");
    g_assert_no_error(err);
}

static void test_duration_errors(void) {
    GError *err = NULL;
    GVariant *r = CALL(helperfn_duration, NULL, &err, V_s("12"));
    assert_fails(r, err, "function duration can only be called on track position values");
    err = NULL;
    r = CALL(helperfn_duration, NULL, &err, g_variant_new_boolean(TRUE));
    assert_fails(r, err, "*duration can only be called*");
}

static void test_duration_out_of_range(void) {
    /* Intended: a double outside the int64 range is an error. The cast is
     * undefined behaviour (UBSan flags it under `make test-asan`). */
    GError *err = NULL;
    GVariant *r = CALL(helperfn_duration, NULL, &err, V_d(1e300));
    assert_fails(r, err, "*duration*");
    err = NULL;
    r = CALL(helperfn_duration, NULL, &err, V_d(-1e300));
    assert_fails(r, err, "*duration*");
    err = NULL;
    r = CALL(helperfn_duration, NULL, &err, V_d(NAN));
    assert_fails(r, err, "*duration*");
    err = NULL;
    r = CALL(helperfn_duration, NULL, &err, V_d(INFINITY));
    assert_fails(r, err, "*duration*");
}

static void test_duration_wrong_nargs_message(void) {
    /* Intended: the message names the function that was misused (the code
     * copy-pasted "function uc"). */
    GError *err = NULL;
    GVariant *r = CALL(helperfn_duration, NULL, &err, V_i64(1), V_i64(2));
    assert_fails(r, err, "function duration takes exactly one argument*");
}

static void test_trunc(void) {
    GError *err = NULL;
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s("hello world"), V_d(5)), "hello…");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s("hi"), V_d(5)), "hi");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s("exact"), V_d(5)), "exact");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s("ünïcode"), V_d(3)), "ünï…");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_i64(123456), V_d(3)), "123…");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, (GVariant *)NULL, V_d(3)), "");
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s("a"), (GVariant *)NULL), "");
    g_assert_no_error(err);
}

static void test_trunc_long_string(void) {
    /* Intended: the ellipsis is added whenever text was cut, also for strings
     * longer than 256 characters (g_utf8_strlen(..., 256) caps the count). */
    gchar *input = g_strnfill(300, 'a');
    gchar *head = g_strnfill(280, 'a');
    gchar *expected = g_strconcat(head, "…", NULL);
    GError *err = NULL;
    assert_string_result(CALL(helperfn_trunc, NULL, &err, V_s(input), V_d(280)), expected);
    g_assert_no_error(err);
    g_free(input);
    g_free(head);
    g_free(expected);
}

static void test_trunc_negative_length(void) {
    /* Intended: a negative length is an error or an empty cut, never a
     * negative end position handed to g_utf8_substring (a g_critical). */
    GError *err = NULL;
    GVariant *r = CALL(helperfn_trunc, NULL, &err, V_s("hello"), V_d(-1));
    if (r != NULL) {
        g_assert_no_error(err);
        g_variant_unref(r);
    } else {
        g_assert_nonnull(err);
        g_error_free(err);
    }
}

static void test_trunc_errors(void) {
    GError *err = NULL;
    GVariant *r = CALL(helperfn_trunc, NULL, &err, V_s("abc"));
    assert_fails(r, err, "function trunc takes exactly two arguments*");
    err = NULL;
    r = CALL(helperfn_trunc, NULL, &err, V_s("abc"), V_i64(2));
    assert_fails(r, err, "*length parameter*");
    err = NULL;
    r = CALL(helperfn_trunc, NULL, &err, V_s("abc"), V_s("2"));
    assert_fails(r, err, "*length parameter*");
}

static void test_default(void) {
    GError *err = NULL;
    GVariant *r;

    r = CALL(helperfn_default, NULL, &err, (GVariant *)NULL, V_s("fallback"));
    assert_string_result(r, "fallback");
    r = CALL(helperfn_default, NULL, &err, V_s("value"), V_s("fallback"));
    assert_string_result(r, "value");
    r = CALL(helperfn_default, NULL, &err, V_s(""), V_s("fallback"));
    assert_string_result(r, "fallback");
    r = CALL(helperfn_default, NULL, &err, V_i64(0), V_s("fallback"));
    g_assert_true(g_variant_is_of_type(r, G_VARIANT_TYPE_INT64));
    g_variant_unref(r);
    r = CALL(helperfn_default, NULL, &err, (GVariant *)NULL, (GVariant *)NULL);
    g_assert_null(r);
    g_assert_no_error(err);

    r = CALL(helperfn_default, NULL, &err, V_s("a"));
    assert_fails(r, err, "function default takes exactly two arguments*");

    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDERS("{{default(album, \"Unknown\")}}", ctx, "Unknown");
    ASSERT_RENDERS("{{default(album, missing)}}", ctx, "");
    g_variant_dict_unref(ctx);
}

static void test_emoji_status_and_volume(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "status", "s", "Playing");
    ASSERT_RENDERS("{{emoji(status)}}", ctx, "▶️");
    g_variant_dict_insert(ctx, "status", "s", "Paused");
    ASSERT_RENDERS("{{emoji(status)}}", ctx, "⏸️");
    g_variant_dict_insert(ctx, "status", "s", "Stopped");
    ASSERT_RENDERS("{{emoji(status)}}", ctx, "⏹️");
    g_variant_dict_insert(ctx, "status", "s", "Weird");
    ASSERT_RENDERS("{{emoji(status)}}", ctx, "Weird");
    g_variant_dict_insert(ctx, "status", "x", (gint64)3);
    ASSERT_RENDERS("{{emoji(status)}}", ctx, "3");

    g_variant_dict_insert(ctx, "volume", "d", 0.1);
    ASSERT_RENDERS("{{emoji(volume)}}", ctx, "🔈");
    g_variant_dict_insert(ctx, "volume", "d", 0.5);
    ASSERT_RENDERS("{{emoji(volume)}}", ctx, "🔉");
    g_variant_dict_insert(ctx, "volume", "d", 0.9);
    ASSERT_RENDERS("{{emoji(volume)}}", ctx, "🔊");
    g_variant_dict_insert(ctx, "volume", "s", "loud");
    ASSERT_RENDERS("{{emoji(volume)}}", ctx, "loud");

    g_variant_dict_insert(ctx, "title", "s", "t");
    ASSERT_RENDERS("{{emoji(title)}}", ctx, "t");
    ASSERT_RENDERS("{{emoji(missing)}}", ctx, "");
    g_variant_dict_unref(ctx);
}

static void test_emoji_errors(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "status", "s", "Playing");
    ASSERT_RENDER_FAILS("{{emoji(\"Playing\")}}", ctx,
                        "*emoji function can only be called with a variable*");
    ASSERT_RENDER_FAILS("{{emoji(status, status)}}", ctx,
                        "function emoji takes exactly one argument*");
    g_variant_dict_unref(ctx);
}

static void test_emoji_direct_non_variable_token(void) {
    struct token *arg = token_create(TOKEN_STRING);
    arg->data = g_strdup("x");
    struct token *fn = token_create(TOKEN_FUNCTION);
    fn->args = g_list_append(NULL, arg);
    GError *err = NULL;
    GVariant *r = CALL(helperfn_emoji, fn, &err, V_s("Playing"));
    assert_fails(r, err, "*only be called with a variable*");
    token_destroy(fn);
}

/* ---- expand_token / expand_format error propagation ---- */

static void test_unknown_function(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDER_FAILS("{{nosuchfn(1)}}", ctx, "unknown template function: nosuchfn");
    ASSERT_RENDER_FAILS("text {{nosuchfn(\"a\", 2)}} more", ctx, "unknown template function*");
    g_variant_dict_unref(ctx);
}

static void test_error_propagates_from_nested_args(void) {
    GVariantDict *ctx = empty_ctx();
    ASSERT_RENDER_FAILS("{{lc(uc(1/0))}}", ctx, "*Divide by zero*");
    ASSERT_RENDER_FAILS("{{lc(nosuch(1))}}", ctx, "unknown template function*");
    ASSERT_RENDER_FAILS("before {{1/0}} after", ctx, "*Divide by zero*");
    ASSERT_RENDER_FAILS("{{ok}}{{duration(\"x\")}}", ctx, "*duration can only be called*");
    g_variant_dict_unref(ctx);
}

static void test_expand_token_directly(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "val");
    GError *err = NULL;

    struct token *num = token_create(TOKEN_NUMBER);
    num->numeric_data = 2.5;
    GVariant *r = expand_token(num, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpfloat(g_variant_get_double(g_variant_ref_sink(r)), ==, 2.5);
    g_variant_unref(r);
    token_destroy(num);

    struct token *var = token_create(TOKEN_VARIABLE);
    var->data = g_strdup("v");
    r = expand_token(var, ctx, &err);
    g_assert_cmpstr(g_variant_get_string(r, NULL), ==, "val");
    g_variant_unref(r);
    g_free(var->data);
    var->data = g_strdup("nope");
    g_assert_null(expand_token(var, ctx, &err));
    g_assert_no_error(err);
    token_destroy(var);

    g_variant_dict_unref(ctx);
}

static void test_expand_format_directly(void) {
    GVariantDict *ctx = empty_ctx();
    g_variant_dict_insert(ctx, "v", "s", "val");
    GError *err = NULL;
    g_assert_cmpstr(({
                        gchar *s = expand_format(NULL, ctx, &err);
                        s;
                    }),
                    ==, "");
    struct token *a = token_create(TOKEN_STRING);
    a->data = g_strdup("x=");
    struct token *b = token_create(TOKEN_VARIABLE);
    b->data = g_strdup("v");
    GList *l = g_list_append(g_list_append(NULL, a), b);
    gchar *s = expand_format(l, ctx, &err);
    g_assert_no_error(err);
    g_assert_cmpstr(s, ==, "x=val");
    g_free(s);
    token_list_destroy(l);
    g_variant_dict_unref(ctx);
}

static void test_value_printing_in_templates(void) {
    GVariantDict *ctx = empty_ctx();
    const gchar *artists[] = {"A", "B", NULL};
    g_variant_dict_insert_value(ctx, "artist", g_variant_new_strv(artists, -1));
    g_variant_dict_insert(ctx, "n", "x", (gint64)7);
    g_variant_dict_insert(ctx, "flag", "b", TRUE);
    ASSERT_RENDERS("{{artist}}|{{n}}|{{flag}}", ctx, "A, B|7|true");
    g_variant_dict_unref(ctx);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    g_test_set_nonfatal_assertions();
#define T(path, fn) g_test_add_data_func("/formatter/" path, (gconstpointer)fn, run_isolated)
    T("plain-text", test_plain_text);
    T("null-format", test_null_format);
    T("destroy-null", test_destroy_null);
    T("too-long", test_format_too_long);
    T("max-length-message", test_format_max_length_message);
    T("error-frees-buffer", test_expand_format_error_frees_buffer);
    T("variables", test_variables_and_whitespace);
    T("string-literals", test_string_literals);
    T("tokenizer-errors", test_tokenizer_errors);
    T("too-many-args", test_too_many_args);
    T("infix-to-identifier", test_infix_to_identifier);
    T("contains-key", test_contains_key);
    T("contains-key-unary-nested", test_contains_key_unary_and_nested_arith);
    T("contains-key-direct", test_token_list_contains_key_direct);
    T("arith/literals", test_arithmetic_literals);
    T("arith/variables", test_arithmetic_with_variables);
    T("arith/int64-multiplication", test_int64_multiplication);
    T("arith/int64-overflow", test_int64_overflow);
    T("arith/int64-add-min-min", test_int64_add_min_min);
    T("arith/int64-min-negation", test_int64_min_negation);
    T("arith/int64-min-div-minus-one", test_int64_min_div_minus_one);
    T("arith/divide-by-zero", test_divide_by_zero);
    T("arith/type-errors", test_arithmetic_type_errors);
    T("arith/null-operand-binary", test_arithmetic_null_operand_binary);
    T("arith/mul-null-operand", test_mul_null_operand);
    T("arith/div-null-operand", test_div_null_operand);
    T("arith/unary-add-null-operand", test_unary_add_null_operand);
    T("arith/unary-sub-null-operand", test_unary_sub_null_operand);
    T("arith/unary-sub-uint64", test_unary_sub_uint64);
    T("arith/wrong-nargs", test_infix_wrong_nargs);
    T("arith/direct-types", test_infix_direct_types);
    T("arith/numeric-helpers", test_numeric_helpers);
    T("fn/lc-uc", test_lc_uc);
    T("fn/lc-uc-wrong-nargs", test_lc_uc_wrong_nargs);
    T("fn/markup-escape", test_markup_escape);
    T("fn/duration", test_duration);
    T("fn/duration-errors", test_duration_errors);
    T("fn/duration-out-of-range", test_duration_out_of_range);
    T("fn/duration-wrong-nargs-message", test_duration_wrong_nargs_message);
    T("fn/trunc", test_trunc);
    T("fn/trunc-long-string", test_trunc_long_string);
    T("fn/trunc-negative-length", test_trunc_negative_length);
    T("fn/trunc-errors", test_trunc_errors);
    T("fn/default", test_default);
    T("fn/emoji", test_emoji_status_and_volume);
    T("fn/emoji-errors", test_emoji_errors);
    T("fn/emoji-direct-non-variable", test_emoji_direct_non_variable_token);
    T("expand/unknown-function", test_unknown_function);
    T("expand/error-propagation", test_error_propagates_from_nested_args);
    T("expand/token-direct", test_expand_token_directly);
    T("expand/format-direct", test_expand_format_directly);
    T("expand/value-printing", test_value_printing_in_templates);
#undef T
    return g_test_run();
}

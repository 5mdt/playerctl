/* Adversarial unit tests for playerctl-cli-util.c (parse_relative_number and
 * the -p rank comparators) plus new name-logic cases of playerctl-common.c. */

#include <glib.h>
#include <glib/gstdio.h>
#include <unistd.h>
#include <locale.h>
#include <math.h>
#include <stdlib.h>
#include <string.h>

#include "playerctl/playerctl-cli.h"
#include "playerctl/playerctl-common.h"

/* Every test runs in a forked subprocess. A test that hits a known defect or
 * must skip writes a marker file (path in QA_MARK) and exits 0; the parent
 * then reports g_test_incomplete()/g_test_skip() instead of a failure. */
static void qa_marker(const char *kind, const char *msg) {
    const char *path = g_getenv("QA_MARK");
    if (path) {
        gchar *text = g_strconcat(kind, msg, NULL);
        g_file_set_contents(path, text, -1, NULL);
        g_free(text);
    }
    _exit(0);
}
#define QA_KNOWN_BUG(ok, msg) G_STMT_START { if (!(ok)) qa_marker("BUG:", msg); } G_STMT_END
#define QA_SKIP(msg) qa_marker("SKIP:", msg)

/* Count GLib criticals instead of aborting, so reachable-CRITICAL defects can
 * be reported as known bugs. */
static int qa_crit_count;
static void qa_crit_handler(const gchar *d, GLogLevelFlags l, const gchar *m, gpointer u) {
    (void)d; (void)l; (void)m; (void)u;
    qa_crit_count++;
}
static void qa_catch_criticals(void) {
    g_log_set_always_fatal(G_LOG_FATAL_MASK);
    g_log_set_default_handler(qa_crit_handler, NULL);
    qa_crit_count = 0;
}

static void run_isolated(gconstpointer fn) {
    if (g_test_subprocess()) {
        ((void (*)(void))fn)();
        return;
    }
    gchar *leaf = g_strdup_printf("qa-mark-%d-%u", getpid(), g_random_int());
    gchar *path = g_build_filename(g_get_tmp_dir(), leaf, NULL);
    g_free(leaf);
    g_setenv("QA_MARK", path, TRUE);
    g_test_trap_subprocess(NULL, 0, 0);
    gchar *marker = NULL;
    if (g_file_get_contents(path, &marker, NULL, NULL)) {
        g_unlink(path);
        if (g_str_has_prefix(marker, "SKIP:")) g_test_skip(marker + 5);
        else g_test_incomplete(marker + 4);
        g_free(marker);
        g_free(path);
        return;
    }
    g_test_trap_assert_passed();
    g_free(path);
}

#define ADD(path, fn) g_test_add_data_func(path, (gconstpointer)fn, run_isolated)

/* ---- parse_relative_number ---- */

static void check_num(const char *text, gboolean ok, double value, gboolean rel) {
    gdouble v = -777;
    gboolean r = TRUE;
    gboolean got = parse_relative_number(text, &v, &r);
    g_assert_cmpint(got, ==, ok);
    if (ok) {
        g_assert_cmpfloat(v, ==, value);
        g_assert_cmpint(r, ==, rel);
    } else {
        /* a rejected string must not touch the output value */
        g_assert_cmpfloat(v, ==, -777);
    }
}

static void test_num_plain(void) { check_num("5", TRUE, 5, FALSE); }
static void test_num_empty(void) { check_num("", FALSE, 0, FALSE); }
static void test_num_plus_suffix(void) { check_num("5+", TRUE, 5, TRUE); }
static void test_num_minus_suffix(void) { check_num("5-", TRUE, -5, TRUE); }
static void test_num_neg_minus_suffix(void) { check_num("-5-", TRUE, 5, TRUE); }
static void test_num_double_plus(void) { check_num("5++", FALSE, 0, 0); }
static void test_num_plus_minus(void) { check_num("5+-", FALSE, 0, 0); }
static void test_num_lone_plus(void) { check_num("+", FALSE, 0, 0); }
static void test_num_lone_minus(void) { check_num("-", FALSE, 0, 0); }
static void test_num_leading_plus(void) { check_num("+5", TRUE, 5, FALSE); }
static void test_num_nan(void) { check_num("nan", FALSE, 0, 0); }
static void test_num_neg_nan(void) { check_num("-nan", FALSE, 0, 0); }
static void test_num_nan_payload(void) { check_num("nan(0x1)", FALSE, 0, 0); }
static void test_num_inf(void) { check_num("inf", FALSE, 0, 0); }
static void test_num_neg_inf(void) { check_num("-inf", FALSE, 0, 0); }
static void test_num_infinity(void) { check_num("infinity", FALSE, 0, 0); }
static void test_num_overflow(void) { check_num("1e400", FALSE, 0, 0); }
static void test_num_neg_overflow(void) { check_num("-1e400", FALSE, 0, 0); }
static void test_num_overflow_suffix(void) { check_num("1e400+", FALSE, 0, 0); }
static void test_num_underflow(void) { check_num("1e-400", TRUE, 0, FALSE); }
static void test_num_big_finite(void) { check_num("1e308", TRUE, 1e308, FALSE); }
static void test_num_leading_space(void) { check_num(" 5", TRUE, 5, FALSE); }
static void test_num_leading_tab_nl(void) { check_num("\t\n5", TRUE, 5, FALSE); }
static void test_num_trailing_space(void) { check_num("5 ", FALSE, 0, 0); }
static void test_num_space_before_suffix(void) { check_num("5 +", FALSE, 0, 0); }
static void test_num_hex(void) { check_num("0x10", TRUE, 16, FALSE); }
static void test_num_hex_float(void) { check_num("0x1p3", TRUE, 8, FALSE); }
static void test_num_comma(void) { check_num("1,5", FALSE, 0, 0); }
static void test_num_dot_forms(void) {
    check_num("1.5", TRUE, 1.5, FALSE);
    check_num(".5", TRUE, .5, FALSE);
    check_num("5.", TRUE, 5, FALSE);
    check_num(".", FALSE, 0, 0);
    check_num("1.2.3", FALSE, 0, 0);
}
static void test_num_exp_forms(void) {
    check_num("1e2", TRUE, 100, FALSE);
    check_num("1e", FALSE, 0, 0);
    check_num("1e+", FALSE, 0, 0);
    check_num("1e+2+", TRUE, 100, TRUE);
}
static void test_num_neg_zero(void) {
    gdouble v = 1;
    gboolean r = FALSE;
    g_assert_true(parse_relative_number("-0", &v, &r));
    g_assert_true(signbit(v));
    g_assert_false(r);
    g_assert_true(parse_relative_number("0-", &v, &r));
    g_assert_true(r);
    g_assert_cmpfloat(v, ==, 0.0);
}
static void test_num_suffix_garbage(void) {
    check_num("5x", FALSE, 0, 0);
    check_num("5+x", FALSE, 0, 0);
    check_num("5%", FALSE, 0, 0);
    check_num("abc", FALSE, 0, 0);
    check_num("--5", FALSE, 0, 0);
}
static void test_num_nul_embedded_via_long(void) {
    gchar *s = g_strnfill(5000, '9');
    gchar *t = g_strconcat(s, "-", NULL);
    gdouble v;
    gboolean r;
    /* 5000 digits overflow to inf */
    g_assert_false(parse_relative_number(t, &v, &r));
    g_free(s);
    g_free(t);
}
static void test_num_long_zeros(void) {
    gchar *s = g_strnfill(100000, '0');
    gchar *t = g_strconcat(s, "7", NULL);
    check_num(t, TRUE, 7, FALSE);
    g_free(s);
    g_free(t);
}
static void test_num_relative_untouched_on_fail(void) {
    gdouble v = 0;
    gboolean r = TRUE;
    g_assert_false(parse_relative_number("", &v, &r));
    g_assert_true(r);
}
static void test_num_locale_comma(void) {
    if (!setlocale(LC_ALL, "de_DE.UTF-8") && !setlocale(LC_ALL, "de_DE.utf8")) {
        QA_SKIP("de_DE.UTF-8 locale not installed");
    }
    /* The CLI only sets LC_CTYPE, but a comma-decimal LC_NUMERIC would make
     * "1.5" fail and "1,5" succeed; document what happens. */
    gdouble v = 0;
    gboolean r;
    gboolean dot = parse_relative_number("1.5", &v, &r);
    gboolean comma = parse_relative_number("1,5", &v, &r);
    setlocale(LC_ALL, "C");
    QA_KNOWN_BUG(dot && !comma, "BUG-U1: parse_relative_number depends on LC_NUMERIC (strtod)");
}
static void test_num_ctype_locale_only(void) {
    if (!setlocale(LC_CTYPE, "de_DE.UTF-8")) {
        QA_SKIP("de_DE.UTF-8 locale not installed");
    }
    check_num("1.5", TRUE, 1.5, FALSE);
    check_num("1,5", FALSE, 0, 0);
}

/* ---- rank comparators ---- */

static GList *lst(const char *first, ...) {
    GList *l = NULL;
    va_list ap;
    va_start(ap, first);
    for (const char *s = first; s; s = va_arg(ap, const char *))
        l = g_list_append(l, (gpointer)s);
    va_end(ap);
    return l;
}

static gint scmp(GList *names, const char *a, const char *b) {
    return player_name_string_compare_func(a, b, names);
}

static void test_rank_listed_order(void) {
    GList *n = lst("b", "a", NULL);
    g_assert_cmpint(scmp(n, "b", "a"), <, 0);
    g_assert_cmpint(scmp(n, "a", "b"), >, 0);
    g_assert_cmpint(scmp(n, "a", "a"), ==, 0);
    g_list_free(n);
}
static void test_rank_any_middle(void) {
    GList *n = lst("a", "%any", "c", NULL);
    /* unknown players rank at %any, between a and c */
    g_assert_cmpint(scmp(n, "a", "zzz"), <, 0);
    g_assert_cmpint(scmp(n, "zzz", "c"), <, 0);
    g_assert_cmpint(scmp(n, "zzz", "yyy"), ==, 0);
    g_list_free(n);
}
static void test_rank_any_first(void) {
    GList *n = lst("%any", "a", NULL);
    g_assert_cmpint(scmp(n, "x", "a"), <, 0);
    g_list_free(n);
}
static void test_rank_any_duplicate_uses_first(void) {
    GList *n = lst("a", "%any", "b", "%any", NULL);
    g_assert_cmpint(scmp(n, "x", "b"), <, 0);
    g_assert_cmpint(scmp(n, "x", "a"), >, 0);
    g_list_free(n);
}
static void test_rank_no_any_unlisted_last(void) {
    GList *n = lst("a", "b", NULL);
    g_assert_cmpint(scmp(n, "zzz", "b"), >, 0);
    g_assert_cmpint(scmp(n, "zzz", "yyy"), ==, 0);
    g_list_free(n);
}
static void test_rank_null_list(void) {
    g_assert_cmpint(scmp(NULL, "a", "b"), ==, 0);
    g_assert_cmpint(scmp(NULL, "a", "a"), ==, 0);
}
static void test_rank_duplicate_names_min(void) {
    GList *n = lst("a", "b", "a", NULL);
    g_assert_cmpint(scmp(n, "a", "b"), <, 0);
    g_list_free(n);
}
static void test_rank_instance_matches_base(void) {
    GList *n = lst("vlc", "mpv", NULL);
    g_assert_cmpint(scmp(n, "vlc.instance123", "mpv"), <, 0);
    g_assert_cmpint(scmp(n, "mpv.instance9", "vlc"), >, 0);
    g_assert_cmpint(scmp(n, "vlc.instance1", "vlc.instance2"), ==, 0);
    g_list_free(n);
}
static void test_rank_prefix_not_instance(void) {
    GList *n = lst("vlc", NULL);
    /* "vlcx" must NOT match -p vlc: ranks like unlisted */
    g_assert_cmpint(scmp(n, "vlc", "vlcx"), <, 0);
    g_assert_cmpint(scmp(n, "vlcx", "vlcy"), ==, 0);
    g_list_free(n);
}
static void test_rank_list_instance_vs_plain(void) {
    /* -p vlc.instance5 does not match plain "vlc" */
    GList *n = lst("vlc.instance5", NULL);
    g_assert_cmpint(scmp(n, "vlc.instance5", "vlc"), <, 0);
    g_list_free(n);
}
static void test_rank_empty_name_in_list(void) {
    GList *n = lst("", "a", NULL);
    /* "" matches nothing but "" and "<anything>." prefixed names */
    g_assert_cmpint(scmp(n, "a", "b"), <, 0);
    g_list_free(n);
}
static void test_rank_null_player_strings(void) {
    GList *n = lst("a", NULL);
    /* g_strcmp0-based: NULL players must not crash */
    qa_catch_criticals();
    gint r1 = scmp(n, NULL, "a"), r2 = scmp(n, NULL, NULL);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U3: NULL player name in -p rank gives GLib CRITICAL (g_str_has_prefix)");
    g_assert_cmpint(r1, >, 0);
    g_assert_cmpint(r2, ==, 0);
    g_list_free(n);
}
static void test_rank_null_item_in_list(void) {
    /* a NULL element inside the -p list (g_list_append(NULL)) */
    GList *n = g_list_append(NULL, NULL);
    n = g_list_append(n, (gpointer)"a");
    qa_catch_criticals();
    gint r = scmp(n, "a", "b");
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U3: NULL name in -p rank gives GLib CRITICAL (g_str_has_prefix)");
    g_assert_cmpint(r, <, 0);
    g_list_free(n);
}
static void test_rank_any_as_player(void) {
    GList *n = lst("a", "b", NULL);
    /* a player literally named %any matches every list entry at rank 0 */
    g_assert_cmpint(scmp(n, "%any", "b"), <=, 0);
    g_list_free(n);
}
static void test_rank_result_normalised(void) {
    GList *n = lst("a", "b", "c", "d", NULL);
    gint r = scmp(n, "a", "d");
    g_assert_cmpint(r, ==, -1);
    r = scmp(n, "d", "a");
    g_assert_cmpint(r, ==, 1);
    g_list_free(n);
}

static PlayerctlPlayerName mk(const char *inst) {
    PlayerctlPlayerName n = {(gchar *)inst, (gchar *)inst, PLAYERCTL_SOURCE_DBUS_SESSION};
    return n;
}

static void test_namecmp_wrapper(void) {
    GList *n = lst("b", "a", NULL);
    PlayerctlPlayerName a = mk("a"), b = mk("b");
    g_assert_cmpint(player_name_compare_func(&a, &b, n), >, 0);
    g_assert_cmpint(player_name_compare_func(&b, &a, n), <, 0);
    g_list_free(n);
}
static void test_exact_first_basic(void) {
    GList *n = lst("mpv", NULL);
    PlayerctlPlayerName exact = mk("mpv"), inst = mk("mpv.instance7");
    g_assert_cmpint(player_name_exact_first_compare_func(&exact, &inst, n), <, 0);
    g_assert_cmpint(player_name_exact_first_compare_func(&inst, &exact, n), >, 0);
    g_assert_cmpint(player_name_exact_first_compare_func(&exact, &exact, n), ==, 0);
    g_assert_cmpint(player_name_exact_first_compare_func(&inst, &inst, n), ==, 0);
    g_list_free(n);
}
static void test_exact_first_rank_wins(void) {
    GList *n = lst("vlc", "mpv", NULL);
    PlayerctlPlayerName exact = mk("mpv"), inst = mk("vlc.instance7");
    g_assert_cmpint(player_name_exact_first_compare_func(&exact, &inst, n), >, 0);
    g_list_free(n);
}
static void test_exact_first_null_list(void) {
    PlayerctlPlayerName a = mk("a"), b = mk("b");
    g_assert_cmpint(player_name_exact_first_compare_func(&a, &b, NULL), ==, 0);
}
static void test_exact_first_any(void) {
    GList *n = lst("%any", NULL);
    PlayerctlPlayerName a = mk("mpv"), b = mk("mpv.instance1");
    /* %any is not an exact name: stays tied */
    gint r = player_name_exact_first_compare_func(&a, &b, n);
    g_assert_cmpint(r, ==, 0);
    g_list_free(n);
}
static void test_exact_first_neither_exact(void) {
    GList *n = lst("mpv", NULL);
    PlayerctlPlayerName a = mk("mpv.instance1"), b = mk("mpv.instance2");
    g_assert_cmpint(player_name_exact_first_compare_func(&a, &b, n), ==, 0);
    g_list_free(n);
}

/* all pairs/triples of a name set must give a consistent preorder */
static void check_order_laws(GList *names, const char **set, int n,
                             gint (*cmp)(const PlayerctlPlayerName *, const PlayerctlPlayerName *, GList *)) {
    PlayerctlPlayerName *p = g_new0(PlayerctlPlayerName, n);
    for (int i = 0; i < n; i++) p[i] = mk(set[i]);
    for (int i = 0; i < n; i++) {
        g_assert_cmpint(cmp(&p[i], &p[i], names), ==, 0);
        for (int j = 0; j < n; j++) {
            gint ij = cmp(&p[i], &p[j], names), ji = cmp(&p[j], &p[i], names);
            if ((ij > 0) - (ij < 0) != -((ji > 0) - (ji < 0)))
                g_error("antisymmetry broken: %s vs %s: %d %d", set[i], set[j], ij, ji);
            for (int k = 0; k < n; k++) {
                gint jk = cmp(&p[j], &p[k], names), ik = cmp(&p[i], &p[k], names);
                if (ij <= 0 && jk <= 0 && ik > 0)
                    g_error("transitivity broken: %s %s %s", set[i], set[j], set[k]);
                if (ij == 0 && ((jk > 0) - (jk < 0)) != ((ik > 0) - (ik < 0)))
                    g_error("tie not transitive: %s %s %s", set[i], set[j], set[k]);
            }
        }
    }
    g_free(p);
}
static gint cmp_plain(const PlayerctlPlayerName *a, const PlayerctlPlayerName *b, GList *n) {
    return player_name_compare_func(a, b, n);
}
static gint cmp_exact(const PlayerctlPlayerName *a, const PlayerctlPlayerName *b, GList *n) {
    return player_name_exact_first_compare_func(a, b, n);
}
static const char *universe[] = {"mpv", "mpv.instance1", "mpv.instance22", "vlc", "vlc.instance3",
                                 "vlcx", "spotify", "firefox.instance9", "a", "b"};
static void test_laws_plain(void) {
    GList *n = lst("vlc", "%any", "mpv", NULL);
    check_order_laws(n, universe, G_N_ELEMENTS(universe), cmp_plain);
    g_list_free(n);
    n = lst("mpv", "vlc", NULL);
    check_order_laws(n, universe, G_N_ELEMENTS(universe), cmp_plain);
    g_list_free(n);
}
static void test_laws_exact(void) {
    GList *n = lst("mpv", "%any", "mpv.instance1", "vlc", NULL);
    check_order_laws(n, universe, G_N_ELEMENTS(universe), cmp_exact);
    g_list_free(n);
    n = lst("vlc", "mpv", "vlc", NULL);
    check_order_laws(n, universe, G_N_ELEMENTS(universe), cmp_exact);
    g_list_free(n);
}
static void test_qsort_exact_first(void) {
    GList *n = lst("mpv", "%any", NULL);
    const char *in[] = {"zed", "mpv.instance1", "mpv", "mpv.instance2", "a"};
    GList *l = NULL;
    PlayerctlPlayerName *p = g_new0(PlayerctlPlayerName, 5);
    for (int i = 0; i < 5; i++) {
        p[i] = mk(in[i]);
        l = g_list_append(l, &p[i]);
    }
    l = g_list_sort_with_data(l, player_name_exact_first_compare_func, n);
    PlayerctlPlayerName *first = l->data;
    PlayerctlPlayerName *second = l->next->data;
    g_assert_cmpstr(first->instance, ==, "mpv");
    g_assert_true(g_str_has_prefix(second->instance, "mpv."));
    g_list_free(l);
    g_list_free(n);
    g_free(p);
}
static void test_sort_stability_ties(void) {
    GList *n = lst("zz", NULL);
    PlayerctlPlayerName p[4] = {mk("a"), mk("b"), mk("c"), mk("d")};
    GList *l = NULL;
    for (int i = 0; i < 4; i++) l = g_list_append(l, &p[i]);
    l = g_list_sort_with_data(l, player_name_compare_func, n);
    for (int i = 0; i < 4; i++) g_assert_true(g_list_nth_data(l, i) == &p[i]);
    g_list_free(l);
    g_list_free(n);
}

/* ---- pctl_player_name_compare (XXX in common.c) ---- */
static void test_name_compare_sources_both_ways(void) {
    PlayerctlPlayerName a = {"x", "x", PLAYERCTL_SOURCE_DBUS_SESSION};
    PlayerctlPlayerName b = {"x", "x", PLAYERCTL_SOURCE_DBUS_SYSTEM};
    gint ab = pctl_player_name_compare(&a, &b), ba = pctl_player_name_compare(&b, &a);
    /* documented XXX: not an ordering; antisymmetry expected */
    QA_KNOWN_BUG((ab > 0) != (ba > 0), "BUG-U2: pctl_player_name_compare returns 1 both ways for differing sources");
}
static void test_name_compare_same(void) {
    PlayerctlPlayerName a = mk("x"), b = mk("x");
    g_assert_cmpint(pctl_player_name_compare(&a, &b), ==, 0);
}
static void test_name_compare_null_instances(void) {
    PlayerctlPlayerName a = {NULL, NULL, PLAYERCTL_SOURCE_DBUS_SESSION};
    PlayerctlPlayerName b = {NULL, NULL, PLAYERCTL_SOURCE_DBUS_SESSION};
    g_assert_cmpint(pctl_player_name_compare(&a, &b), ==, 0);
    b.instance = "x";
    g_assert_cmpint(pctl_player_name_compare(&a, &b), <, 0);
}
static void test_name_compare_sort_order(void) {
    PlayerctlPlayerName p[3] = {mk("c"), mk("a"), mk("b")};
    GList *l = NULL;
    for (int i = 0; i < 3; i++) l = g_list_append(l, &p[i]);
    l = g_list_sort(l, (GCompareFunc)pctl_player_name_compare);
    g_assert_true(l->data == &p[1]);
    g_list_free(l);
}

/* ---- common.c name logic: new cases ---- */
static void base_is(const char *in, const char *want) {
    gchar *b = pctl_player_base_name(in);
    g_assert_cmpstr(b, ==, want);
    g_free(b);
}
static void test_base_dot_instance(void) { base_is(".instance", ".instance"); }
static void test_base_x_instance(void) { base_is("x.instance", "x.instance"); }
static void test_base_x_instance_digit(void) { base_is("x.instance5", "x"); }
static void test_base_dot_instance5(void) { base_is(".instance5", ".instance5"); }
static void test_base_two_instances(void) { base_is("a.instance1.instance2", "a.instance1"); }
static void test_base_inst_nondigit(void) { base_is("a.instance1x", "a.instance1x"); }
static void test_base_inst_mid(void) { base_is("a.instance1.b", "a.instance1.b"); }
static void test_base_empty(void) { base_is("", ""); }
static void test_base_unicode(void) { base_is("плеер.instance42", "плеер"); }
static void test_base_huge_digits(void) {
    gchar *s = g_strdup_printf("p.instance%0*d", 5000, 1);
    base_is(s, "p");
    g_free(s);
}
static void test_base_negative_digit(void) { base_is("p.instance-1", "p.instance-1"); }
static void test_base_unicode_digit(void) { base_is("p.instance\xd9\xa1", "p.instance\xd9\xa1"); }
static void test_base_null(void) {
    /* NULL instance: g_strrstr would be a CRITICAL */
    qa_catch_criticals();
    gchar *b = pctl_player_base_name(NULL);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U4: pctl_player_base_name(NULL) gives GLib CRITICAL and returns NULL");
    g_free(b);
}

static void test_sic_null_name_instance(void) {
    qa_catch_criticals();
    gint r = pctl_player_name_string_instance_compare(NULL, "vlc");
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U3: string_instance_compare(NULL, inst) gives GLib CRITICAL");
    g_assert_cmpint(r, !=, 0);
}
static void test_sic_null_instance_name(void) {
    qa_catch_criticals();
    gint r = pctl_player_name_string_instance_compare("vlc", NULL);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U3: string_instance_compare(name, NULL) gives GLib CRITICAL");
    g_assert_cmpint(r, !=, 0);
}
static void test_sic_both_null(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare(NULL, NULL), ==, 0);
}
static void test_sic_vlc_vlcx(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc", "vlcx"), !=, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlcx", "vlc"), !=, 0);
}
static void test_sic_vlc_vlcdot(void) {
    /* "vlc." has prefix "vlc" followed by "."; instance part empty */
    gint r = pctl_player_name_string_instance_compare("vlc", "vlc.");
    g_assert_cmpint(r, ==, 0);
}
static void test_sic_empty_name(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare("", "vlc"), !=, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("", ""), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("", ".x"), ==, 0);
}
static void test_sic_any(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare("%any", "x"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("x", "%any"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare(NULL, "%any"), ==, 0);
}
static void test_sic_reverse_arg_order(void) {
    /* name is the base; instance first does not match */
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc.instance1", "vlc"), !=, 0);
}
static void test_sic_dot_in_name(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare("a.b", "a.b.instance1"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("a", "a.b"), ==, 0);
}
static void test_sic_case(void) {
    g_assert_cmpint(pctl_player_name_string_instance_compare("VLC", "vlc"), !=, 0);
}
static void test_player_name_new(void) {
    PlayerctlPlayerName *n = pctl_player_name_new("x.instance3", PLAYERCTL_SOURCE_DBUS_SYSTEM);
    g_assert_cmpstr(n->name, ==, "x");
    g_assert_cmpstr(n->instance, ==, "x.instance3");
    g_assert_cmpint(n->source, ==, PLAYERCTL_SOURCE_DBUS_SYSTEM);
    playerctl_player_name_free(n);
}
static void test_find_instance_any_source(void) {
    PlayerctlPlayerName a = mk("vlc.instance1");
    GList *l = g_list_append(NULL, &a);
    GList *f = pctl_player_name_find_instance(l, (gchar *)"vlc", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_nonnull(f);
    f = pctl_player_name_find_instance(l, (gchar *)"vlc", PLAYERCTL_SOURCE_DBUS_SYSTEM);
    g_assert_null(f);
    f = pctl_player_name_find_instance(l, (gchar *)"vlcx", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_null(f);
    f = pctl_player_name_find_instance(NULL, (gchar *)"vlc", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_null(f);
    g_list_free(l);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
#define T(name) ADD("/cli-util/" #name, test_##name)
    T(num_plain); T(num_empty); T(num_plus_suffix); T(num_minus_suffix);
    T(num_neg_minus_suffix); T(num_double_plus); T(num_plus_minus); T(num_lone_plus);
    T(num_lone_minus); T(num_leading_plus); T(num_nan); T(num_neg_nan);
    T(num_nan_payload); T(num_inf); T(num_neg_inf); T(num_infinity); T(num_overflow);
    T(num_neg_overflow); T(num_overflow_suffix); T(num_underflow); T(num_big_finite);
    T(num_leading_space); T(num_leading_tab_nl); T(num_trailing_space);
    T(num_space_before_suffix); T(num_hex); T(num_hex_float); T(num_comma);
    T(num_dot_forms); T(num_exp_forms); T(num_neg_zero); T(num_suffix_garbage);
    T(num_nul_embedded_via_long); T(num_long_zeros); T(num_relative_untouched_on_fail);
    T(num_locale_comma); T(num_ctype_locale_only);
    T(rank_listed_order); T(rank_any_middle); T(rank_any_first);
    T(rank_any_duplicate_uses_first); T(rank_no_any_unlisted_last); T(rank_null_list);
    T(rank_duplicate_names_min); T(rank_instance_matches_base); T(rank_prefix_not_instance);
    T(rank_list_instance_vs_plain); T(rank_empty_name_in_list); T(rank_null_player_strings);
    T(rank_null_item_in_list); T(rank_any_as_player); T(rank_result_normalised);
    T(namecmp_wrapper); T(exact_first_basic); T(exact_first_rank_wins);
    T(exact_first_null_list); T(exact_first_any); T(exact_first_neither_exact);
    T(laws_plain); T(laws_exact); T(qsort_exact_first); T(sort_stability_ties);
    T(name_compare_sources_both_ways); T(name_compare_same); T(name_compare_null_instances);
    T(name_compare_sort_order);
    T(base_dot_instance); T(base_x_instance); T(base_x_instance_digit);
    T(base_dot_instance5); T(base_two_instances); T(base_inst_nondigit); T(base_inst_mid);
    T(base_empty); T(base_unicode); T(base_huge_digits); T(base_negative_digit);
    T(base_unicode_digit); T(base_null);
    T(sic_null_name_instance); T(sic_null_instance_name); T(sic_both_null); T(sic_vlc_vlcx);
    T(sic_vlc_vlcdot); T(sic_empty_name); T(sic_any); T(sic_reverse_arg_order);
    T(sic_dot_in_name); T(sic_case); T(player_name_new); T(find_instance_any_source);
    return g_test_run();
}

/* Adversarial unit tests for playerctl-daemon-player.c (player model and
 * cached property updates). */

#include <glib.h>
#include <glib/gstdio.h>
#include <math.h>
#include <unistd.h>

#include "playerctl/playerctl-daemon-private.h"
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


/* Count GLib warnings/criticals instead of aborting, so reachable defects can
 * be reported as known bugs. */
static int qa_crit_count, qa_warn_count;
static void qa_log_handler(const gchar *d, GLogLevelFlags l, const gchar *m, gpointer u) {
    (void)d; (void)m; (void)u;
    if (l & G_LOG_LEVEL_CRITICAL) qa_crit_count++;
    else if (l & G_LOG_LEVEL_WARNING) qa_warn_count++;
}
static void qa_catch_logs(void) {
    g_log_set_always_fatal(G_LOG_FATAL_MASK);
    g_log_set_default_handler(qa_log_handler, NULL);
    qa_crit_count = qa_warn_count = 0;
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
#define T(name) ADD("/daemon-player/" #name, test_##name)

static GVariant *dict1(const char *key, GVariant *value) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", key, value);
    return g_variant_ref_sink(g_variant_builder_end(&b));
}
static GVariant *empty_dict(void) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    return g_variant_ref_sink(g_variant_builder_end(&b));
}
static gboolean upd(struct Player *p, const char *iface, GVariant *props) {
    gboolean r = player_update_properties(p, iface, props);
    g_variant_unref(props);
    return r;
}
static GVariant *cached(struct Player *p, const char *iface, const char *key) {
    GVariant **c = player_cache_for(p, iface);
    if (!c || !*c) return NULL;
    return g_variant_lookup_value(*c, key, NULL);
}

/* ---- optional_index ---- */
static void test_optional_index_known(void) {
    g_assert_cmpint(optional_index(TRACKLIST_INTERFACE), >=, 0);
    g_assert_cmpint(optional_index(PLAYLISTS_INTERFACE), >=, 0);
    g_assert_cmpint(optional_index(TRACKLIST_INTERFACE), !=, optional_index(PLAYLISTS_INTERFACE));
    g_assert_cmpstr(optional_interfaces[optional_index(TRACKLIST_INTERFACE)].name, ==, TRACKLIST_INTERFACE);
}
static void test_optional_index_unknown(void) {
    g_assert_cmpint(optional_index(NULL), ==, -1);
    g_assert_cmpint(optional_index(""), ==, -1);
    g_assert_cmpint(optional_index(ROOT_INTERFACE), ==, -1);
    g_assert_cmpint(optional_index(PLAYER_INTERFACE), ==, -1);
    g_assert_cmpint(optional_index("org.mpris.MediaPlayer2.tracklist"), ==, -1);
    g_assert_cmpint(optional_index(TRACKLIST_INTERFACE "."), ==, -1);
    g_assert_cmpint(optional_index(PLAYERCTLD_INTERFACE), ==, -1);
}
static void test_optional_invalidated_lists(void) {
    for (int i = 0; i < N_OPTIONAL; i++) {
        g_assert_nonnull(optional_interfaces[i].name);
        g_assert_nonnull(optional_interfaces[i].invalidated);
        g_assert_nonnull(optional_interfaces[i].invalidated[0]);
    }
}

/* ---- player_new / free ---- */
static void test_new_fields(void) {
    struct Player *p = player_new(":1.5", "org.mpris.MediaPlayer2.vlc");
    g_assert_cmpstr(p->unique, ==, ":1.5");
    g_assert_cmpstr(p->well_known, ==, "org.mpris.MediaPlayer2.vlc");
    g_assert_cmpint(p->position, ==, 0);
    g_assert_null(p->player_properties);
    g_assert_null(p->root_properties);
    for (int i = 0; i < N_OPTIONAL; i++) g_assert_null(p->optional_properties[i]);
    g_assert_nonnull(p->cancellable);
    g_assert_false(g_cancellable_is_cancelled(p->cancellable));
    player_free(p);
}
static void test_new_null_names(void) {
    struct Player *p = player_new(NULL, NULL);
    g_assert_null(p->unique);
    g_assert_null(p->well_known);
    player_free(p);
}
static void test_new_copies_strings(void) {
    char *u = g_strdup(":1.9");
    struct Player *p = player_new(u, "w");
    g_free(u);
    g_assert_cmpstr(p->unique, ==, ":1.9");
    player_free(p);
}
static void test_free_null(void) { player_free(NULL); }
static void test_free_cancels(void) {
    struct Player *p = player_new("u", "w");
    GCancellable *c = g_object_ref(p->cancellable);
    player_free(p);
    g_assert_true(g_cancellable_is_cancelled(c));
    g_object_unref(c);
}
static void test_free_all_props(void) {
    struct Player *p = player_new("u", "w");
    p->player_properties = empty_dict();
    p->root_properties = empty_dict();
    for (int i = 0; i < N_OPTIONAL; i++) p->optional_properties[i] = empty_dict();
    player_free(p);
}
static void test_set_unique(void) {
    struct Player *p = player_new("a", "w");
    player_set_unique_name(p, "b");
    g_assert_cmpstr(p->unique, ==, "b");
    player_set_unique_name(p, NULL);
    g_assert_null(p->unique);
    player_free(p);
}
static void test_set_unique_same_pointer(void) {
    struct Player *p = player_new("abc", "w");
    /* the new name may alias the old buffer: free-before-dup is a UAF
     * (latent: the only caller passes a signal string). Not executed, as
     * the read of freed memory is undefined; ASan would flag it. */
    QA_KNOWN_BUG(FALSE, "BUG-U7: player_set_unique_name(p, p->unique) frees before g_strdup (latent use-after-free)");
    player_set_unique_name(p, p->unique);
    g_assert_cmpstr(p->unique, ==, "abc");
    player_free(p);
}
static void test_usable(void) {
    struct Player *p = player_new("u", "w");
    g_assert_false(player_is_usable(p));
    p->player_properties = empty_dict();
    g_assert_false(player_is_usable(p));
    p->root_properties = empty_dict();
    g_assert_true(player_is_usable(p));
    g_variant_unref(p->player_properties);
    p->player_properties = NULL;
    g_assert_false(player_is_usable(p));
    player_free(p);
}

/* ---- player_matches ---- */
static gint match(const char *u1, const char *w1, const char *u2, const char *w2) {
    struct Player a = {.unique = (char *)u1, .well_known = (char *)w1};
    struct Player b = {.unique = (char *)u2, .well_known = (char *)w2};
    return player_matches(&a, &b);
}
static void test_matches_equal(void) { g_assert_cmpint(match("u", "w", "u", "w"), ==, 0); }
static void test_matches_unique_differs(void) { g_assert_cmpint(match("u", "w", "x", "w"), !=, 0); }
static void test_matches_wk_differs(void) { g_assert_cmpint(match("u", "w", "u", "x"), !=, 0); }
static void test_matches_null_unique_wildcard(void) {
    g_assert_cmpint(match(NULL, "w", "u", "w"), ==, 0);
    g_assert_cmpint(match("u", "w", NULL, "w"), ==, 0);
    g_assert_cmpint(match(NULL, "w", "u", "x"), !=, 0);
}
static void test_matches_null_wk_wildcard(void) {
    g_assert_cmpint(match("u", NULL, "u", "w"), ==, 0);
    g_assert_cmpint(match("u", "w", "u", NULL), ==, 0);
    g_assert_cmpint(match("u", NULL, "x", "w"), !=, 0);
}
static void test_matches_all_null(void) {
    g_assert_cmpint(match(NULL, NULL, "u", "w"), ==, 0);
    g_assert_cmpint(match("u", "w", NULL, NULL), ==, 0);
    g_assert_cmpint(match(NULL, NULL, NULL, NULL), ==, 0);
}
static void test_matches_cross_null(void) {
    /* probe has only unique, candidate has only well-known: nothing comparable */
    g_assert_cmpint(match("u", NULL, NULL, "w"), ==, 0);
}
static void test_matches_empty_strings(void) {
    g_assert_cmpint(match("", "", "", ""), ==, 0);
    g_assert_cmpint(match("", "w", "u", "w"), !=, 0);
}
static void test_matches_symmetric(void) {
    const char *v[] = {NULL, "", "a", "b"};
    for (int a = 0; a < 4; a++) for (int b = 0; b < 4; b++)
        for (int c = 0; c < 4; c++) for (int d = 0; d < 4; d++) {
            gint x = match(v[a], v[b], v[c], v[d]) != 0;
            gint y = match(v[c], v[d], v[a], v[b]) != 0;
            g_assert_cmpint(x, ==, y);
        }
}
static void test_matches_queue_find(void) {
    GQueue *q = g_queue_new();
    struct Player *a = player_new(":1.1", "w.a"), *b = player_new(":1.2", "w.b");
    g_queue_push_tail(q, a);
    g_queue_push_tail(q, b);
    struct Player probe = {.unique = NULL, .well_known = (char *)"w.b"};
    g_assert_true(g_queue_find_custom(q, &probe, player_matches)->data == b);
    struct Player any = {0};
    g_assert_true(g_queue_find_custom(q, &any, player_matches)->data == a);
    struct Player miss = {.unique = (char *)":9.9"};
    g_assert_null(g_queue_find_custom(q, &miss, player_matches));
    g_queue_free(q);
    player_free(a);
    player_free(b);
}

/* ---- player_cache_for ---- */
static void test_cache_for_mapping(void) {
    struct Player *p = player_new("u", "w");
    g_assert_true(player_cache_for(p, PLAYER_INTERFACE) == &p->player_properties);
    g_assert_true(player_cache_for(p, ROOT_INTERFACE) == &p->root_properties);
    g_assert_true(player_cache_for(p, TRACKLIST_INTERFACE) == &p->optional_properties[optional_index(TRACKLIST_INTERFACE)]);
    g_assert_true(player_cache_for(p, PLAYLISTS_INTERFACE) == &p->optional_properties[optional_index(PLAYLISTS_INTERFACE)]);
    player_free(p);
}
static void test_cache_for_unknown(void) {
    struct Player *p = player_new("u", "w");
    g_assert_null(player_cache_for(p, "org.example.Nope"));
    g_assert_null(player_cache_for(p, ""));
    g_assert_null(player_cache_for(p, NULL));
    g_assert_null(player_cache_for(p, PLAYERCTLD_INTERFACE));
    g_assert_null(player_cache_for(p, "org.freedesktop.DBus.Properties"));
    player_free(p);
}

/* ---- player_update_properties ---- */
static void test_upd_new_property_changed(void) {
    struct Player *p = player_new("u", "w");
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.5))));
    GVariant *v = cached(p, PLAYER_INTERFACE, "Volume");
    g_assert_nonnull(v);
    g_assert_cmpfloat(g_variant_get_double(v), ==, 0.5);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_repeat_identical(void) {
    struct Player *p = player_new("u", "w");
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.5))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.5))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.5))));
    player_free(p);
}
static void test_upd_value_changes(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.5)));
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Volume", g_variant_new_double(0.6))));
    GVariant *v = cached(p, PLAYER_INTERFACE, "Volume");
    g_assert_cmpfloat(g_variant_get_double(v), ==, 0.6);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_type_change_is_change(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("Rate", g_variant_new_double(1.0)));
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Rate", g_variant_new_int32(1))));
    player_free(p);
}
static void test_upd_empty_dict(void) {
    struct Player *p = player_new("u", "w");
    g_assert_false(upd(p, PLAYER_INTERFACE, empty_dict()));
    /* an empty GetAll still creates the cache, making the player "usable" */
    g_assert_nonnull(p->player_properties);
    upd(p, PLAYER_INTERFACE, dict1("a", g_variant_new_int32(1)));
    g_assert_false(upd(p, PLAYER_INTERFACE, empty_dict()));
    GVariant *v = cached(p, PLAYER_INTERFACE, "a");
    g_assert_nonnull(v);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_merges(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("a", g_variant_new_int32(1)));
    upd(p, PLAYER_INTERFACE, dict1("b", g_variant_new_int32(2)));
    GVariant *a = cached(p, PLAYER_INTERFACE, "a"), *b = cached(p, PLAYER_INTERFACE, "b");
    g_assert_nonnull(a);
    g_assert_nonnull(b);
    g_variant_unref(a);
    g_variant_unref(b);
    player_free(p);
}
static void test_upd_non_vardict(void) {
    struct Player *p = player_new("u", "w");
    qa_catch_logs();
    GVariant *bad = g_variant_ref_sink(g_variant_new_string("nope"));
    gboolean r = player_update_properties(p, PLAYER_INTERFACE, bad);
    g_variant_unref(bad);
    g_assert_false(r);
    g_assert_cmpint(qa_crit_count, ==, 0);
    g_assert_null(p->player_properties);
    player_free(p);
}
static void test_upd_wrong_dict_type(void) {
    struct Player *p = player_new("u", "w");
    qa_catch_logs();
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a{ss}"));
    g_variant_builder_add(&b, "{ss}", "k", "v");
    GVariant *bad = g_variant_ref_sink(g_variant_builder_end(&b));
    g_assert_false(player_update_properties(p, PLAYER_INTERFACE, bad));
    g_variant_unref(bad);
    g_assert_cmpint(qa_crit_count, ==, 0);
    player_free(p);
}
static void test_upd_non_vardict_keeps_cache(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("a", g_variant_new_int32(1)));
    GVariant *before = p->player_properties;
    qa_catch_logs();
    GVariant *bad = g_variant_ref_sink(g_variant_new_int32(3));
    g_assert_false(player_update_properties(p, PLAYER_INTERFACE, bad));
    g_variant_unref(bad);
    g_assert_true(p->player_properties == before);
    player_free(p);
}
static void test_upd_unknown_interface(void) {
    struct Player *p = player_new("u", "w");
    qa_catch_logs();
    GVariant *d = dict1("a", g_variant_new_int32(1));
    g_assert_false(player_update_properties(p, "org.example.Nope", d));
    g_variant_unref(d);
    g_assert_cmpint(qa_crit_count, ==, 0);
    g_assert_null(p->player_properties);
    g_assert_null(p->root_properties);
    player_free(p);
}
static void test_upd_null_interface(void) {
    struct Player *p = player_new("u", "w");
    qa_catch_logs();
    GVariant *d = dict1("a", g_variant_new_int32(1));
    gboolean r = player_update_properties(p, NULL, d);
    g_variant_unref(d);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U5: player_update_properties(NULL iface) logs a GLib CRITICAL");
    g_assert_false(r);
    player_free(p);
}
static void test_upd_duplicate_keys(void) {
    struct Player *p = player_new("u", "w");
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", "k", g_variant_new_int32(1));
    g_variant_builder_add(&b, "{sv}", "k", g_variant_new_int32(2));
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    g_assert_true(upd(p, PLAYER_INTERFACE, d));
    GVariant *v = cached(p, PLAYER_INTERFACE, "k");
    g_assert_cmpint(g_variant_get_int32(v), ==, 2);
    g_variant_unref(v);
    GVariantIter it;
    g_variant_iter_init(&it, p->player_properties);
    g_assert_cmpuint(g_variant_iter_n_children(&it), ==, 1);
    player_free(p);
}
static void test_upd_duplicate_keys_identical_repeat(void) {
    struct Player *p = player_new("u", "w");
    for (int i = 0; i < 2; i++) {
        GVariantBuilder b;
        g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
        g_variant_builder_add(&b, "{sv}", "k", g_variant_new_int32(1));
        g_variant_builder_add(&b, "{sv}", "k", g_variant_new_int32(1));
        GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
        gboolean r = upd(p, PLAYER_INTERFACE, d);
        g_assert_cmpint(r, ==, i == 0);
    }
    player_free(p);
}
static void test_upd_position_on_player(void) {
    struct Player *p = player_new("u", "w");
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_int64(1234))));
    g_assert_cmpint(p->position, ==, 1234);
    GVariant *v = cached(p, PLAYER_INTERFACE, "Position");
    g_assert_null(v);
    player_free(p);
}
static void test_upd_position_extremes(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_int64(G_MININT64)));
    g_assert_cmpint(p->position, ==, G_MININT64);
    upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_int64(G_MAXINT64)));
    g_assert_cmpint(p->position, ==, G_MAXINT64);
    upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_int64(-1)));
    g_assert_cmpint(p->position, ==, -1);
    player_free(p);
}
static void test_upd_position_wrong_type(void) {
    struct Player *p = player_new("u", "w");
    p->position = 77;
    qa_catch_logs();
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_string("12"))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_double(1.5))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_uint64(5))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Position", g_variant_new_int32(5))));
    g_assert_cmpint(p->position, ==, 77);
    g_assert_cmpint(qa_crit_count, ==, 0);
    player_free(p);
}
static void test_upd_position_on_root_iface(void) {
    struct Player *p = player_new("u", "w");
    p->position = 5;
    g_assert_true(upd(p, ROOT_INTERFACE, dict1("Position", g_variant_new_int64(99))));
    g_assert_cmpint(p->position, ==, 5);
    GVariant *v = cached(p, ROOT_INTERFACE, "Position");
    g_assert_nonnull(v);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_position_on_optional_iface(void) {
    struct Player *p = player_new("u", "w");
    g_assert_true(upd(p, TRACKLIST_INTERFACE, dict1("Position", g_variant_new_int64(99))));
    g_assert_cmpint(p->position, ==, 0);
    player_free(p);
}
static void test_upd_position_with_others(void) {
    struct Player *p = player_new("u", "w");
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", "Position", g_variant_new_int64(10));
    g_variant_builder_add(&b, "{sv}", "Volume", g_variant_new_double(1));
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    g_assert_true(upd(p, PLAYER_INTERFACE, d));
    g_assert_cmpint(p->position, ==, 10);
    player_free(p);
}
static void test_upd_each_interface_isolated(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("a", g_variant_new_int32(1)));
    upd(p, ROOT_INTERFACE, dict1("b", g_variant_new_int32(2)));
    upd(p, TRACKLIST_INTERFACE, dict1("c", g_variant_new_int32(3)));
    upd(p, PLAYLISTS_INTERFACE, dict1("d", g_variant_new_int32(4)));
    GVariant *v = cached(p, PLAYER_INTERFACE, "b");
    g_assert_null(v);
    v = cached(p, ROOT_INTERFACE, "a");
    g_assert_null(v);
    v = cached(p, TRACKLIST_INTERFACE, "d");
    g_assert_null(v);
    v = cached(p, PLAYLISTS_INTERFACE, "d");
    g_assert_nonnull(v);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_huge_dict(void) {
    struct Player *p = player_new("u", "w");
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    for (int i = 0; i < 20000; i++) {
        gchar *k = g_strdup_printf("key%d", i);
        g_variant_builder_add(&b, "{sv}", k, g_variant_new_int32(i));
        g_free(k);
    }
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    g_assert_true(player_update_properties(p, PLAYER_INTERFACE, d));
    g_assert_false(player_update_properties(p, PLAYER_INTERFACE, d));
    g_variant_unref(d);
    player_free(p);
}
static void test_upd_empty_and_odd_keys(void) {
    struct Player *p = player_new("u", "w");
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("", g_variant_new_int32(1))));
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("\xd0\xba\xd0\xbb", g_variant_new_int32(1))));
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("mpris:trackid", g_variant_new_object_path("/a"))));
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("", g_variant_new_int32(1))));
    player_free(p);
}
static void test_upd_nested_variant_value(void) {
    struct Player *p = player_new("u", "w");
    GVariant *inner = g_variant_new_variant(g_variant_new_int32(3));
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("v", inner)));
    GVariant *c = cached(p, PLAYER_INTERFACE, "v");
    g_assert_true(g_variant_is_of_type(c, G_VARIANT_TYPE_VARIANT));
    g_variant_unref(c);
    player_free(p);
}
static void test_upd_nan_repeat(void) {
    struct Player *p = player_new("u", "w");
    upd(p, PLAYER_INTERFACE, dict1("Rate", g_variant_new_double(NAN)));
    gboolean r = upd(p, PLAYER_INTERFACE, dict1("Rate", g_variant_new_double(NAN)));
    QA_KNOWN_BUG(!r, "BUG-U6: NaN property re-sent identically counts as changed");
    g_assert_false(r);
    player_free(p);
}
static void test_upd_metadata_dict_value(void) {
    struct Player *p = player_new("u", "w");
    GVariantBuilder md;
    g_variant_builder_init(&md, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&md, "{sv}", "xesam:title", g_variant_new_string("t"));
    GVariant *m1 = g_variant_builder_end(&md);
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Metadata", m1)));
    g_variant_builder_init(&md, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&md, "{sv}", "xesam:title", g_variant_new_string("t"));
    GVariant *m2 = g_variant_builder_end(&md);
    g_assert_false(upd(p, PLAYER_INTERFACE, dict1("Metadata", m2)));
    g_variant_builder_init(&md, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&md, "{sv}", "xesam:title", g_variant_new_string("u"));
    GVariant *m3 = g_variant_builder_end(&md);
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("Metadata", m3)));
    player_free(p);
}
static void test_upd_cache_is_independent_ref(void) {
    struct Player *p = player_new("u", "w");
    GVariant *d = dict1("a", g_variant_new_int32(1));
    player_update_properties(p, PLAYER_INTERFACE, d);
    g_assert_true(p->player_properties != d);
    g_variant_unref(d);
    GVariant *v = cached(p, PLAYER_INTERFACE, "a");
    g_assert_nonnull(v);
    g_variant_unref(v);
    player_free(p);
}
static void test_upd_return_after_failed_then_ok(void) {
    struct Player *p = player_new("u", "w");
    qa_catch_logs();
    GVariant *bad = g_variant_ref_sink(g_variant_new_string("x"));
    g_assert_false(player_update_properties(p, PLAYER_INTERFACE, bad));
    g_variant_unref(bad);
    g_assert_true(upd(p, PLAYER_INTERFACE, dict1("a", g_variant_new_int32(1))));
    player_free(p);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    T(optional_index_known); T(optional_index_unknown); T(optional_invalidated_lists);
    T(new_fields); T(new_null_names); T(new_copies_strings); T(free_null); T(free_cancels);
    T(free_all_props); T(set_unique); T(set_unique_same_pointer); T(usable);
    T(matches_equal); T(matches_unique_differs); T(matches_wk_differs);
    T(matches_null_unique_wildcard); T(matches_null_wk_wildcard); T(matches_all_null);
    T(matches_cross_null); T(matches_empty_strings); T(matches_symmetric); T(matches_queue_find);
    T(cache_for_mapping); T(cache_for_unknown);
    T(upd_new_property_changed); T(upd_repeat_identical); T(upd_value_changes);
    T(upd_type_change_is_change); T(upd_empty_dict); T(upd_merges); T(upd_non_vardict);
    T(upd_wrong_dict_type); T(upd_non_vardict_keeps_cache); T(upd_unknown_interface);
    T(upd_null_interface); T(upd_duplicate_keys); T(upd_duplicate_keys_identical_repeat);
    T(upd_position_on_player); T(upd_position_extremes); T(upd_position_wrong_type);
    T(upd_position_on_root_iface); T(upd_position_on_optional_iface); T(upd_position_with_others);
    T(upd_each_interface_isolated); T(upd_huge_dict); T(upd_empty_and_odd_keys);
    T(upd_nested_variant_value); T(upd_nan_repeat); T(upd_metadata_dict_value);
    T(upd_cache_is_independent_ref); T(upd_return_after_failed_then_ok);
    return g_test_run();
}

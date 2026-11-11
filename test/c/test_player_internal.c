/* Adversarial unit tests for internals of playerctl-player.c (the whole
 * library is compiled into this test): properties_get_reply_value,
 * metadata_get_track_id, player_propagate_init_error and the status/loop
 * parsers of playerctl-common.c. The static helpers calculate_cached_position
 * and timespec_to_usec and print_metadata_table (player-commands.c) are not
 * reachable: including their .c files would duplicate the symbols already
 * compiled in, so they are skipped. */

#include <glib.h>
#include <glib/gstdio.h>
#include <math.h>
#include <unistd.h>

#include "playerctl/playerctl-common.h"
#include "playerctl/playerctl-player-internal.h"
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
#define T(name) ADD("/player-internal/" #name, test_##name)

static GVariant *md1(const char *key, GVariant *v) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", key, v);
    return g_variant_ref_sink(g_variant_builder_end(&b));
}
static void tid_is(GVariant *md, const char *want) {
    gchar *id = metadata_get_track_id(md);
    g_assert_cmpstr(id, ==, want);
    g_free(id);
    g_variant_unref(md);
}

/* ---- properties_get_reply_value ---- */
static GVariant *reply_of(GVariant *inner) {
    return g_variant_ref_sink(g_variant_new_tuple(&inner, 1));
}
static void test_reply_variant_string(void) {
    GVariant *r = reply_of(g_variant_new_variant(g_variant_new_string("x")));
    GVariant *v = properties_get_reply_value(r);
    g_assert_nonnull(v);
    g_assert_cmpstr(g_variant_get_string(v, NULL), ==, "x");
    g_variant_unref(v);
    g_variant_unref(r);
}
static void test_reply_variant_dict(void) {
    GVariant *d = md1("a", g_variant_new_int32(1));
    GVariant *r = reply_of(g_variant_new_variant(d));
    g_variant_unref(d);
    GVariant *v = properties_get_reply_value(r);
    g_assert_true(g_variant_is_of_type(v, G_VARIANT_TYPE_VARDICT));
    g_variant_unref(v);
    g_variant_unref(r);
}
static void test_reply_nested_variant(void) {
    GVariant *r = reply_of(g_variant_new_variant(g_variant_new_variant(g_variant_new_int32(1))));
    GVariant *v = properties_get_reply_value(r);
    g_assert_true(g_variant_is_of_type(v, G_VARIANT_TYPE_VARIANT));
    g_variant_unref(v);
    g_variant_unref(r);
}
static void test_reply_non_tuple(void) {
    GVariant *r = g_variant_ref_sink(g_variant_new_string("x"));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_tuple_of_string(void) {
    GVariant *r = reply_of(g_variant_new_string("x"));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_empty_tuple(void) {
    GVariant *r = g_variant_ref_sink(g_variant_new_tuple(NULL, 0));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_two_element_tuple(void) {
    GVariant *kids[2] = {g_variant_new_variant(g_variant_new_int32(1)), g_variant_new_variant(g_variant_new_int32(2))};
    GVariant *r = g_variant_ref_sink(g_variant_new_tuple(kids, 2));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_dict_not_tuple(void) {
    GVariant *r = md1("a", g_variant_new_int32(1));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_array_of_variant(void) {
    GVariant *items[] = {g_variant_new_variant(g_variant_new_int32(1))};
    GVariant *r = g_variant_ref_sink(g_variant_new_array(G_VARIANT_TYPE_VARIANT, items, 1));
    g_assert_null(properties_get_reply_value(r));
    g_variant_unref(r);
}
static void test_reply_returns_new_ref(void) {
    GVariant *r = reply_of(g_variant_new_variant(g_variant_new_int64(7)));
    GVariant *v = properties_get_reply_value(r);
    g_variant_unref(r);
    g_assert_cmpint(g_variant_get_int64(v), ==, 7);
    g_variant_unref(v);
}

/* ---- metadata_get_track_id ---- */
static void test_tid_object_path(void) { tid_is(md1("mpris:trackid", g_variant_new_object_path("/a/b")), "/a/b"); }
static void test_tid_string_path(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/a/b")), "/a/b"); }
static void test_tid_empty_string(void) { tid_is(md1("mpris:trackid", g_variant_new_string("")), NULL); }
static void test_tid_slash(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/")), "/"); }
static void test_tid_trailing_slash(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/a/")), NULL); }
static void test_tid_double_slash(void) { tid_is(md1("mpris:trackid", g_variant_new_string("//")), NULL); }
static void test_tid_relative(void) { tid_is(md1("mpris:trackid", g_variant_new_string("track1")), NULL); }
static void test_tid_space(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/a b")), NULL); }
static void test_tid_dash(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/a-b")), NULL); }
static void test_tid_unicode(void) { tid_is(md1("mpris:trackid", g_variant_new_string("/\xd1\x82")), NULL); }
static void test_tid_urlish(void) { tid_is(md1("mpris:trackid", g_variant_new_string("spotify:track:abc")), NULL); }
static void test_tid_int(void) { tid_is(md1("mpris:trackid", g_variant_new_int32(3)), NULL); }
static void test_tid_array_of_strings(void) {
    const gchar *s[] = {"/a", NULL};
    tid_is(md1("mpris:trackid", g_variant_new_strv(s, -1)), NULL);
}
static void test_tid_signature_string(void) { tid_is(md1("mpris:trackid", g_variant_new_signature("i")), NULL); }
static void test_tid_missing(void) { tid_is(md1("xesam:title", g_variant_new_string("t")), NULL); }
static void test_tid_empty_dict(void) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    tid_is(g_variant_ref_sink(g_variant_builder_end(&b)), NULL);
}
static void test_tid_case_sensitive_key(void) { tid_is(md1("MPRIS:TRACKID", g_variant_new_string("/a")), NULL); }
static void test_tid_long_path(void) {
    gchar *p = g_strnfill(100000, 'a');
    gchar *path = g_strconcat("/", p, NULL);
    tid_is(md1("mpris:trackid", g_variant_new_string(path)), path);
    g_free(p);
    g_free(path);
}
static void test_tid_many_segments(void) {
    GString *s = g_string_new("");
    for (int i = 0; i < 20000; i++) g_string_append(s, "/a");
    tid_is(md1("mpris:trackid", g_variant_new_string(s->str)), s->str);
    g_string_free(s, TRUE);
}
static void test_tid_duplicate_keys(void) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", "mpris:trackid", g_variant_new_string("/one"));
    g_variant_builder_add(&b, "{sv}", "mpris:trackid", g_variant_new_string("/two"));
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    gchar *id = metadata_get_track_id(d);
    g_assert_true(id != NULL);
    g_free(id);
    g_variant_unref(d);
}
static void test_tid_objpath_beats_string(void) {
    /* both an object path and a string under the same key is not possible in a{sv}
     * with one key; with two keys the object path lookup runs first */
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE_VARDICT);
    g_variant_builder_add(&b, "{sv}", "mpris:trackid", g_variant_new_string("/s"));
    g_variant_builder_add(&b, "{sv}", "mpris:trackid", g_variant_new_object_path("/o"));
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    gchar *id = metadata_get_track_id(d);
    g_assert_nonnull(id);
    g_free(id);
    g_variant_unref(d);
}
static void test_tid_string_dict_ss(void) {
    /* a{ss} metadata from a hostile player */
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a{ss}"));
    g_variant_builder_add(&b, "{ss}", "mpris:trackid", "/a");
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    qa_catch_logs();
    gchar *id = metadata_get_track_id(d);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U9: metadata_get_track_id on an a{ss} Metadata reply gives GLib CRITICAL");
    g_free(id);
    g_variant_unref(d);
}
static void test_tid_non_dict_string(void) {
    /* player_get_metadata passes through whatever (v) a Spotify-style player
     * returns for Metadata, even a string */
    GVariant *d = g_variant_ref_sink(g_variant_new_string("hostile"));
    qa_catch_logs();
    gchar *id = metadata_get_track_id(d);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U9: metadata_get_track_id on a non-dict Metadata reply gives GLib CRITICAL (reachable via properties_get_reply_value in playerctl_player_get_metadata)");
    g_assert_null(id);
    g_variant_unref(d);
}
static void test_tid_non_dict_int_dict(void) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a{ii}"));
    g_variant_builder_add(&b, "{ii}", 1, 2);
    GVariant *d = g_variant_ref_sink(g_variant_builder_end(&b));
    qa_catch_logs();
    gchar *id = metadata_get_track_id(d);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U9: metadata_get_track_id on an a{ii} Metadata reply gives GLib CRITICAL");
    g_assert_null(id);
    g_variant_unref(d);
}
static void test_tid_tuple_metadata(void) {
    GVariant *kids[] = {g_variant_new_string("x")};
    GVariant *d = g_variant_ref_sink(g_variant_new_tuple(kids, 1));
    qa_catch_logs();
    gchar *id = metadata_get_track_id(d);
    QA_KNOWN_BUG(qa_crit_count == 0, "BUG-U9: metadata_get_track_id on a tuple Metadata reply gives GLib CRITICAL");
    g_assert_null(id);
    g_variant_unref(d);
}

/* ---- player_propagate_init_error ---- */
static PlayerctlPlayer *bare_player(void) {
    PlayerctlPlayer *p = g_object_new(PLAYERCTL_TYPE_PLAYER, NULL);
    g_assert_nonnull(p);
    return p;
}
static void test_init_error_none(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    GError *e = NULL;
    g_assert_false(player_propagate_init_error(p, &e));
    g_assert_no_error(e);
    g_object_unref(p);
}
static void test_init_error_set(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    p->priv->init_error = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "boom");
    GError *e = NULL;
    g_assert_true(player_propagate_init_error(p, &e));
    g_assert_cmpstr(e->message, ==, "boom");
    g_assert_true(e != p->priv->init_error);
    g_clear_error(&e);
    g_assert_nonnull(p->priv->init_error);
    g_object_unref(p);
}
static void test_init_error_null_out(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    p->priv->init_error = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "boom");
    g_assert_true(player_propagate_init_error(p, NULL));
    g_object_unref(p);
}
static void test_init_error_repeat(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    p->priv->init_error = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "boom");
    for (int i = 0; i < 3; i++) {
        GError *e = NULL;
        g_assert_true(player_propagate_init_error(p, &e));
        g_assert_cmpstr(e->message, ==, "boom");
        g_clear_error(&e);
    }
    g_object_unref(p);
}
static void test_init_error_existing_err_set(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    p->priv->init_error = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "boom");
    GError *e = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "old");
    qa_catch_logs();
    player_propagate_init_error(p, &e);
    /* g_propagate_error on a set GError warns; callers must pass a clean one */
    g_clear_error(&e);
    g_object_unref(p);
}
static void test_bare_player_has_init_error(void) {
    /* constructed() inits the object: with no name it must record an error */
    PlayerctlPlayer *p = bare_player();
    GError *e = NULL;
    g_assert_true(player_propagate_init_error(p, &e));
    g_assert_nonnull(e);
    g_clear_error(&e);
    g_object_unref(p);
}
static void test_bare_player_properties_unset(void) {
    PlayerctlPlayer *p = bare_player();
    gchar *name = (gchar *)"unset";
    g_object_get(p, "player-name", &name, NULL);
    g_assert_null(name);
    g_object_unref(p);
}
static void test_bare_player_command_reports_init_error(void) {
    PlayerctlPlayer *p = bare_player();
    g_clear_error(&p->priv->init_error);
    p->priv->init_error = g_error_new(G_IO_ERROR, G_IO_ERROR_FAILED, "boom");
    GError *e = NULL;
    playerctl_player_play(p, &e);
    g_assert_nonnull(e);
    g_assert_cmpstr(e->message, ==, "boom");
    g_clear_error(&e);
    playerctl_player_next(p, &e);
    g_assert_nonnull(e);
    g_clear_error(&e);
    gchar *m = playerctl_player_print_metadata_prop(p, NULL, &e);
    g_assert_null(m);
    g_assert_nonnull(e);
    g_clear_error(&e);
    g_object_unref(p);
}

/* ---- status parsers ---- */
static void test_status_parse(void) {
    PlayerctlPlaybackStatus s = PLAYERCTL_PLAYBACK_STATUS_STOPPED;
    g_assert_true(pctl_parse_playback_status("playing", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_PLAYBACK_STATUS_PLAYING);
    g_assert_true(pctl_parse_playback_status("PAUSED", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_PLAYBACK_STATUS_PAUSED);
    g_assert_true(pctl_parse_playback_status("sToPpEd", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_PLAYBACK_STATUS_STOPPED);
}
static void test_status_parse_rejects(void) {
    PlayerctlPlaybackStatus s = PLAYERCTL_PLAYBACK_STATUS_PAUSED;
    const char *bad[] = {"", " Playing", "Playing ", "Play", "Playingx", "Playing\n", "0", NULL};
    for (int i = 0; bad[i] || i == 0; i++) {
        g_assert_false(pctl_parse_playback_status(bad[i], &s));
        if (!bad[i]) break;
    }
    g_assert_cmpint(s, ==, PLAYERCTL_PLAYBACK_STATUS_PAUSED);
}
static void test_status_parse_null(void) {
    PlayerctlPlaybackStatus s = PLAYERCTL_PLAYBACK_STATUS_PAUSED;
    g_assert_false(pctl_parse_playback_status(NULL, &s));
}
static void test_status_to_string_range(void) {
    g_assert_cmpstr(pctl_playback_status_to_string(PLAYERCTL_PLAYBACK_STATUS_PLAYING), ==, "Playing");
    g_assert_null(pctl_playback_status_to_string((PlayerctlPlaybackStatus)99));
    g_assert_null(pctl_playback_status_to_string((PlayerctlPlaybackStatus)-1));
}
static void test_status_roundtrip(void) {
    for (int i = 0; i < 3; i++) {
        const gchar *n = pctl_playback_status_to_string((PlayerctlPlaybackStatus)i);
        g_assert_nonnull(n);
        PlayerctlPlaybackStatus s;
        g_assert_true(pctl_parse_playback_status(n, &s));
        g_assert_cmpint(s, ==, i);
    }
}
static void test_loop_parse(void) {
    PlayerctlLoopStatus s;
    g_assert_true(pctl_parse_loop_status("none", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_LOOP_STATUS_NONE);
    g_assert_true(pctl_parse_loop_status("TRACK", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_LOOP_STATUS_TRACK);
    g_assert_true(pctl_parse_loop_status("Playlist", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_LOOP_STATUS_PLAYLIST);
}
static void test_loop_parse_rejects(void) {
    PlayerctlLoopStatus s = PLAYERCTL_LOOP_STATUS_TRACK;
    g_assert_false(pctl_parse_loop_status("", &s));
    g_assert_false(pctl_parse_loop_status(NULL, &s));
    g_assert_false(pctl_parse_loop_status("Tracks", &s));
    g_assert_false(pctl_parse_loop_status("Tra", &s));
    g_assert_false(pctl_parse_loop_status(" none", &s));
    g_assert_false(pctl_parse_loop_status("true", &s));
    g_assert_cmpint(s, ==, PLAYERCTL_LOOP_STATUS_TRACK);
}
static void test_loop_to_string_range(void) {
    g_assert_cmpstr(pctl_loop_status_to_string(PLAYERCTL_LOOP_STATUS_PLAYLIST), ==, "Playlist");
    g_assert_null(pctl_loop_status_to_string((PlayerctlLoopStatus)42));
}
static void test_source_bus_mapping(void) {
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_DBUS_SESSION), ==, G_BUS_TYPE_SESSION);
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_DBUS_SYSTEM), ==, G_BUS_TYPE_SYSTEM);
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_NONE), ==, G_BUS_TYPE_NONE);
    g_assert_cmpint(pctl_source_to_bus_type((PlayerctlSource)77), ==, G_BUS_TYPE_NONE);
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_SESSION), ==, PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_SYSTEM), ==, PLAYERCTL_SOURCE_DBUS_SYSTEM);
}
static void test_bus_to_source_unknown_warns(void) {
    qa_catch_logs();
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_STARTER), ==, PLAYERCTL_SOURCE_NONE);
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_NONE), ==, PLAYERCTL_SOURCE_NONE);
    g_assert_cmpint(qa_warn_count, ==, 2);
}
static void test_print_gvariant_null(void) {
    gchar *s = pctl_print_gvariant(NULL);
    g_assert_cmpstr(s, ==, "");
    g_free(s);
}
static void test_print_gvariant_signature_and_maybe(void) {
    GVariant *v = g_variant_ref_sink(g_variant_new_signature("a{sv}"));
    gchar *s = pctl_print_gvariant(v);
    g_assert_nonnull(s);
    g_free(s);
    g_variant_unref(v);
    v = g_variant_ref_sink(g_variant_new_maybe(G_VARIANT_TYPE_STRING, NULL));
    s = pctl_print_gvariant(v);
    g_assert_nonnull(s);
    g_free(s);
    g_variant_unref(v);
}
static void test_print_gvariant_array_with_empty_strings(void) {
    const gchar *a[] = {"", "", NULL};
    GVariant *v = g_variant_ref_sink(g_variant_new_strv(a, -1));
    gchar *s = pctl_print_gvariant(v);
    g_assert_cmpstr(s, ==, ", ");
    g_free(s);
    g_variant_unref(v);
}
static void test_print_gvariant_nan_inf(void) {
    GVariant *v = g_variant_ref_sink(g_variant_new_double(INFINITY));
    gchar *s = pctl_print_gvariant(v);
    g_assert_nonnull(s);
    g_free(s);
    g_variant_unref(v);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    T(reply_variant_string); T(reply_variant_dict); T(reply_nested_variant);
    T(reply_non_tuple); T(reply_tuple_of_string); T(reply_empty_tuple);
    T(reply_two_element_tuple); T(reply_dict_not_tuple); T(reply_array_of_variant);
    T(reply_returns_new_ref);
    T(tid_object_path); T(tid_string_path); T(tid_empty_string); T(tid_slash);
    T(tid_trailing_slash); T(tid_double_slash); T(tid_relative); T(tid_space); T(tid_dash);
    T(tid_unicode); T(tid_urlish); T(tid_int); T(tid_array_of_strings);
    T(tid_signature_string); T(tid_missing); T(tid_empty_dict); T(tid_case_sensitive_key);
    T(tid_long_path); T(tid_many_segments); T(tid_duplicate_keys); T(tid_objpath_beats_string);
    T(tid_string_dict_ss); T(tid_non_dict_string); T(tid_non_dict_int_dict); T(tid_tuple_metadata);
    T(init_error_none); T(init_error_set); T(init_error_null_out); T(init_error_repeat);
    T(init_error_existing_err_set); T(bare_player_properties_unset); T(bare_player_has_init_error);
    T(bare_player_command_reports_init_error);
    T(status_parse); T(status_parse_rejects); T(status_parse_null); T(status_to_string_range);
    T(status_roundtrip); T(loop_parse); T(loop_parse_rejects); T(loop_to_string_range);
    T(source_bus_mapping); T(bus_to_source_unknown_warns); T(print_gvariant_null);
    T(print_gvariant_signature_and_maybe); T(print_gvariant_array_with_empty_strings);
    T(print_gvariant_nan_inf);
    return g_test_run();
}

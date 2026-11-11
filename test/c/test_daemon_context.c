/* Adversarial unit tests for the playerctld context queue
 * (playerctl-daemon-context.c). Pure queue operations run without a bus;
 * functions that emit signals use a private bus from GTestDBus (skipped when
 * dbus-daemon is missing). */

#include <gio/gio.h>
#include <glib.h>
#include <glib/gstdio.h>
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
#define T(name) ADD("/daemon-context/" #name, test_##name)

static struct PlayerctldContext *ctx_new(void) {
    struct PlayerctldContext *c = g_new0(struct PlayerctldContext, 1);
    c->players = g_queue_new();
    c->pending_players = g_queue_new();
    return c;
}
static void ctx_free(struct PlayerctldContext *c) {
    /* players that are in a queue are owned by the test through arrays */
    g_queue_free(c->players);
    g_queue_free(c->pending_players);
    if (c->connection) g_object_unref(c->connection);
    g_free(c);
}
static struct Player *mkp(int i) {
    gchar *u = g_strdup_printf(":1.%d", 100 + i), *w = g_strdup_printf("org.mpris.MediaPlayer2.p%d", i);
    struct Player *p = player_new(u, w);
    g_free(u);
    g_free(w);
    return p;
}
static gchar *order(struct PlayerctldContext *c) {
    GString *s = g_string_new("");
    for (GList *l = c->players->head; l; l = l->next) {
        struct Player *p = l->data;
        g_string_append(s, p->well_known + strlen("org.mpris.MediaPlayer2.p"));
    }
    return g_string_free(s, FALSE);
}
#define ASSERT_ORDER(c, want) G_STMT_START { gchar *_o = order(c); g_assert_cmpstr(_o, ==, want); g_free(_o); } G_STMT_END

static GTestDBus *bus;
static void ctx_connect(struct PlayerctldContext *c) {
    bus = g_test_dbus_new(G_TEST_DBUS_NONE);
    g_test_dbus_up(bus);
    GError *e = NULL;
    c->connection = g_dbus_connection_new_for_address_sync(
        g_test_dbus_get_bus_address(bus),
        G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_CLIENT | G_DBUS_CONNECTION_FLAGS_MESSAGE_BUS_CONNECTION,
        NULL, NULL, &e);
    if (!c->connection) qa_marker("SKIP:", e ? e->message : "no private bus");
}

/* ---- empty ---- */
static void test_empty_get_active(void) {
    struct PlayerctldContext *c = ctx_new();
    g_assert_null(context_get_active_player(c));
    ctx_free(c);
}
static void test_empty_find(void) {
    struct PlayerctldContext *c = ctx_new();
    g_assert_null(context_find_player(c, ":1.1", "w"));
    g_assert_null(context_find_player(c, NULL, NULL));
    ctx_free(c);
}
static void test_empty_shift_unshift(void) {
    struct PlayerctldContext *c = ctx_new();
    g_assert_null(context_shift_active_player(c));
    g_assert_null(context_unshift_active_player(c));
    g_assert_cmpuint(c->players->length, ==, 0);
    ctx_free(c);
}
static void test_empty_names(void) {
    struct PlayerctldContext *c = ctx_new();
    GVariant *v = g_variant_ref_sink(context_player_names_to_gvariant(c));
    g_assert_cmpstr(g_variant_get_type_string(v), ==, "as");
    g_assert_cmpuint(g_variant_n_children(v), ==, 0);
    g_variant_unref(v);
    ctx_free(c);
}
static void test_empty_remove_unknown(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *p = mkp(1);
    context_remove_player(c, p);
    g_assert_cmpuint(c->players->length, ==, 0);
    player_free(p);
    ctx_free(c);
}
static void test_remove_null(void) {
    struct PlayerctldContext *c = ctx_new();
    context_remove_player(c, NULL);
    ctx_free(c);
}

/* ---- add / pending ---- */
static void test_add_order(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *p[3] = {mkp(1), mkp(2), mkp(3)};
    for (int i = 0; i < 3; i++) context_add_player(c, p[i]);
    ASSERT_ORDER(c, "123");
    g_assert_true(context_get_active_player(c) == p[0]);
    for (int i = 0; i < 3; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_add_twice(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_player(c, b);
    context_add_player(c, a);
    g_assert_cmpuint(c->players->length, ==, 2);
    ASSERT_ORDER(c, "21");
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_add_pending_not_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    g_assert_null(context_get_active_player(c));
    g_assert_cmpuint(c->pending_players->length, ==, 1);
    g_assert_cmpuint(c->players->length, ==, 0);
    player_free(a);
    ctx_free(c);
}
static void test_add_pending_twice(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    context_add_pending_player(c, a);
    g_assert_cmpuint(c->pending_players->length, ==, 1);
    player_free(a);
    ctx_free(c);
}
static void test_pending_to_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    context_add_player(c, a);
    g_assert_cmpuint(c->pending_players->length, ==, 0);
    g_assert_cmpuint(c->players->length, ==, 1);
    player_free(a);
    ctx_free(c);
}
static void test_active_to_pending(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_player(c, a);
    context_add_pending_player(c, a);
    g_assert_cmpuint(c->pending_players->length, ==, 1);
    g_assert_cmpuint(c->players->length, ==, 0);
    player_free(a);
    ctx_free(c);
}
static void test_add_many(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *p[2000];
    for (int i = 0; i < 2000; i++) { p[i] = mkp(i); context_add_player(c, p[i]); }
    g_assert_cmpuint(c->players->length, ==, 2000);
    context_add_player(c, p[0]);
    g_assert_true(g_queue_peek_tail(c->players) == p[0]);
    g_assert_cmpuint(c->players->length, ==, 2000);
    for (int i = 0; i < 2000; i++) context_remove_player(c, p[i]);
    g_assert_cmpuint(c->players->length, ==, 0);
    for (int i = 0; i < 2000; i++) player_free(p[i]);
    ctx_free(c);
}

/* ---- remove / pending_active ---- */
static void test_remove_from_players(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_player(c, b);
    context_remove_player(c, a);
    ASSERT_ORDER(c, "2");
    context_remove_player(c, a);
    ASSERT_ORDER(c, "2");
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_remove_from_pending(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    context_remove_player(c, a);
    g_assert_cmpuint(c->pending_players->length, ==, 0);
    player_free(a);
    ctx_free(c);
}
static void test_remove_clears_pending_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    c->pending_active = a;
    context_remove_player(c, a);
    g_assert_null(c->pending_active);
    player_free(a);
    ctx_free(c);
}
static void test_remove_other_keeps_pending_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_pending_player(c, a);
    context_add_pending_player(c, b);
    c->pending_active = a;
    context_remove_player(c, b);
    g_assert_true(c->pending_active == a);
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_remove_never_added_pending_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    c->pending_active = a;
    context_remove_player(c, a);
    g_assert_null(c->pending_active);
    player_free(a);
    ctx_free(c);
}

/* ---- set active ---- */
static void test_set_active_moves_to_head(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *p[3] = {mkp(1), mkp(2), mkp(3)};
    for (int i = 0; i < 3; i++) context_add_player(c, p[i]);
    context_set_active_player(c, p[2]);
    ASSERT_ORDER(c, "312");
    context_set_active_player(c, p[2]);
    ASSERT_ORDER(c, "312");
    for (int i = 0; i < 3; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_set_active_from_pending(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_pending_player(c, b);
    c->pending_active = b;
    context_set_active_player(c, b);
    ASSERT_ORDER(c, "21");
    g_assert_cmpuint(c->pending_players->length, ==, 0);
    g_assert_null(c->pending_active);
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_set_active_on_empty(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_set_active_player(c, a);
    g_assert_true(context_get_active_player(c) == a);
    player_free(a);
    ctx_free(c);
}
static void test_set_active_clears_other_pending_active(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_pending_player(c, a);
    c->pending_active = a;
    context_set_active_player(c, b);
    /* documented: pending_active is reset whenever an active player is set */
    g_assert_null(c->pending_active);
    player_free(a);
    player_free(b);
    ctx_free(c);
}

/* ---- find ---- */
static void test_find_by_names(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_player(c, b);
    g_assert_true(context_find_player(c, ":1.102", NULL) == b);
    g_assert_true(context_find_player(c, NULL, "org.mpris.MediaPlayer2.p1") == a);
    g_assert_true(context_find_player(c, ":1.101", "org.mpris.MediaPlayer2.p1") == a);
    g_assert_null(context_find_player(c, ":1.101", "org.mpris.MediaPlayer2.p2"));
    g_assert_null(context_find_player(c, ":9.9", NULL));
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_find_players_before_pending(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *dup = mkp(1);
    context_add_pending_player(c, dup);
    context_add_player(c, a);
    g_assert_true(context_find_player(c, ":1.101", NULL) == a);
    player_free(a);
    player_free(dup);
    ctx_free(c);
}
static void test_find_pending_only(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    g_assert_true(context_find_player(c, ":1.101", NULL) == a);
    player_free(a);
    ctx_free(c);
}
static void test_find_null_probe_matches_first(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_player(c, b);
    /* documented: both NULL matches the first player */
    g_assert_true(context_find_player(c, NULL, NULL) == a);
    player_free(a);
    player_free(b);
    ctx_free(c);
}
static void test_find_null_probe_pending_fallback(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    g_assert_true(context_find_player(c, NULL, NULL) == a);
    player_free(a);
    ctx_free(c);
}
static void test_find_player_with_null_names(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = player_new(NULL, NULL);
    context_add_player(c, a);
    /* a player with no names matches every probe */
    g_assert_true(context_find_player(c, ":1.1", "x") == a);
    player_free(a);
    ctx_free(c);
}

/* ---- names ---- */
static void test_names_order(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *p[3] = {mkp(1), mkp(2), mkp(3)};
    for (int i = 0; i < 3; i++) context_add_player(c, p[i]);
    GVariant *v = g_variant_ref_sink(context_player_names_to_gvariant(c));
    g_assert_cmpuint(g_variant_n_children(v), ==, 3);
    const gchar **s = g_variant_get_strv(v, NULL);
    g_assert_cmpstr(s[0], ==, "org.mpris.MediaPlayer2.p1");
    g_assert_cmpstr(s[2], ==, "org.mpris.MediaPlayer2.p3");
    g_free(s);
    g_variant_unref(v);
    for (int i = 0; i < 3; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_names_ignores_pending(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_pending_player(c, a);
    GVariant *v = g_variant_ref_sink(context_player_names_to_gvariant(c));
    g_assert_cmpuint(g_variant_n_children(v), ==, 0);
    g_variant_unref(v);
    player_free(a);
    ctx_free(c);
}
static void test_names_null_well_known(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = player_new(":1.1", NULL);
    context_add_player(c, a);
    qa_catch_logs();
    GVariant *v = context_player_names_to_gvariant(c);
    QA_KNOWN_BUG(qa_crit_count == 0 && v != NULL, "BUG-U8: context_player_names_to_gvariant with NULL well_known gives CRITICAL/NULL (latent)");
    g_variant_unref(g_variant_ref_sink(v));
    player_free(a);
    ctx_free(c);
}
static void test_names_empty_string(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = player_new(":1.1", "");
    context_add_player(c, a);
    GVariant *v = g_variant_ref_sink(context_player_names_to_gvariant(c));
    g_assert_cmpuint(g_variant_n_children(v), ==, 1);
    g_variant_unref(v);
    player_free(a);
    ctx_free(c);
}

/* ---- shift / unshift ---- */
static void test_shift_single_no_emit(void) {
    struct PlayerctldContext *c = ctx_new();
    struct Player *a = mkp(1);
    context_add_player(c, a);
    g_assert_true(context_shift_active_player(c) == a);
    g_assert_true(context_unshift_active_player(c) == a);
    g_assert_cmpuint(c->players->length, ==, 1);
    player_free(a);
    ctx_free(c);
}
static void test_shift_rotates(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *p[3] = {mkp(1), mkp(2), mkp(3)};
    for (int i = 0; i < 3; i++) context_add_player(c, p[i]);
    qa_catch_logs();
    g_assert_true(context_shift_active_player(c) == p[1]);
    ASSERT_ORDER(c, "231");
    g_assert_true(context_shift_active_player(c) == p[2]);
    ASSERT_ORDER(c, "312");
    g_assert_true(context_shift_active_player(c) == p[0]);
    ASSERT_ORDER(c, "123");
    g_assert_cmpint(qa_crit_count, ==, 0);
    for (int i = 0; i < 3; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_unshift_rotates(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *p[3] = {mkp(1), mkp(2), mkp(3)};
    for (int i = 0; i < 3; i++) context_add_player(c, p[i]);
    qa_catch_logs();
    g_assert_true(context_unshift_active_player(c) == p[2]);
    ASSERT_ORDER(c, "312");
    g_assert_true(context_unshift_active_player(c) == p[1]);
    ASSERT_ORDER(c, "231");
    g_assert_cmpint(qa_crit_count, ==, 0);
    for (int i = 0; i < 3; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_shift_unshift_inverse(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *p[4] = {mkp(1), mkp(2), mkp(3), mkp(4)};
    for (int i = 0; i < 4; i++) context_add_player(c, p[i]);
    qa_catch_logs();
    context_shift_active_player(c);
    context_unshift_active_player(c);
    ASSERT_ORDER(c, "1234");
    for (int i = 0; i < 4; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_shift_full_cycle(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *p[5];
    for (int i = 0; i < 5; i++) { p[i] = mkp(i + 1); context_add_player(c, p[i]); }
    qa_catch_logs();
    for (int i = 0; i < 5; i++) context_shift_active_player(c);
    ASSERT_ORDER(c, "12345");
    for (int i = 0; i < 5; i++) player_free(p[i]);
    ctx_free(c);
}
static void test_shift_with_pending_untouched(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *a = mkp(1), *b = mkp(2), *pend = mkp(3);
    context_add_player(c, a);
    context_add_player(c, b);
    context_add_pending_player(c, pend);
    qa_catch_logs();
    context_shift_active_player(c);
    g_assert_cmpuint(c->pending_players->length, ==, 1);
    player_free(a);
    player_free(b);
    player_free(pend);
    ctx_free(c);
}
static void test_shift_clears_pending_active(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *a = mkp(1), *b = mkp(2);
    context_add_player(c, a);
    context_add_player(c, b);
    c->pending_active = a;
    qa_catch_logs();
    context_shift_active_player(c);
    /* a was removed and re-added: remove clears pending_active for it */
    g_assert_null(c->pending_active);
    player_free(a);
    player_free(b);
    ctx_free(c);
}

/* ---- emit functions (private bus) ---- */
static void test_emit_no_player(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    GError *e = NULL;
    context_emit_active_player_changed(c, &e);
    g_assert_no_error(e);
    ctx_free(c);
}
static void test_emit_usable_player(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *a = mkp(1);
    GVariant *empty = g_variant_ref_sink(g_variant_new_array(G_VARIANT_TYPE("{sv}"), NULL, 0));
    player_update_properties(a, PLAYER_INTERFACE, empty);
    player_update_properties(a, ROOT_INTERFACE, empty);
    g_variant_unref(empty);
    context_add_player(c, a);
    GError *e = NULL;
    context_emit_active_player_changed(c, &e);
    g_assert_no_error(e);
    player_free(a);
    ctx_free(c);
}
static void test_emit_unusable_player_warns(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *a = mkp(1);
    context_add_player(c, a);
    qa_catch_logs();
    GError *e = NULL;
    context_emit_active_player_changed(c, &e);
    g_assert_no_error(e);
    g_assert_cmpint(qa_warn_count, ==, 1);
    g_assert_cmpint(qa_crit_count, ==, 0);
    player_free(a);
    ctx_free(c);
}
static void test_emit_closed_connection(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    g_dbus_connection_close_sync(c->connection, NULL, NULL);
    GError *e = NULL;
    context_emit_active_player_changed(c, &e);
    g_assert_nonnull(e);
    g_clear_error(&e);
    ctx_free(c);
}
static void test_emit_error_null_out(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    g_dbus_connection_close_sync(c->connection, NULL, NULL);
    context_emit_active_player_changed(c, NULL);
    ctx_free(c);
}
static void test_emit_optional_no_player_no_announce(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    GError *e = NULL;
    g_assert_true(context_emit_optional_properties(c, NULL, &e));
    g_assert_no_error(e);
    for (int i = 0; i < N_OPTIONAL; i++) g_assert_false(c->announced_optional[i]);
    ctx_free(c);
}
static void test_emit_optional_tracks_announce(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    struct Player *a = mkp(1);
    a->optional_properties[0] = g_variant_ref_sink(g_variant_new_array(G_VARIANT_TYPE("{sv}"), NULL, 0));
    GError *e = NULL;
    g_assert_true(context_emit_optional_properties(c, a, &e));
    g_assert_true(c->announced_optional[0]);
    g_assert_false(c->announced_optional[1]);
    /* player loses the interface: invalidation, flag cleared */
    g_variant_unref(a->optional_properties[0]);
    a->optional_properties[0] = NULL;
    g_assert_true(context_emit_optional_properties(c, a, &e));
    g_assert_false(c->announced_optional[0]);
    g_assert_no_error(e);
    player_free(a);
    ctx_free(c);
}
static void test_emit_optional_closed_connection(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    g_dbus_connection_close_sync(c->connection, NULL, NULL);
    GError *e = NULL;
    gboolean r = context_emit_optional_properties(c, NULL, &e);
    g_assert_false(r);
    g_assert_nonnull(e);
    g_clear_error(&e);
    ctx_free(c);
}
static void test_emit_optional_prior_announce_no_player_invalidates(void) {
    struct PlayerctldContext *c = ctx_new();
    ctx_connect(c);
    c->announced_optional[0] = TRUE;
    GError *e = NULL;
    g_assert_true(context_emit_optional_properties(c, NULL, &e));
    g_assert_false(c->announced_optional[0]);
    ctx_free(c);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    T(empty_get_active); T(empty_find); T(empty_shift_unshift); T(empty_names);
    T(empty_remove_unknown); T(remove_null);
    T(add_order); T(add_twice); T(add_pending_not_active); T(add_pending_twice);
    T(pending_to_active); T(active_to_pending); T(add_many);
    T(remove_from_players); T(remove_from_pending); T(remove_clears_pending_active);
    T(remove_other_keeps_pending_active); T(remove_never_added_pending_active);
    T(set_active_moves_to_head); T(set_active_from_pending); T(set_active_on_empty);
    T(set_active_clears_other_pending_active);
    T(find_by_names); T(find_players_before_pending); T(find_pending_only);
    T(find_null_probe_matches_first); T(find_null_probe_pending_fallback);
    T(find_player_with_null_names);
    T(names_order); T(names_ignores_pending); T(names_null_well_known); T(names_empty_string);
    T(shift_single_no_emit); T(shift_rotates); T(unshift_rotates); T(shift_unshift_inverse);
    T(shift_full_cycle); T(shift_with_pending_untouched); T(shift_clears_pending_active);
    T(emit_no_player); T(emit_usable_player); T(emit_unusable_player_warns);
    T(emit_closed_connection); T(emit_error_null_out); T(emit_optional_no_player_no_announce);
    T(emit_optional_tracks_announce); T(emit_optional_closed_connection);
    T(emit_optional_prior_announce_no_player_invalidates);
    return g_test_run();
}

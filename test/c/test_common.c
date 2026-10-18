/* Unit tests for the pctl_* helpers in playerctl-common.c. */

#include <glib.h>
#include <stdlib.h>

#include "playerctl/playerctl-common.h"

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

static gchar *print_and_free(GVariant *v) {
    GVariant *sunk = g_variant_ref_sink(v);
    gchar *s = pctl_print_gvariant(sunk);
    g_variant_unref(sunk);
    return s;
}

#define ASSERT_PRINTS(variant, expected)     \
    G_STMT_START {                           \
        gchar *_s = print_and_free(variant); \
        g_assert_cmpstr(_s, ==, expected);   \
        g_free(_s);                          \
    }                                        \
    G_STMT_END

/* ---- pctl_print_gvariant ---- */

static void test_print_string(void) {
    ASSERT_PRINTS(g_variant_new_string("hello world"), "hello world");
    ASSERT_PRINTS(g_variant_new_string(""), "");
}

static void test_print_string_array(void) {
    const gchar *three[] = {"a", "b", "c", NULL};
    ASSERT_PRINTS(g_variant_new_strv(three, -1), "a, b, c");
    const gchar *one[] = {"solo", NULL};
    ASSERT_PRINTS(g_variant_new_strv(one, -1), "solo");
    ASSERT_PRINTS(g_variant_new_strv(NULL, 0), "");
}

static void test_print_object_path(void) {
    /* 'o' is not 's', so it goes through g_variant_print (quoted) */
    ASSERT_PRINTS(g_variant_new_object_path("/org/mpris/Track/1"), "'/org/mpris/Track/1'");
}

static void test_print_numbers(void) {
    ASSERT_PRINTS(g_variant_new_boolean(TRUE), "true");
    ASSERT_PRINTS(g_variant_new_boolean(FALSE), "false");
    ASSERT_PRINTS(g_variant_new_int32(-5), "-5");
    ASSERT_PRINTS(g_variant_new_int64(123456789012), "123456789012");
    ASSERT_PRINTS(g_variant_new_uint64(18446744073709551615ULL), "18446744073709551615");
    ASSERT_PRINTS(g_variant_new_double(0.5), "0.5");
    ASSERT_PRINTS(g_variant_new_double(3.0), "3.0");
    ASSERT_PRINTS(g_variant_new_byte(7), "0x07");
}

static void test_print_dict(void) {
    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&b, "{sv}", "k", g_variant_new_int32(1));
    ASSERT_PRINTS(g_variant_builder_end(&b), "{'k': <1>}");
}

static void test_print_nested(void) {
    GVariant *items[] = {g_variant_new_string("x"), g_variant_new_int32(2)};
    ASSERT_PRINTS(g_variant_new_tuple(items, 2), "('x', 2)");

    GVariantBuilder b;
    g_variant_builder_init(&b, G_VARIANT_TYPE("aas"));
    g_variant_builder_open(&b, G_VARIANT_TYPE("as"));
    g_variant_builder_add(&b, "s", "p");
    g_variant_builder_add(&b, "s", "q");
    g_variant_builder_close(&b);
    ASSERT_PRINTS(g_variant_builder_end(&b), "[['p', 'q']]");
}

static void test_print_null(void) {
    /* Intended: a NULL variant prints as an empty string without criticals. */
    gchar *s = pctl_print_gvariant(NULL);
    g_assert_cmpstr(s, ==, "");
    g_free(s);
}

/* ---- playback / loop status ---- */

static void test_parse_playback_status(void) {
    PlayerctlPlaybackStatus st = PLAYERCTL_PLAYBACK_STATUS_STOPPED;
    g_assert_true(pctl_parse_playback_status("Playing", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_PLAYBACK_STATUS_PLAYING);
    g_assert_true(pctl_parse_playback_status("paused", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_PLAYBACK_STATUS_PAUSED);
    g_assert_true(pctl_parse_playback_status("STOPPED", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_PLAYBACK_STATUS_STOPPED);

    st = PLAYERCTL_PLAYBACK_STATUS_PAUSED;
    g_assert_false(pctl_parse_playback_status("bogus", &st));
    g_assert_false(pctl_parse_playback_status("", &st));
    g_assert_false(pctl_parse_playback_status(NULL, &st));
    g_assert_cmpint(st, ==, PLAYERCTL_PLAYBACK_STATUS_PAUSED); /* untouched */
}

static void test_parse_loop_status(void) {
    PlayerctlLoopStatus st = PLAYERCTL_LOOP_STATUS_PLAYLIST;
    g_assert_true(pctl_parse_loop_status("None", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_LOOP_STATUS_NONE);
    g_assert_true(pctl_parse_loop_status("track", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_LOOP_STATUS_TRACK);
    g_assert_true(pctl_parse_loop_status("PLAYLIST", &st));
    g_assert_cmpint(st, ==, PLAYERCTL_LOOP_STATUS_PLAYLIST);

    st = PLAYERCTL_LOOP_STATUS_TRACK;
    g_assert_false(pctl_parse_loop_status("sideways", &st));
    g_assert_false(pctl_parse_loop_status("", &st));
    g_assert_false(pctl_parse_loop_status(NULL, &st));
    g_assert_cmpint(st, ==, PLAYERCTL_LOOP_STATUS_TRACK);
}

static void test_status_to_string(void) {
    g_assert_cmpstr(pctl_playback_status_to_string(PLAYERCTL_PLAYBACK_STATUS_PLAYING), ==,
                    "Playing");
    g_assert_cmpstr(pctl_playback_status_to_string(PLAYERCTL_PLAYBACK_STATUS_PAUSED), ==, "Paused");
    g_assert_cmpstr(pctl_playback_status_to_string(PLAYERCTL_PLAYBACK_STATUS_STOPPED), ==,
                    "Stopped");
    g_assert_null(pctl_playback_status_to_string((PlayerctlPlaybackStatus)99));
    g_assert_cmpstr(pctl_loop_status_to_string(PLAYERCTL_LOOP_STATUS_NONE), ==, "None");
    g_assert_cmpstr(pctl_loop_status_to_string(PLAYERCTL_LOOP_STATUS_TRACK), ==, "Track");
    g_assert_cmpstr(pctl_loop_status_to_string(PLAYERCTL_LOOP_STATUS_PLAYLIST), ==, "Playlist");
    g_assert_null(pctl_loop_status_to_string((PlayerctlLoopStatus)99));
}

/* ---- bus type <-> source ---- */

static void test_source_to_bus_type(void) {
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_DBUS_SESSION), ==, G_BUS_TYPE_SESSION);
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_DBUS_SYSTEM), ==, G_BUS_TYPE_SYSTEM);
    g_assert_cmpint(pctl_source_to_bus_type(PLAYERCTL_SOURCE_NONE), ==, G_BUS_TYPE_NONE);
}

static void test_bus_type_to_source(void) {
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_SESSION), ==, PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_SYSTEM), ==, PLAYERCTL_SOURCE_DBUS_SYSTEM);

    g_test_expect_message("playerctl", G_LOG_LEVEL_WARNING, "could not convert bus type*");
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_NONE), ==, PLAYERCTL_SOURCE_NONE);
    g_test_assert_expected_messages();

    g_test_expect_message("playerctl", G_LOG_LEVEL_WARNING, "could not convert bus type*");
    g_assert_cmpint(pctl_bus_type_to_source(G_BUS_TYPE_STARTER), ==, PLAYERCTL_SOURCE_NONE);
    g_test_assert_expected_messages();
}

/* ---- player names ---- */

static void test_name_new(void) {
    PlayerctlPlayerName *n = pctl_player_name_new("vlc.instance123", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_cmpstr(n->name, ==, "vlc");
    g_assert_cmpstr(n->instance, ==, "vlc.instance123");
    g_assert_cmpint(n->source, ==, PLAYERCTL_SOURCE_DBUS_SESSION);
    playerctl_player_name_free(n);

    n = pctl_player_name_new("mpd", PLAYERCTL_SOURCE_DBUS_SYSTEM);
    g_assert_cmpstr(n->name, ==, "mpd");
    g_assert_cmpstr(n->instance, ==, "mpd");
    playerctl_player_name_free(n);

    /* only the first dot splits */
    n = pctl_player_name_new("a.b.c", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_cmpstr(n->name, ==, "a");
    g_assert_cmpstr(n->instance, ==, "a.b.c");
    playerctl_player_name_free(n);
}

static void test_name_compare(void) {
    PlayerctlPlayerName *a = pctl_player_name_new("alpha", PLAYERCTL_SOURCE_DBUS_SESSION);
    PlayerctlPlayerName *a2 = pctl_player_name_new("alpha", PLAYERCTL_SOURCE_DBUS_SESSION);
    PlayerctlPlayerName *b = pctl_player_name_new("beta", PLAYERCTL_SOURCE_DBUS_SESSION);
    PlayerctlPlayerName *as = pctl_player_name_new("alpha", PLAYERCTL_SOURCE_DBUS_SYSTEM);

    g_assert_cmpint(pctl_player_name_compare(a, a2), ==, 0);
    g_assert_cmpint(pctl_player_name_compare(a, b), <, 0);
    g_assert_cmpint(pctl_player_name_compare(b, a), >, 0);
    g_assert_cmpint(pctl_player_name_compare(a, as), !=, 0); /* different source */

    playerctl_player_name_free(a);
    playerctl_player_name_free(a2);
    playerctl_player_name_free(b);
    playerctl_player_name_free(as);
}

static void test_string_instance_compare(void) {
    /* (name, instance): 0 when instance is the name or one of its instances */
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc", "vlc"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc", "vlc.instance1"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc", "vlcfoo"), !=, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc", "mpd"), !=, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("%any", "whatever"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("whatever", "%any"), ==, 0);
    g_assert_cmpint(pctl_player_name_string_instance_compare("vlc.instance1", "vlc"), !=, 0);
}

static void test_instance_compare(void) {
    PlayerctlPlayerName *name = pctl_player_name_new("vlc", PLAYERCTL_SOURCE_DBUS_SESSION);
    PlayerctlPlayerName *inst = pctl_player_name_new("vlc.i1", PLAYERCTL_SOURCE_DBUS_SESSION);
    PlayerctlPlayerName *inst_sys = pctl_player_name_new("vlc.i1", PLAYERCTL_SOURCE_DBUS_SYSTEM);
    PlayerctlPlayerName *any = pctl_player_name_new("%any", PLAYERCTL_SOURCE_DBUS_SESSION);

    g_assert_cmpint(pctl_player_name_instance_compare(name, inst), ==, 0);
    g_assert_cmpint(pctl_player_name_instance_compare(name, inst_sys), !=, 0);
    g_assert_cmpint(pctl_player_name_instance_compare(name, any), ==, 0);

    playerctl_player_name_free(name);
    playerctl_player_name_free(inst);
    playerctl_player_name_free(inst_sys);
    playerctl_player_name_free(any);
}

static GList *make_list(void) {
    GList *l = NULL;
    l = g_list_append(l, pctl_player_name_new("vlc", PLAYERCTL_SOURCE_DBUS_SESSION));
    l = g_list_append(l, pctl_player_name_new("create.instance123", PLAYERCTL_SOURCE_DBUS_SESSION));
    l = g_list_append(l, pctl_player_name_new("mpd", PLAYERCTL_SOURCE_DBUS_SYSTEM));
    return l;
}

static void test_name_find(void) {
    GList *l = make_list();
    GList *hit = pctl_player_name_find(l, "create.instance123", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_nonnull(hit);
    g_assert_cmpstr(((PlayerctlPlayerName *)hit->data)->instance, ==, "create.instance123");

    /* find() is an exact-instance lookup */
    g_assert_null(pctl_player_name_find(l, "create", PLAYERCTL_SOURCE_DBUS_SESSION));
    /* source must match */
    g_assert_null(pctl_player_name_find(l, "vlc", PLAYERCTL_SOURCE_DBUS_SYSTEM));
    g_assert_nonnull(pctl_player_name_find(l, "mpd", PLAYERCTL_SOURCE_DBUS_SYSTEM));
    g_assert_null(pctl_player_name_find(NULL, "vlc", PLAYERCTL_SOURCE_DBUS_SESSION));
    pctl_player_name_list_destroy(l);
}

static void test_name_find_instance(void) {
    GList *l = make_list();
    GList *hit;

    hit = pctl_player_name_find_instance(l, "vlc", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_nonnull(hit);
    g_assert_cmpstr(((PlayerctlPlayerName *)hit->data)->instance, ==, "vlc");

    hit = pctl_player_name_find_instance(l, "mpd", PLAYERCTL_SOURCE_DBUS_SYSTEM);
    g_assert_nonnull(hit);

    g_assert_null(pctl_player_name_find_instance(l, "mpd", PLAYERCTL_SOURCE_DBUS_SESSION));
    g_assert_null(pctl_player_name_find_instance(l, "nothere", PLAYERCTL_SOURCE_DBUS_SESSION));
    pctl_player_name_list_destroy(l);
}

static void test_name_find_instance_by_base_name(void) {
    /* Intended: searching for the base name "create" finds the running
     * instance "create.instance123". pctl_player_name_find_instance hands the
     * (list item, search key) pair to pctl_player_name_instance_compare, whose
     * parameters are (name, instance), so the roles are reversed and the
     * prefix test is made the wrong way round. */
    GList *l = make_list();
    GList *hit = pctl_player_name_find_instance(l, "create", PLAYERCTL_SOURCE_DBUS_SESSION);
    g_assert_nonnull(hit);
    if (hit != NULL) {
        g_assert_cmpstr(((PlayerctlPlayerName *)hit->data)->instance, ==, "create.instance123");
    }
    pctl_player_name_list_destroy(l);
}

static void test_name_list_destroy(void) {
    pctl_player_name_list_destroy(NULL);
    pctl_player_name_list_destroy(make_list());
}

/* ---- pctl_list_player_names_on_bus without a bus ---- */

static void test_list_names_session_socket_missing(void) {
    /* unreachable session bus socket: documented to warn and return an empty list */
    g_setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/nonexistent/playerctl-test-bus", TRUE);
    GError *err = NULL;
    g_test_expect_message("playerctl", G_LOG_LEVEL_WARNING, "*socket address not found*");
    GList *l = pctl_list_player_names_on_bus(G_BUS_TYPE_SESSION, &err);
    g_test_assert_expected_messages();
    g_assert_null(l);
    g_assert_no_error(err);
}

static void test_list_names_system_socket_missing(void) {
    /* same on the system bus, but only logged at debug level */
    g_setenv("DBUS_SYSTEM_BUS_ADDRESS", "unix:path=/nonexistent/playerctl-test-bus", TRUE);
    GError *err = NULL;
    GList *l = pctl_list_player_names_on_bus(G_BUS_TYPE_SYSTEM, &err);
    g_assert_null(l);
    g_assert_no_error(err);
}

static void test_list_names_invalid_address(void) {
    /* an unparseable address is not "not found": the error is propagated */
    g_setenv("DBUS_SESSION_BUS_ADDRESS", "this-is-not-an-address", TRUE);
    GError *err = NULL;
    GList *l = pctl_list_player_names_on_bus(G_BUS_TYPE_SESSION, &err);
    g_assert_null(l);
    g_assert_nonnull(err);
    g_clear_error(&err);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    g_test_set_nonfatal_assertions();
    g_test_add_data_func("/common/print/string", (gconstpointer)test_print_string, run_isolated);
    g_test_add_data_func("/common/print/string-array", (gconstpointer)test_print_string_array,
                         run_isolated);
    g_test_add_data_func("/common/print/object-path", (gconstpointer)test_print_object_path,
                         run_isolated);
    g_test_add_data_func("/common/print/numbers", (gconstpointer)test_print_numbers, run_isolated);
    g_test_add_data_func("/common/print/dict", (gconstpointer)test_print_dict, run_isolated);
    g_test_add_data_func("/common/print/nested", (gconstpointer)test_print_nested, run_isolated);
    g_test_add_data_func("/common/print/null", (gconstpointer)test_print_null, run_isolated);
    g_test_add_data_func("/common/status/parse-playback", (gconstpointer)test_parse_playback_status,
                         run_isolated);
    g_test_add_data_func("/common/status/parse-loop", (gconstpointer)test_parse_loop_status,
                         run_isolated);
    g_test_add_data_func("/common/status/to-string", (gconstpointer)test_status_to_string,
                         run_isolated);
    g_test_add_data_func("/common/bus/source-to-bus-type", (gconstpointer)test_source_to_bus_type,
                         run_isolated);
    g_test_add_data_func("/common/bus/bus-type-to-source", (gconstpointer)test_bus_type_to_source,
                         run_isolated);
    g_test_add_data_func("/common/name/new", (gconstpointer)test_name_new, run_isolated);
    g_test_add_data_func("/common/name/compare", (gconstpointer)test_name_compare, run_isolated);
    g_test_add_data_func("/common/name/string-instance-compare",
                         (gconstpointer)test_string_instance_compare, run_isolated);
    g_test_add_data_func("/common/name/instance-compare", (gconstpointer)test_instance_compare,
                         run_isolated);
    g_test_add_data_func("/common/name/find", (gconstpointer)test_name_find, run_isolated);
    g_test_add_data_func("/common/name/find-instance", (gconstpointer)test_name_find_instance,
                         run_isolated);
    g_test_add_data_func("/common/name/find-instance-by-base-name",
                         (gconstpointer)test_name_find_instance_by_base_name, run_isolated);
    g_test_add_data_func("/common/name/list-destroy", (gconstpointer)test_name_list_destroy,
                         run_isolated);
    g_test_add_data_func("/common/bus/list-names-session-socket-missing",
                         (gconstpointer)test_list_names_session_socket_missing, run_isolated);
    g_test_add_data_func("/common/bus/list-names-system-socket-missing",
                         (gconstpointer)test_list_names_system_socket_missing, run_isolated);
    g_test_add_data_func("/common/bus/list-names-invalid-address",
                         (gconstpointer)test_list_names_invalid_address, run_isolated);
    return g_test_run();
}

/* Unit tests for PlayerctlPlayerName (copy/free). */

#include <glib.h>
#include <playerctl/playerctl-player-name.h>

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

static PlayerctlPlayerName *make_name(void) {
    PlayerctlPlayerName *n = g_slice_new0(PlayerctlPlayerName);
    n->name = g_strdup("vlc");
    n->instance = g_strdup("vlc.instance42");
    n->source = PLAYERCTL_SOURCE_DBUS_SYSTEM;
    return n;
}

static void test_copy_is_deep(void) {
    PlayerctlPlayerName *orig = make_name();
    PlayerctlPlayerName *copy = playerctl_player_name_copy(orig);

    g_assert_nonnull(copy);
    g_assert_true(copy != orig);
    g_assert_cmpstr(copy->name, ==, "vlc");
    g_assert_cmpstr(copy->instance, ==, "vlc.instance42");
    g_assert_cmpint(copy->source, ==, PLAYERCTL_SOURCE_DBUS_SYSTEM);
    g_assert_true(copy->name != orig->name);
    g_assert_true(copy->instance != orig->instance);

    /* the copy must survive the original being freed */
    playerctl_player_name_free(orig);
    g_assert_cmpstr(copy->instance, ==, "vlc.instance42");
    playerctl_player_name_free(copy);
}

static void test_copy_null(void) {
    /* g_return_val_if_fail(name != NULL) emits a critical and returns NULL */
    g_test_expect_message("playerctl", G_LOG_LEVEL_CRITICAL, "*playerctl_player_name_copy*");
    g_assert_null(playerctl_player_name_copy(NULL));
    g_test_assert_expected_messages();
}

static void test_free_null(void) {
    playerctl_player_name_free(NULL);
}

static void test_boxed_type(void) {
    GType type = playerctl_player_name_get_type();
    g_assert_true(G_TYPE_IS_BOXED(type));
    g_assert_cmpstr(g_type_name(type), ==, "PlayerctlPlayerName");

    PlayerctlPlayerName *orig = make_name();
    gpointer copy = g_boxed_copy(type, orig);
    g_assert_cmpstr(((PlayerctlPlayerName *)copy)->instance, ==, "vlc.instance42");
    g_boxed_free(type, copy);
    playerctl_player_name_free(orig);
}

int main(int argc, char **argv) {
    g_test_init(&argc, &argv, NULL);
    g_test_set_nonfatal_assertions();
    g_test_add_data_func("/player-name/copy-is-deep", (gconstpointer)test_copy_is_deep,
                         run_isolated);
    g_test_add_data_func("/player-name/copy-null", (gconstpointer)test_copy_null, run_isolated);
    g_test_add_data_func("/player-name/free-null", (gconstpointer)test_free_null, run_isolated);
    g_test_add_data_func("/player-name/boxed-type", (gconstpointer)test_boxed_type, run_isolated);
    return g_test_run();
}

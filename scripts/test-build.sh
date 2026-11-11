# shellcheck shell=bash
# Sourced by the test scripts inside the playerctl-test image, with the repo
# mounted in the working directory.
#
#   . scripts/test-build.sh
#   test_build DIR [meson setup options]
#
# Configures DIR (once; the options only matter then; the API docs are not built:
# the tests do not need them and gtk-doc cannot run an ASAN build), builds it incrementally
# and installs it into the container's /usr, so D-Bus activation finds
# playerctld. The image holds no build, DIR lives in the mounted repo (build/test/*)
# and survives between runs. PATH and the library paths point to DIR as well.
test_build() {
	local dir=$1
	shift
	[ -f "$dir/build.ninja" ] || meson setup --prefix=/usr -Dgtk-doc=false "$dir" "$@" >/dev/null || return 1
	ninja -C "$dir" >/dev/null || return 1
	ninja -C "$dir" install >/dev/null || return 1
	export PATH="$PWD/$dir/playerctl:$PATH"
	export LD_LIBRARY_PATH="$PWD/$dir/playerctl${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
	export GI_TYPELIB_PATH="$PWD/$dir/playerctl${GI_TYPELIB_PATH:+:$GI_TYPELIB_PATH}"
}

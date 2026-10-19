.PHONY: manifests manifests-sync manifests-check package-slug contributors contributors-check contributors-duplicates help dev-image build docs test test-local test-container test-c docker-test coverage all \
	dist dist-check package packages package-lint packages-lint package-test packages-test release-assets \
	format format-py format-c format-yaml format-md \
	format-check format-check-py format-check-c format-check-yaml format-check-md \
	lint lint-py lint-c lint-sh
.DEFAULT_GOAL := help

FORMAT_C_SOURCE = $(shell find playerctl | grep \.[ch]$)
PY_DIRS = test examples scripts
YAML_SOURCE = $(shell find . \( -name build -o -name .venv -o -name .git \) -prune -o \( -name '*.yml' -o -name '*.yaml' \) -type f -print)
MD_SOURCE = $(shell find . \( -name build -o -name .venv -o -name .git \) -prune -o -name '*.md' ! -name LICENSE.md -type f -print)
SH_SOURCE = data/playerctl.bash $(wildcard scripts/*.sh)
help: ## show this help
	@awk 'BEGIN {FS = ":.*## "; print "Usage: make [target]\n\nTargets:"} /^[a-zA-Z_-]+:.*## / {printf "  %-18s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

# Container engine: podman if available, else docker (override with CONTAINER_ENGINE=...)
CONTAINER_ENGINE ?= $(firstword $(notdir $(shell which podman docker 2>/dev/null)))

# Fail with a clear message when a tool is missing: $(call require,tool...)
require = @for t in $(1); do command -v $$t >/dev/null || { echo "No $$t in PATH" >&2; exit 1; }; done

# By default the format, lint and build targets run inside the tooling image
# (Dockerfile.dev) so they only need podman or docker. Use CONTAINER=0 to run the
# tools from the host instead (needs uv, shellcheck and the glib dev packages;
# clang-format and clang-tidy come from the pinned uv "lint" group).
CONTAINER ?= 1
DEV_IMAGE = playerctl-dev

ifeq ($(CONTAINER),1)
# Docker runs as root by default, which would leave root-owned files in the repo
ifeq ($(notdir $(CONTAINER_ENGINE)),docker)
CONTAINER_USER = --user $(shell id -u):$(shell id -g) -e HOME=/tmp
endif
RUN = $(CONTAINER_ENGINE) run --rm $(CONTAINER_USER) $(RUN_ARGS) -v "$(CURDIR)":/src:Z -w /src $(DEV_IMAGE)
DEV_DEPS = dev-image
BUILD_DIR = build/container
# $(call need,tool...): what a target requires in the current mode
need = $(CONTAINER_ENGINE)
else
RUN =
DEV_DEPS =
BUILD_DIR = build
need = $(1)
endif

dev-image: ## build the tooling image used by the format, lint and build targets
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) build -q -f Dockerfile.dev -t $(DEV_IMAGE) .

# The tests run plain `playerctl`/`playerctld` from PATH, so put the meson build
# first to avoid silently testing a system-wide install.
BUILD_BIN = $(CURDIR)/build/playerctl

build: $(DEV_DEPS) ## build playerctl with meson + ninja (build/container, or build with CONTAINER=0)
	$(call require,$(call need,uv))
	@test -f $(BUILD_DIR)/build.ninja || $(RUN) uv run meson setup $(BUILD_DIR)
	$(RUN) uv run meson compile -C $(BUILD_DIR)

# gtk-doc is not part of the default meson target, so build playerctl-doc explicitly
docs: build ## build the API docs (HTML in build/container/doc/reference/html, or build/doc/reference/html with CONTAINER=0)
	$(RUN) uv run meson compile -C $(BUILD_DIR) doc/reference/playerctl-doc:alias
	@test -f $(BUILD_DIR)/doc/reference/html/index.html || { echo "No docs generated in $(BUILD_DIR)/doc/reference/html" >&2; exit 1; }
	@echo "API docs: $(BUILD_DIR)/doc/reference/html/index.html"

# Packaging: the supported releases of each distribution (Debian 12 and the
# Ubuntu LTS releases are in long term support). Everything runs in containers: the tarball in the tooling image,
# each package in a container of the distro it is for (podman or docker).
# Output: build/dist (tarball), build/packages/<distro>-<arch>, build/release.
VERSION = $(shell sed -n "s/^version: '\(.*\)'$$/\1/p" packaging/package.yaml)
DIST_DIR = build/dist
PKG_DIR = build/packages
RELEASE_DIR = build/release
TARBALL = $(DIST_DIR)/playerctl-$(VERSION).tar.xz
PKG_ARCH = $(patsubst arm64,aarch64,$(shell uname -m))

# PKG_DISTROS, IMAGE_* and TYPE_* come from packaging/package.yaml, as do the
# manifests: they are rendered into PKG_GEN_DIR by `make manifests`
PKG_GEN_DIR = build/packaging
ifneq ($(filter package% release-assets,$(MAKECMDGOALS)),)
include $(PKG_GEN_DIR)/distros.mk
endif

DISTRO ?=
distro_image = $(or $(IMAGE_$(DISTRO)),$(error set DISTRO to one of: $(PKG_DISTROS)))
distro_dir = $(PKG_DIR)/$(DISTRO)-$(PKG_ARCH)
# the name of the DISTRO packages in the release and in the CI artifacts
package_slug = playerctl-$(or $(SLUG_$(DISTRO)),$(error set DISTRO to one of: $(PKG_DISTROS)))-$(PKG_ARCH)

# Docker runs as real root: let package-build.sh hand the files back
ifeq ($(notdir $(CONTAINER_ENGINE)),docker)
PKG_USER_ENV = -e HOST_UID=$(shell id -u) -e HOST_GID=$(shell id -g)
endif

# meson dist reads the git history. In a git worktree .git is a file pointing
# outside the checkout, so the git directory is mounted as well. Inside the
# container the files have another inode, device and owner than the ones in the
# index, which makes git see every file as modified and meson refuse to run on a
# clean tree; core.checkstat=minimal compares only the size and mtime, so real
# changes are still found.
DIST_FLAGS ?=
ifeq ($(CONTAINER),1)
GIT_COMMON_DIR = $(shell git rev-parse --path-format=absolute --git-common-dir)
RUN_GIT = $(CONTAINER_ENGINE) run --rm $(CONTAINER_USER) \
	-e GIT_CONFIG_COUNT=2 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
	-e GIT_CONFIG_KEY_1=core.checkstat -e GIT_CONFIG_VALUE_1=minimal \
	-v "$(CURDIR)":/src:Z -v "$(GIT_COMMON_DIR)":"$(GIT_COMMON_DIR)":ro,z -w /src $(DEV_IMAGE)
else
RUN_GIT =
endif

dist: build ## build the source tarball (meson dist, only the files needed to build it) in build/dist; DIST_FLAGS=--allow-dirty for uncommitted changes
	rm -rf $(DIST_DIR) $(BUILD_DIR)/meson-dist
	mkdir -p $(DIST_DIR)
	$(RUN_GIT) uv run meson dist -C $(BUILD_DIR) --formats xztar --no-tests $(DIST_FLAGS)
	cp $(BUILD_DIR)/meson-dist/playerctl-$(VERSION).tar.xz* $(DIST_DIR)/

dist-check: $(DEV_DEPS) ## fail if the tarball in build/dist holds files outside the allowlist
	$(RUN) scripts/dist-check.sh $(TARBALL)

MANIFEST_SOURCES = packaging/package.yaml $(shell find packaging/templates -type f) scripts/render-packaging.py doc/CHANGELOG.md

manifests: $(DEV_DEPS) ## render the package manifests from packaging/package.yaml and packaging/templates into build/packaging
	$(call require,$(call need,uv))
	$(RUN_GIT) uv run --group packaging scripts/render-packaging.py --out $(PKG_GEN_DIR)

manifests-sync: $(DEV_DEPS) ## copy the version from packaging/package.yaml to meson.build, pyproject.toml and uv.lock, and update the distro table in doc/installing.md
	$(call require,$(call need,uv))
	$(RUN) uv run --group packaging scripts/render-packaging.py --sync

manifests-check: $(DEV_DEPS) ## fail if the version copies or the distro table in doc/installing.md are out of date
	$(call require,$(call need,uv))
	$(RUN_GIT) uv run --group packaging scripts/render-packaging.py --check

# distros.mk is included while parsing, so make renders it first when it is
# missing or older than its sources
$(PKG_GEN_DIR)/distros.mk: $(MANIFEST_SOURCES)
	$(MAKE) manifests

package-slug: ## print the name of the packages built for DISTRO in the release and the CI artifacts, e.g. playerctl-fedora-43-x86_64
	@echo $(package_slug)

package: ## build the package for DISTRO from the tarball in build/dist, in that distro's container into build/packages (DISTRO: see PKG_DISTROS)
	$(call require,$(CONTAINER_ENGINE))
	@test -f $(TARBALL) || { echo "No $(TARBALL), run make dist first" >&2; exit 1; }
	@test -f $(PKG_GEN_DIR)/distros.mk || { echo "No $(PKG_GEN_DIR), run make manifests first" >&2; exit 1; }
	$(CONTAINER_ENGINE) run --rm $(PKG_USER_ENV) -v "$(CURDIR)":/src:z -w /src $(distro_image) \
		scripts/package-build.sh $(TYPE_$(DISTRO)) $(TARBALL) $(distro_dir) $(PKG_GEN_DIR)

packages: dist manifests ## build the packages for every distro in PKG_DISTROS
	@failed=; for d in $(PKG_DISTROS); do $(MAKE) package DISTRO=$$d || failed="$$failed $$d"; done; \
	test -z "$$failed" || { echo "Failed:$$failed" >&2; exit 1; }

package-lint: ## lint the packages built for DISTRO (rpmlint, lintian or namcap, in that distro's container)
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR)/scripts":/scripts:ro,z -v "$(CURDIR)/$(distro_dir)":/pkgs:ro,z \
		$(distro_image) /scripts/package-lint.sh /pkgs

packages-lint: ## lint the packages of every distro in PKG_DISTROS
	@failed=; for d in $(PKG_DISTROS); do $(MAKE) package-lint DISTRO=$$d || failed="$$failed $$d"; done; \
	test -z "$$failed" || { echo "Failed:$$failed" >&2; exit 1; }

package-test: ## install the packages built for DISTRO in a fresh container of that distro and check them
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR)/scripts":/scripts:ro,z -v "$(CURDIR)/$(distro_dir)":/pkgs:ro,z \
		$(distro_image) /scripts/package-test.sh /pkgs $(VERSION)

packages-test: ## install-test the packages of every distro in PKG_DISTROS
	@failed=; for d in $(PKG_DISTROS); do $(MAKE) package-test DISTRO=$$d || failed="$$failed $$d"; done; \
	test -z "$$failed" || { echo "Failed:$$failed" >&2; exit 1; }

release-assets: RUN_ARGS = -e GPG_PRIVATE_KEY
release-assets: $(DEV_DEPS) ## collect tarball, packages and SHA256SUMS in build/release (signed if GPG_PRIVATE_KEY is set)
	$(RUN) uv run --group packaging scripts/release-assets.sh $(DIST_DIR) $(PKG_DIR) $(RELEASE_DIR)

test-local: ## build with meson on the host (CONTAINER=0), then run the pytest suite against ./build (needs glib dev packages and dbus-run-session)
	$(call require,uv dbus-run-session)
	$(MAKE) build CONTAINER=0
	PATH=$(BUILD_BIN):$$PATH GI_TYPELIB_PATH=$(BUILD_BIN) LD_LIBRARY_PATH=$(BUILD_BIN) dbus-run-session uv run --group gi pytest -sq

test-container: ## build the image and run the tests in a container (podman or docker)
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) build -t playerctl-test .
	$(CONTAINER_ENGINE) run --rm $(if $(shell [ -t 0 ] && echo tty),-it) playerctl-test

test-c: ## build and run the C unit tests (test/c) with meson test in the test image
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) build -t playerctl-test .
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR):/src:Z" -w /src playerctl-test bash -c "meson setup /tmp/build-c -Dtests=true >/dev/null && ninja -C /tmp/build-c >/dev/null && meson test -C /tmp/build-c --print-errorlogs"

test: test-container ## run the tests in a container (alias for test-container)

coverage: ## run the tests against a gcov-instrumented build in the test image; reports in build/coverage
	$(call require,$(CONTAINER_ENGINE))
	$(CONTAINER_ENGINE) build -t playerctl-test .
	mkdir -p build/coverage
	$(CONTAINER_ENGINE) run --rm -v "$(CURDIR)/test:/app/test:Z" -v "$(CURDIR)/scripts:/app/scripts:Z" -v "$(CURDIR)/build/coverage:/out:Z" playerctl-test bash scripts/coverage.sh

# docker-test kept as an alias for test-container
docker-test: test-container ## alias for test-container

# Formatting: rewrite files in place
format: format-py format-c format-yaml format-md contributors ## format Python, C, YAML and Markdown sources in place and update CONTRIBUTORS.md

format-py: $(DEV_DEPS) ## format Python sources in place (ruff)
	$(call require,$(call need,uv))
	$(RUN) uv run ruff format $(PY_DIRS)

format-c: $(DEV_DEPS) ## format C sources in place (clang-format)
	$(call require,$(call need,uv))
	$(RUN) uv run --group lint clang-format -i ${FORMAT_C_SOURCE}

format-yaml: $(DEV_DEPS) ## format YAML files in place (yamlfmt)
	$(call require,$(call need,yamlfmt))
	$(RUN) yamlfmt ${YAML_SOURCE}

format-md: $(DEV_DEPS) ## format Markdown files in place (markdownfmt)
	$(call require,$(call need,markdownfmt))
	$(RUN) markdownfmt -w ${MD_SOURCE}

# Formatting: fail on violations without changing files
format-check: format-check-py format-check-c format-check-yaml format-check-md ## check Python, C, YAML and Markdown formatting without changing files

format-check-py: $(DEV_DEPS) ## check Python formatting (ruff)
	$(call require,$(call need,uv))
	$(RUN) uv run ruff format --check $(PY_DIRS)

format-check-c: $(DEV_DEPS) ## check C formatting (clang-format)
	$(call require,$(call need,uv))
	$(RUN) uv run --group lint clang-format --dry-run --Werror ${FORMAT_C_SOURCE}

format-check-yaml: $(DEV_DEPS) ## check YAML formatting (yamlfmt)
	$(call require,$(call need,yamlfmt))
	$(RUN) yamlfmt -lint ${YAML_SOURCE}

format-check-md: $(DEV_DEPS) ## check Markdown formatting (markdownfmt)
	$(call require,$(call need,markdownfmt))
	@out=$$($(RUN) markdownfmt -l ${MD_SOURCE}); \
	test -z "$$out" || { echo "Not formatted:"; echo "$$out"; exit 1; }

# Linting
lint: lint-py lint-c lint-sh ## lint Python, C and shell sources

lint-py: $(DEV_DEPS) ## lint Python sources (ruff)
	$(call require,$(call need,uv))
	$(RUN) uv run ruff check $(PY_DIRS)

# clang-tidy needs a compile database, which meson generates (this needs the
# glib/gobject-introspection dev packages, see Dockerfile.dev). The sources
# include generated headers, so compile once to create them.
$(BUILD_DIR)/compile_commands.json: $(DEV_DEPS)
	$(call require,$(call need,uv))
	$(RUN) uv run meson setup $(BUILD_DIR)
	$(RUN) uv run meson compile -C $(BUILD_DIR)

# Findings are warnings by default; CI passes CLANG_TIDY_FLAGS="--warnings-as-errors=*"
CLANG_TIDY_FLAGS ?=

lint-c: $(BUILD_DIR)/compile_commands.json ## lint C sources (clang-tidy, needs a meson build dir)
	$(call require,$(call need,uv))
	$(RUN) uv run --group lint clang-tidy -p $(BUILD_DIR) --quiet $(CLANG_TIDY_FLAGS) $(filter %.c,${FORMAT_C_SOURCE})

lint-sh: $(DEV_DEPS) ## lint shell scripts (shellcheck)
	$(call require,$(call need,shellcheck))
	$(RUN) shellcheck $(SH_SOURCE)

# Contributors: read from the git history, so these run on the host
contributors: ## add authors of C code from the git history to CONTRIBUTORS.md
	python3 scripts/update-contributors.py

contributors-check: ## fail if CONTRIBUTORS.md misses an author of C code
	python3 scripts/update-contributors.py --check

contributors-duplicates: ## list contributor identities that look like the same person (fix with .mailmap)
	python3 scripts/update-contributors.py --duplicates

all: format-check lint test ## check formatting, lint, then run the container tests

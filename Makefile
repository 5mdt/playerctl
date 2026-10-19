.PHONY: contributors contributors-check contributors-duplicates help dev-image build docs test test-local test-container test-c docker-test coverage all \
	format format-py format-c format-yaml format-md \
	format-check format-check-py format-check-c format-check-yaml format-check-md \
	lint lint-py lint-c lint-sh
.DEFAULT_GOAL := help

FORMAT_C_SOURCE = $(shell find playerctl | grep \.[ch]$)
PY_DIRS = test examples scripts
YAML_SOURCE = $(shell find . \( -name build -o -name .venv -o -name .git \) -prune -o \( -name '*.yml' -o -name '*.yaml' \) -type f -print)
MD_SOURCE = $(shell find . \( -name build -o -name .venv -o -name .git \) -prune -o -name '*.md' ! -name LICENSE.md -type f -print)
SH_SOURCE = fpm-packages.sh data/playerctl.bash
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
RUN = $(CONTAINER_ENGINE) run --rm $(CONTAINER_USER) -v "$(CURDIR)":/src:Z -w /src $(DEV_IMAGE)
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

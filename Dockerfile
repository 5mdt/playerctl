ARG UBUNTU_VERSION=24.04
ARG UV_VERSION=0.8.0

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM ubuntu:${UBUNTU_VERSION}

# Toolchain and Python environment only: the repo is bind-mounted at /app by
# the Makefile and playerctl is built inside the container (build/test/*), so
# this image changes only with this file, pyproject.toml, uv.lock or the dbus conf.

RUN export DEBIAN_FRONTEND=noninteractive; \
    export DEBCONF_NONINTERACTIVE_SEEN=true; \
    echo 'tzdata tzdata/Areas select Etc' | debconf-set-selections; \
    echo 'tzdata tzdata/Zones/Etc select UTC' | debconf-set-selections; \
    apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-dev \
    ninja-build \
    build-essential \
    libglib2.0-dev \
    libgirepository1.0-dev \
    libcairo2-dev \
    pkg-config \
    gtk-doc-tools \
    dbus \
    && rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv
# Keep the virtualenv outside the bind-mounted repo so it never clashes with a
# host .venv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON_PREFERENCE=only-system \
    UV_FROZEN=1
WORKDIR /opt/project
COPY pyproject.toml uv.lock ./
RUN uv sync --no-install-project --group dev --group gi
ENV PATH=/opt/venv/bin:$PATH

COPY test/data/dbus-system.conf /etc/dbus-1/system.d/test-dbus-system.conf
RUN mkdir -p /run/dbus

WORKDIR /app
ENV PYTHONASYNCIODEBUG=1
ENV DBUS_SYSTEM_BUS_ADDRESS=unix:path=/var/run/dbus/system_bus_socket
CMD ["bash", "-c", "dbus-daemon --nopidfile --system && dbus-run-session python3 -m pytest -vvs"]

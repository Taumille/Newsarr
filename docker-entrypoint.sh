#!/bin/sh
# Container entrypoint.
#
# The data directory is normally a bind mount or a named volume, and either can
# end up owned by a UID/GID that does not match the container's unprivileged
# `newsarr` user (for example a pre-existing volume or a root-owned host
# directory). That makes SQLite fail with "unable to open database file", so we
# repair ownership as root and then drop privileges before starting the app.
set -eu

data_dir="${NEWSARR_DATA_DIR:-/etc/newsarr}"
app_user="newsarr"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$data_dir"
    chown -R "${app_user}:${app_user}" "$data_dir"
    exec gosu "$app_user" "$@"
fi

exec "$@"

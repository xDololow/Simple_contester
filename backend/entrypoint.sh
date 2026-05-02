#!/bin/sh
set -eu

python -m app.migrate upgrade
exec "$@"

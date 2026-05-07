#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/restore.sh path/to/backup.sql

Restores a MariaDB SQL dump into the compose MariaDB service.
This is destructive for data in the target database. Set RESTORE_YES=1 to skip
the interactive confirmation.
USAGE
}

load_dotenv_defaults() {
  local env_file="${1:-.env}"
  [ -f "$env_file" ] || return 0

  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    line="${line#"${line%%[![:space:]]*}"}"
    line="${line%"${line##*[![:space:]]}"}"
    [ -n "$line" ] || continue
    case "$line" in
      \#* | *=*) ;;
      *) continue ;;
    esac

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"

    if [[ "$value" == \"*\" && "$value" == *\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] && [ -z "${!key+x}" ]; then
      export "$key=$value"
    fi
  done < "$env_file"
}

compose() {
  docker compose "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

if [ "$#" -ne 1 ]; then
  usage
  exit 2
fi

DUMP_FILE="$1"
if [ ! -f "$DUMP_FILE" ]; then
  echo "Dump file does not exist: $DUMP_FILE" >&2
  exit 1
fi
if [ ! -s "$DUMP_FILE" ]; then
  echo "Dump file is empty: $DUMP_FILE" >&2
  exit 1
fi

load_dotenv_defaults ".env"

require_command docker

SERVICE="${MARIADB_SERVICE:-mariadb}"
DB_NAME="${MARIADB_DATABASE:-simple_contester}"
DB_USER="${RESTORE_DB_USER:-root}"
DB_PASSWORD="${RESTORE_DB_PASSWORD:-${MARIADB_ROOT_PASSWORD:-root}}"

if ! compose ps --services --status running | grep -qx "$SERVICE"; then
  echo "MariaDB compose service '$SERVICE' is not running." >&2
  echo "Start it first, for example: docker compose up -d mariadb" >&2
  exit 1
fi

if ! compose exec -T "$SERVICE" sh -c 'command -v mariadb >/dev/null 2>&1 || command -v mysql >/dev/null 2>&1' >/dev/null; then
  echo "Neither mariadb nor mysql client was found in service '$SERVICE'." >&2
  exit 1
fi

cat >&2 <<EOF
WARNING: restore is destructive.

Target compose service: $SERVICE
Target database:        $DB_NAME
Dump file:              $DUMP_FILE

The SQL dump will be executed against MariaDB and may drop/replace existing
tables and data. Stop backend/judger services before restoring active systems.
EOF

if [ "${RESTORE_YES:-0}" != "1" ]; then
  printf 'Type "restore %s" to continue: ' "$DB_NAME" >&2
  IFS= read -r confirmation
  if [ "$confirmation" != "restore $DB_NAME" ]; then
    echo "Restore cancelled." >&2
    exit 1
  fi
fi

echo "Restoring '$DUMP_FILE' into service '$SERVICE'..."

compose exec -T \
  -e MYSQL_PWD="$DB_PASSWORD" \
  -e MARIADB_RESTORE_USER="$DB_USER" \
  "$SERVICE" \
  sh -c '
    set -e
    mysql_bin="$(command -v mariadb || command -v mysql)"
    exec "$mysql_bin" --user="$MARIADB_RESTORE_USER"
  ' \
  < "$DUMP_FILE"

echo "Restore complete."

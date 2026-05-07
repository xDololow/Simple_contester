#!/usr/bin/env bash
set -euo pipefail

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

load_dotenv_defaults ".env"

require_command docker

SERVICE="${MARIADB_SERVICE:-mariadb}"
DB_NAME="${MARIADB_DATABASE:-simple_contester}"
DB_USER="${BACKUP_DB_USER:-root}"
DB_PASSWORD="${BACKUP_DB_PASSWORD:-${MARIADB_ROOT_PASSWORD:-root}}"
BACKUP_DIR="${BACKUP_DIR:-backups}"
TIMESTAMP="$(date -u +%Y%m%dT%H%M%SZ)"
OUTPUT_FILE="$BACKUP_DIR/${DB_NAME}_${TIMESTAMP}.sql"
TMP_OUTPUT_FILE="$OUTPUT_FILE.tmp.$$"

cleanup_tmp() {
  rm -f "$TMP_OUTPUT_FILE"
}
trap cleanup_tmp EXIT

mkdir -p "$BACKUP_DIR"

if ! compose ps --services --status running | grep -qx "$SERVICE"; then
  echo "MariaDB compose service '$SERVICE' is not running." >&2
  echo "Start it first, for example: docker compose up -d mariadb" >&2
  exit 1
fi

if ! compose exec -T "$SERVICE" sh -c 'command -v mariadb-dump >/dev/null 2>&1 || command -v mysqldump >/dev/null 2>&1' >/dev/null; then
  echo "Neither mariadb-dump nor mysqldump was found in service '$SERVICE'." >&2
  exit 1
fi

echo "Creating MariaDB dump for database '$DB_NAME' from service '$SERVICE'..."
echo "Backup file: $OUTPUT_FILE"

compose exec -T \
  -e MYSQL_PWD="$DB_PASSWORD" \
  -e MARIADB_DUMP_USER="$DB_USER" \
  -e MARIADB_DUMP_DATABASE="$DB_NAME" \
  "$SERVICE" \
  sh -c '
    set -e
    dump_bin="$(command -v mariadb-dump || command -v mysqldump)"
    exec "$dump_bin" \
      --user="$MARIADB_DUMP_USER" \
      --single-transaction \
      --quick \
      --routines \
      --triggers \
      --events \
      --add-drop-table \
      --databases "$MARIADB_DUMP_DATABASE"
  ' \
  > "$TMP_OUTPUT_FILE"

if [ ! -s "$TMP_OUTPUT_FILE" ]; then
  echo "Backup failed: dump file is empty." >&2
  exit 1
fi

mv "$TMP_OUTPUT_FILE" "$OUTPUT_FILE"
trap - EXIT
echo "Backup complete: $OUTPUT_FILE"

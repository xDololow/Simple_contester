#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="${1:-.env}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Env file not found: $ENV_FILE" >&2
  echo "Usage: scripts/check-env.sh [path/to/.env]" >&2
  exit 2
fi

declare -A ENV_VALUES=()

load_env_file() {
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

    if [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      ENV_VALUES["$key"]="$value"
    fi
  done < "$ENV_FILE"
}

warn_if_equals() {
  local key="$1"
  local insecure_value="$2"
  local message="$3"
  if [ "${ENV_VALUES[$key]+set}" = "set" ] && [ "${ENV_VALUES[$key]}" = "$insecure_value" ]; then
    echo "WARN: $message"
    WARNINGS=$((WARNINGS + 1))
  fi
}

warn_if_empty() {
  local key="$1"
  local message="$2"
  if [ "${ENV_VALUES[$key]+set}" = "set" ] && [ -z "${ENV_VALUES[$key]}" ]; then
    echo "WARN: $message"
    WARNINGS=$((WARNINGS + 1))
  fi
}

WARNINGS=0
load_env_file

warn_if_equals JWT_SECRET change-me-in-production "JWT_SECRET uses the public demo value."
warn_if_equals JWT_SECRET dev-secret "JWT_SECRET uses the local development default."
warn_if_empty JWT_SECRET "JWT_SECRET is empty."
warn_if_equals ADMIN_USERNAME admin "ADMIN_USERNAME is still 'admin'."
warn_if_equals ADMIN_PASSWORD admin "ADMIN_PASSWORD is still 'admin'."
warn_if_empty ADMIN_PASSWORD "ADMIN_PASSWORD is empty."
warn_if_equals MARIADB_ROOT_PASSWORD root "MARIADB_ROOT_PASSWORD is still 'root'."
warn_if_empty MARIADB_ROOT_PASSWORD "MARIADB_ROOT_PASSWORD is empty."
warn_if_equals MARIADB_PASSWORD contestant "MARIADB_PASSWORD is still the demo value."
warn_if_empty MARIADB_PASSWORD "MARIADB_PASSWORD is empty."
warn_if_equals BACKUP_DB_PASSWORD root "BACKUP_DB_PASSWORD is still 'root'."
warn_if_equals RESTORE_DB_PASSWORD root "RESTORE_DB_PASSWORD is still 'root'."

if [ "$WARNINGS" -gt 0 ]; then
  echo "Found $WARNINGS insecure env value(s). Replace them before production."
  exit 1
fi

echo "No insecure demo defaults found in $ENV_FILE."

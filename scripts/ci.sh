#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_IMAGE="${BACKEND_CI_IMAGE:-simple-contester-backend-ci:local}"
FRONTEND_IMAGE="${FRONTEND_CI_IMAGE:-simple-contester-frontend-ci:local}"
JUDGER_IMAGE="${JUDGER_CI_IMAGE:-simple-contester-judger:local}"

usage() {
  cat >&2 <<'USAGE'
Usage: scripts/ci.sh [all|lint|compose|backend|frontend|judger]

Runs the practical local CI checks used by GitHub Actions.
USAGE
}

log() {
  printf '\n==> %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

docker_run_repo() {
  docker run --rm \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e PYTHONPATH=/workspace/backend:/workspace/judger \
    -v "$ROOT_DIR:/workspace" \
    -w /workspace \
    --entrypoint python \
    "$@"
}

check_lint() {
  log "Checking shell syntax"
  bash -n "$ROOT_DIR"/scripts/*.sh

  if git -C "$ROOT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log "Checking whitespace with git diff --check"
    git -C "$ROOT_DIR" diff --check
  fi
}

check_compose() {
  require_command docker
  check_lint

  log "Validating docker compose config"
  docker compose -f "$ROOT_DIR/docker-compose.yml" config --quiet
}

check_backend() {
  require_command docker
  check_lint

  log "Building backend CI image"
  docker build -f "$ROOT_DIR/backend/Dockerfile" -t "$BACKEND_IMAGE" "$ROOT_DIR"

  log "Compiling backend, judger imports, and tests"
  docker_run_repo "$BACKEND_IMAGE" -m compileall -q backend/app judger tests

  log "Running backend-focused pytest suite"
  docker_run_repo "$BACKEND_IMAGE" -m pytest \
    -o cache_dir=/tmp/simple-contester-pytest-cache \
    tests/test_admin_stats.py \
    tests/test_auth_import.py \
    tests/test_contest_submissions_scoreboard.py \
    tests/test_scoring_modes_comparison.py \
    tests/test_migrations.py \
    tests/test_package_import_export.py \
    tests/test_task_library_archive_import.py
}

check_frontend() {
  require_command docker
  check_lint

  log "Building frontend CI image"
  docker build -f "$ROOT_DIR/frontend/Dockerfile" -t "$FRONTEND_IMAGE" "$ROOT_DIR/frontend"

  log "Running frontend Bun build"
  docker run --rm --entrypoint bun "$FRONTEND_IMAGE" run build
}

check_judger() {
  require_command docker
  check_lint

  log "Building judger CI image"
  docker build -f "$ROOT_DIR/judger/Dockerfile" -t "$JUDGER_IMAGE" "$ROOT_DIR/judger"

  log "Compiling judger modules"
  docker run --rm --entrypoint python "$JUDGER_IMAGE" -m py_compile /judger/runners.py /judger/worker.py

  log "Running judger language smoke tests"
  docker run --rm \
    -e JUDGER_PATH=/judger \
    -v "$ROOT_DIR/scripts:/ci-scripts:ro" \
    --entrypoint python \
    "$JUDGER_IMAGE" \
    /ci-scripts/judger_smoke.py
}

main() {
  cd "$ROOT_DIR"

  local target="${1:-all}"
  case "$target" in
    all)
      check_compose
      check_backend
      check_frontend
      check_judger
      ;;
    lint)
      check_lint
      ;;
    compose)
      check_compose
      ;;
    backend)
      check_backend
      ;;
    frontend)
      check_frontend
      ;;
    judger)
      check_judger
      ;;
    -h | --help | help)
      usage
      ;;
    *)
      usage
      exit 2
      ;;
  esac
}

main "$@"

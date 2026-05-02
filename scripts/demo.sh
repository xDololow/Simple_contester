#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8001}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
DEMO_USERNAME="${DEMO_USERNAME:-demo_$(date +%s)}"
DEMO_PASSWORD="${DEMO_PASSWORD:-demo123}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  PYTHON_BIN=python
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

json_get() {
  "$PYTHON_BIN" -c "import json, sys; print(json.load(sys.stdin)$1)"
}

request() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local token="${4:-}"
  local output="$tmpdir/response.json"
  local headers=(-H "Content-Type: application/json")
  if [ -n "$token" ]; then
    headers+=(-H "Authorization: Bearer $token")
  fi
  if [ -n "$body" ]; then
    curl -fsS -X "$method" "${headers[@]}" --data @"$body" "$API_BASE$path" -o "$output"
  else
    curl -fsS -X "$method" "${headers[@]}" "$API_BASE$path" -o "$output"
  fi
  cat "$output"
}

admin_login="$tmpdir/admin-login.json"
cat > "$admin_login" <<JSON
{"username":"$ADMIN_USERNAME","password":"$ADMIN_PASSWORD"}
JSON
admin_token="$(request POST /api/auth/login "$admin_login" | json_get "['access_token']")"

user_body="$tmpdir/user.json"
cat > "$user_body" <<JSON
{"username":"$DEMO_USERNAME","password":"$DEMO_PASSWORD","display_name":"Demo Participant","role":"participant"}
JSON
user_id="$(request POST /api/users "$user_body" "$admin_token" | json_get "['id']")"

starts_at="$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)"
ends_at="$(date -u -d '1 day' +%Y-%m-%dT%H:%M:%SZ)"
contest_body="$tmpdir/contest.json"
cat > "$contest_body" <<JSON
{"title":"Demo Contest","description":"Created by scripts/demo.sh","status":"running","time_mode":"fixed","starts_at":"$starts_at","ends_at":"$ends_at"}
JSON
contest_id="$(request POST /api/contests "$contest_body" "$admin_token" | json_get "['id']")"

task_body="$tmpdir/task.json"
cat > "$task_body" <<JSON
{
  "contest_id": $contest_id,
  "title": "A + B",
  "statement": "Read two integers and print their sum.",
  "input_format": "Two integers.",
  "output_format": "Their sum.",
  "samples": [{"input": "2 3", "output": "5"}],
  "time_limit_ms": 2000,
  "memory_limit_mb": 256,
  "points": 100,
  "tests": [{"input_data": "2 3\n", "output_data": "5\n", "is_sample": true}]
}
JSON
task_id="$(request POST /api/tasks "$task_body" "$admin_token" | json_get "['id']")"

participant_login="$tmpdir/participant-login.json"
cat > "$participant_login" <<JSON
{"username":"$DEMO_USERNAME","password":"$DEMO_PASSWORD"}
JSON
participant_token="$(request POST /api/auth/login "$participant_login" | json_get "['access_token']")"

submission_body="$tmpdir/submission.json"
cat > "$submission_body" <<'JSON'
{
  "language": "python",
  "source_code": "import sys\nprint(sum(map(int, sys.stdin.read().split())))\n"
}
JSON
submission_id="$(request POST "/api/contests/$contest_id/tasks/$task_id/submissions" "$submission_body" "$participant_token" | json_get "['id']")"

echo
echo "Demo created:"
echo "  user: $DEMO_USERNAME (id $user_id)"
echo "  contest_id: $contest_id"
echo "  task_id: $task_id"
echo "  submission_id: $submission_id"
echo
echo "Check submission:"
echo "  curl -H 'Authorization: Bearer $participant_token' '$API_BASE/api/submissions/$submission_id'"

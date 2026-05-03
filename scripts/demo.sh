#!/usr/bin/env bash
set -euo pipefail

API_BASE="${API_BASE:-http://localhost:8001}"
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin}"
DEMO_PREFIX="${DEMO_PREFIX:-demo_$(date +%s)}"
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
  local status_file="$tmpdir/status.txt"
  local headers=(-H "Content-Type: application/json")
  if [ -n "$token" ]; then
    headers+=(-H "Authorization: Bearer $token")
  fi

  : > "$output"
  local curl_exit=0
  set +e
  if [ -n "$body" ]; then
    curl -sS -X "$method" "${headers[@]}" --data @"$body" "$API_BASE$path" -o "$output" -w "%{http_code}" > "$status_file"
  else
    curl -sS -X "$method" "${headers[@]}" "$API_BASE$path" -o "$output" -w "%{http_code}" > "$status_file"
  fi
  curl_exit=$?
  set -e

  if [ "$curl_exit" -ne 0 ]; then
    echo "Request failed: $method $path -> curl exit $curl_exit" >&2
    echo "Check that backend is running and API_BASE is correct: $API_BASE" >&2
    exit 1
  fi

  local status_code
  status_code="$(cat "$status_file")"
  if [ "$status_code" -lt 200 ] || [ "$status_code" -ge 300 ]; then
    echo "Request failed: $method $path -> HTTP $status_code" >&2
    cat "$output" >&2
    echo >&2
    exit 1
  fi
  cat "$output"
}

write_json() {
  local file="$1"
  cat > "$file"
}

login_body="$tmpdir/admin-login.json"
write_json "$login_body" <<JSON
{"username":"$ADMIN_USERNAME","password":"$ADMIN_PASSWORD"}
JSON
admin_token="$(request POST /api/auth/login "$login_body" | json_get "['access_token']")"

participant_username="${DEMO_PREFIX}_alice"
teammate_username="${DEMO_PREFIX}_bob"

participant_body="$tmpdir/participant.json"
write_json "$participant_body" <<JSON
{"username":"$participant_username","password":"$DEMO_PASSWORD","display_name":"Demo Alice","role":"participant"}
JSON
participant_id="$(request POST /api/users "$participant_body" "$admin_token" | json_get "['id']")"

teammate_body="$tmpdir/teammate.json"
write_json "$teammate_body" <<JSON
{"username":"$teammate_username","password":"$DEMO_PASSWORD","display_name":"Demo Bob","role":"participant"}
JSON
teammate_id="$(request POST /api/users "$teammate_body" "$admin_token" | json_get "['id']")"

team_body="$tmpdir/team.json"
write_json "$team_body" <<JSON
{"name":"$DEMO_PREFIX Team","user_ids":[$participant_id,$teammate_id]}
JSON
team_id="$(request POST /api/teams "$team_body" "$admin_token" | json_get "['id']")"

starts_at="$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)"
ends_at="$(date -u -d '1 day' +%Y-%m-%dT%H:%M:%SZ)"

contest_body="$tmpdir/contest.json"
write_json "$contest_body" <<JSON
{
  "title":"$DEMO_PREFIX Individual Contest",
  "description":"Private individual contest created by scripts/demo.sh",
  "status":"running",
  "is_public":false,
  "time_mode":"individual",
  "participation_mode":"individual",
  "starts_at":"$starts_at",
  "ends_at":"$ends_at",
  "individual_duration_minutes":180
}
JSON
contest_id="$(request POST /api/contests "$contest_body" "$admin_token" | json_get "['id']")"

participants_body="$tmpdir/participants.json"
write_json "$participants_body" <<JSON
{"user_ids":[$participant_id,$teammate_id]}
JSON
request PUT "/api/contests/$contest_id/participants" "$participants_body" "$admin_token" >/dev/null

task_sum_body="$tmpdir/task-sum.json"
write_json "$task_sum_body" <<JSON
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
  "tests": [
    {"input_data": "2 3\n", "output_data": "5\n", "is_sample": true},
    {"input_data": "10 -4\n", "output_data": "6\n", "is_sample": false}
  ]
}
JSON
task_sum_id="$(request POST /api/tasks "$task_sum_body" "$admin_token" | json_get "['id']")"

task_echo_body="$tmpdir/task-echo.json"
write_json "$task_echo_body" <<JSON
{
  "contest_id": $contest_id,
  "title": "Echo",
  "statement": "Print the input unchanged.",
  "input_format": "One line.",
  "output_format": "The same line.",
  "samples": [{"input": "hello", "output": "hello"}],
  "time_limit_ms": 2000,
  "memory_limit_mb": 256,
  "points": 50,
  "tests": [
    {"input_data": "hello\n", "output_data": "hello\n", "is_sample": true},
    {"input_data": "simple contester\n", "output_data": "simple contester\n", "is_sample": false}
  ]
}
JSON
task_echo_id="$(request POST /api/tasks "$task_echo_body" "$admin_token" | json_get "['id']")"

team_contest_body="$tmpdir/team-contest.json"
write_json "$team_contest_body" <<JSON
{
  "title":"$DEMO_PREFIX Team Contest",
  "description":"Private team contest created by scripts/demo.sh",
  "status":"running",
  "is_public":false,
  "time_mode":"fixed",
  "participation_mode":"team",
  "starts_at":"$starts_at",
  "ends_at":"$ends_at",
  "individual_duration_minutes":null
}
JSON
team_contest_id="$(request POST /api/contests "$team_contest_body" "$admin_token" | json_get "['id']")"

contest_teams_body="$tmpdir/contest-teams.json"
write_json "$contest_teams_body" <<JSON
{"team_ids":[$team_id]}
JSON
request PUT "/api/contests/$team_contest_id/teams" "$contest_teams_body" "$admin_token" >/dev/null

task_product_body="$tmpdir/task-product.json"
write_json "$task_product_body" <<JSON
{
  "contest_id": $team_contest_id,
  "title": "A * B",
  "statement": "Read two integers and print their product.",
  "input_format": "Two integers.",
  "output_format": "Their product.",
  "samples": [{"input": "2 3", "output": "6"}],
  "time_limit_ms": 2000,
  "memory_limit_mb": 256,
  "points": 100,
  "tests": [
    {"input_data": "2 3\n", "output_data": "6\n", "is_sample": true},
    {"input_data": "7 8\n", "output_data": "56\n", "is_sample": false}
  ]
}
JSON
task_product_id="$(request POST /api/tasks "$task_product_body" "$admin_token" | json_get "['id']")"

participant_login="$tmpdir/participant-login.json"
write_json "$participant_login" <<JSON
{"username":"$participant_username","password":"$DEMO_PASSWORD"}
JSON
participant_token="$(request POST /api/auth/login "$participant_login" | json_get "['access_token']")"

teammate_login="$tmpdir/teammate-login.json"
write_json "$teammate_login" <<JSON
{"username":"$teammate_username","password":"$DEMO_PASSWORD"}
JSON
teammate_token="$(request POST /api/auth/login "$teammate_login" | json_get "['access_token']")"

sum_submission_body="$tmpdir/submission-sum.json"
write_json "$sum_submission_body" <<'JSON'
{
  "language": "python",
  "source_code": "import sys\nprint(sum(map(int, sys.stdin.read().split())))\n"
}
JSON
sum_submission_id="$(request POST "/api/contests/$contest_id/tasks/$task_sum_id/submissions" "$sum_submission_body" "$participant_token" | json_get "['id']")"

echo_submission_body="$tmpdir/submission-echo.json"
write_json "$echo_submission_body" <<'JSON'
{
  "language": "javascript",
  "source_code": "const fs = require('fs'); process.stdout.write(fs.readFileSync(0, 'utf8'));\n"
}
JSON
echo_submission_id="$(request POST "/api/contests/$contest_id/tasks/$task_echo_id/submissions" "$echo_submission_body" "$teammate_token" | json_get "['id']")"

product_submission_body="$tmpdir/submission-product.json"
write_json "$product_submission_body" <<'JSON'
{
  "language": "python",
  "source_code": "import sys\na, b = map(int, sys.stdin.read().split())\nprint(a * b)\n"
}
JSON
product_submission_id="$(request POST "/api/contests/$team_contest_id/tasks/$task_product_id/submissions" "$product_submission_body" "$participant_token" | json_get "['id']")"

echo
echo "Demo created:"
echo "  API: $API_BASE"
echo "  users:"
echo "    $participant_username / $DEMO_PASSWORD (id $participant_id)"
echo "    $teammate_username / $DEMO_PASSWORD (id $teammate_id)"
echo "  team:"
echo "    $DEMO_PREFIX Team (id $team_id)"
echo "  individual contest:"
echo "    contest_id: $contest_id"
echo "    tasks: A + B=$task_sum_id, Echo=$task_echo_id"
echo "    submissions: python=$sum_submission_id, javascript=$echo_submission_id"
echo "  team contest:"
echo "    contest_id: $team_contest_id"
echo "    task: A * B=$task_product_id"
echo "    submission: $product_submission_id"
echo
echo "Useful checks:"
echo "  curl -H 'Authorization: Bearer $participant_token' '$API_BASE/api/contests/$contest_id/scoreboard'"
echo "  curl -H 'Authorization: Bearer $participant_token' '$API_BASE/api/contests/$team_contest_id/scoreboard'"

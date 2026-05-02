# Simple Contester

Closed/local olympiad contest platform MVP.

## Stack

- Backend: FastAPI + SQLAlchemy
- Frontend: React + Vite, intended for Bun with npm/node fallback
- Database: MariaDB
- Judger: Python worker, scalable via Docker Compose

## Quick Start

```bash
cp .env.example .env
docker compose up --build
```

Services with default ports:

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8001/docs
- MariaDB host port: `3307`, mapped to container port `3306`

Default admin credentials:

```text
username: admin
password: admin
```

## Useful Commands

```bash
# Validate compose after changing env vars.
docker compose config

# Start or rebuild everything.
docker compose up --build

# Run in background.
docker compose up --build -d

# Show service status and healthchecks.
docker compose ps

# Follow logs for API and workers.
docker compose logs -f backend judger

# Stop containers, keep database volume.
docker compose down

# Stop containers and remove MariaDB data.
docker compose down -v
```

## Database Migrations

Schema changes are managed with Alembic. The backend Docker entrypoint waits for
the database, stamps an existing pre-Alembic schema when needed, runs
`alembic upgrade head`, and then starts Uvicorn. This keeps
`docker compose up --build` working for both fresh databases and current local
MariaDB volumes.

Manual migration commands:

```bash
# From the repository root, with backend dependencies installed.
PYTHONPATH=backend alembic upgrade head

# Create a new migration after changing backend/app/models.py.
PYTHONPATH=backend alembic revision --autogenerate -m "Describe schema change"

# Inspect current migration state.
PYTHONPATH=backend alembic current
PYTHONPATH=backend alembic history
```

For Docker-only environments:

```bash
docker compose run --rm backend python -m app.migrate upgrade
```

The FastAPI startup no longer creates tables. It still keeps the admin bootstrap
and a small MariaDB compatibility pass for local volumes that were created
before migrations existed.

## Configuration

Compose reads `.env` automatically. Start from `.env.example`; the defaults keep `docker compose up --build` working without a local `.env`.

| Variable | Default | Description |
| --- | --- | --- |
| `MARIADB_DATABASE` | `simple_contester` | Database name created by MariaDB. |
| `MARIADB_USER` | `contestant` | Application DB user. |
| `MARIADB_PASSWORD` | `contestant` | Application DB password. |
| `MARIADB_ROOT_PASSWORD` | `root` | MariaDB root password. |
| `MARIADB_PORT` | `3307` | Host port for MariaDB. Kept off standard `3306` by default. |
| `BACKEND_PORT` | `8001` | Host port mapped to backend container port `8000`. |
| `FRONTEND_PORT` | `5173` | Host port mapped to Vite container port `5173`. |
| `VITE_API_BASE` | `http://localhost:8001` | API URL compiled into the Vite frontend. Update this when `BACKEND_PORT` changes. |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated backend CORS origins. Update this when `FRONTEND_PORT` changes. |
| `DATABASE_URL` | `mysql+pymysql://contestant:contestant@mariadb:3306/simple_contester` | SQLAlchemy URL used by backend and judger inside Docker. |
| `JWT_SECRET` | `change-me-in-production` | Token signing secret. Change outside local demo. |
| `ADMIN_USERNAME` | `admin` | Bootstrap admin username. |
| `ADMIN_PASSWORD` | `admin` | Bootstrap admin password. |
| `JUDGER_ID` | `docker-judger` | Worker ID written to claimed submissions. |
| `POLL_INTERVAL_SECONDS` | `1` | Judger polling interval. |
| `STOP_ON_FIRST_FAILED_TEST` | `1` | Set to `0` to run all tests after a failed test. |
| `OUTPUT_LIMIT_BYTES` | `1048576` | Maximum combined stdout/stderr captured from a compile or run before the process is killed and reported as a runtime error. |
| `PROCESS_LIMIT` | `256` | Per-run process limit applied with `RLIMIT_NPROC` where the host kernel enforces it. |
| `FILE_SIZE_LIMIT_BYTES` | `16777216` | Maximum file size a submitted program can create in subprocess mode. |
| `COMPILE_TIMEOUT_SECONDS` | `20` | Compiler wall-clock timeout. |
| `COMPILE_MEMORY_LIMIT_MB` | `4096` | Compiler address-space limit. |
| `COMPILE_PROCESS_LIMIT` | `256` | Compiler process limit. |
| `COMPILE_FILE_SIZE_LIMIT_BYTES` | `268435456` | Maximum compiler output/artifact file size. |

## Healthchecks

Compose healthchecks are configured for:

- `mariadb`: MariaDB image healthcheck script.
- `backend`: FastAPI docs endpoint inside the container.
- `frontend`: Vite root page through Bun `fetch`.
- `judger`: database connectivity through SQLAlchemy.

Use `docker compose ps` to inspect health state.

## Live Updates

Contest submissions and scoreboards use an authenticated Server-Sent Events MVP.
The frontend opens `GET /api/contests/{contest_id}/events?token=...` after the
initial contest load because browser `EventSource` cannot send an
`Authorization` header. The backend validates the JWT token, applies the same
contest access checks as the normal contest endpoints, and streams a compact
`contest` event whenever submission verdicts/scores change. If the stream is
unavailable or drops, the contest view falls back to slower polling through
`GET /api/contests/{contest_id}/live-snapshot`.

## Scale Judgers

Judger workers use row locking with `SKIP LOCKED`, so several workers can poll the same queue.

```bash
docker compose up --build --scale judger=3
```

Do not publish ports on `judger`; scaling works because it is an internal worker service.

## Judger Sandbox Boundaries

The default judger is still a simple Python worker, but each compile and test run now executes in an isolated temporary working directory with a restricted environment. For every test case, the compiled artifacts are copied into a fresh temp directory, so files created by one run do not persist into the next run.

Submissions are run with:

- wall-clock and CPU time limits;
- address-space limits where compatible with the runtime;
- process, open-file, core-dump, and file-size limits;
- bounded stdout/stderr capture with truncation handling;
- `HOME` and `TMPDIR` pointed at the per-run temp directory.

The Docker Compose judger service also runs as a non-root user with a read-only root filesystem, writable `/tmp` tmpfs, dropped Linux capabilities, `no-new-privileges`, and a container-level `pids_limit`.

Important caveats:

- Subprocess mode does not provide a reliable per-submission network namespace. The judger needs database network access, so untrusted code can still attempt outbound connections from inside the judger container. For production, run submissions in a separate per-submission container, VM, or microVM with network disabled.
- `RLIMIT_NPROC` is kernel/user dependent and is not reliably enforced for root; the Docker image runs as the non-root `judge` user to make it effective.
- Language runtimes such as JVM, Node.js, Go, and Mono manage memory internally, so memory verdicts are best-effort and may appear as runtime errors for some failure modes.
- This sandbox is suitable for a local MVP or trusted contests. It is not a complete hostile-code isolation boundary.

## Local Frontend Without Docker

Bun is preferred:

```bash
cd frontend
bun install
bun run dev --host 0.0.0.0
```

Node/npm fallback:

```bash
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

When running the frontend locally against Docker backend, keep `VITE_API_BASE=http://localhost:8001`.

## Demo End-to-End

Start the stack first:

```bash
docker compose up --build -d
```

Then run the demo script. It logs in as admin, creates a participant, creates a running contest, creates an `A + B` task, logs in as the participant, and submits a Python solution.

```bash
bash scripts/demo.sh
```

The script prints the created IDs and a `curl` command to inspect the submission. A judger should move the submission from `Queued` to `Accepted`.

Equivalent curl workflow:

```bash
API_BASE=http://localhost:8001

ADMIN_TOKEN="$(
  curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin"}' \
    "$API_BASE/api/auth/login" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['access_token'])"
)"

curl -fsS -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d '{"username":"alice","password":"alice123","display_name":"Alice","role":"participant"}' \
  "$API_BASE/api/users"

CONTEST_ID="$(
  curl -fsS -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN_TOKEN" \
    -d '{"title":"Demo Contest","description":"curl demo","status":"running","time_mode":"fixed","starts_at":"2026-01-01T00:00:00Z","ends_at":"2030-01-01T00:00:00Z"}' \
    "$API_BASE/api/contests" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])"
)"

TASK_ID="$(
  curl -fsS -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer $ADMIN_TOKEN" \
    -d '{"contest_id":'"$CONTEST_ID"',"title":"A + B","statement":"Read two integers and print their sum.","input_format":"Two integers.","output_format":"Their sum.","samples":[{"input":"2 3","output":"5"}],"tests":[{"input_data":"2 3\n","output_data":"5\n","is_sample":true}]}' \
    "$API_BASE/api/tasks" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['id'])"
)"

USER_TOKEN="$(
  curl -fsS -X POST -H 'Content-Type: application/json' \
    -d '{"username":"alice","password":"alice123"}' \
    "$API_BASE/api/auth/login" \
  | python3 -c "import json, sys; print(json.load(sys.stdin)['access_token'])"
)"

curl -fsS -X POST -H 'Content-Type: application/json' -H "Authorization: Bearer $USER_TOKEN" \
  -d '{"language":"python","source_code":"import sys\nprint(sum(map(int, sys.stdin.read().split())))\n"}' \
  "$API_BASE/api/contests/$CONTEST_ID/tasks/$TASK_ID/submissions"
```

## User Import Formats

CSV columns:

```csv
username,password,display_name,role
alice,secret,Alice,participant
```

JSON:

```json
[
  {"username": "alice", "password": "secret", "display_name": "Alice", "role": "participant"}
]
```

YAML:

```yaml
- username: alice
  password: secret
  display_name: Alice
  role: participant
```

## Backend MVP Notes

- Contests can be linked to teams through admin API endpoints at `/api/contests/{contest_id}/teams`.
- Tasks are stored in a standalone task library. `POST /api/tasks` creates a task without requiring a contest; optional `contest_id` is still accepted for older clients and immediately links the task to that contest. Admins can replace contest task assignments with `PUT /api/contests/{contest_id}/tasks` and a JSON body like `{"task_ids":[1,2,3]}`.
- Task statements are stored as Markdown text in `statement`; rendering is handled by the frontend.
- Admins can bulk import task tests with `POST /api/tasks/{task_id}/tests/import-archive` using a `.zip` file containing matching `*.in` and `*.out` files with the same basename, for example `001.in` and `001.out`. Unsafe archive paths are ignored and unmatched files are reported.
- Partial scoring is optional per task through `partial_scoring`. When enabled, a solution earns `accepted_tests / total_tests * task.points`, rounded to two decimal places. When disabled, scoring remains all-or-nothing. Scoreboard totals use the best score per task.
- Team-based scoring and team-only contest access are not enforced yet; current submissions and scoreboard remain participant-based.

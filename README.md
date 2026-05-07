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

## Production Deployment MVP

This repository is still an MVP, but the Docker setup can be run behind a
normal reverse proxy for a small closed installation. Keep the default
`docker-compose.yml` for local development. For a production-style host, use the
override file:

```bash
cp .env.example .env
$EDITOR .env
bash scripts/check-env.sh .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

First-run checklist:

- Replace `JWT_SECRET`, `ADMIN_PASSWORD`, `MARIADB_PASSWORD`,
  `MARIADB_ROOT_PASSWORD`, `BACKUP_DB_PASSWORD`, and `RESTORE_DB_PASSWORD`.
- Set `VITE_API_BASE` to the public HTTPS API origin and `CORS_ORIGINS` to the
  exact browser origins that should call the API.
- Run `bash scripts/check-env.sh .env` and treat warnings as deployment blockers.
- Start the stack, confirm `docker compose ps` shows healthy `mariadb`,
  `backend`, and `judger`, then log in and change or rotate the bootstrap admin
  account.
- Create a backup with `bash scripts/backup.sh` and verify restore on a non-prod
  Compose project before relying on the deployment.

Secrets policy:

- Do not commit `.env`, SQL dumps, TLS private keys, or generated JWT secrets.
- Use unique database and admin passwords per environment.
- Rotate `JWT_SECRET` to invalidate all existing browser tokens after a leak or
  an admin handoff.
- Store backups off-host and protect them like production credentials because
  they contain users, password hashes, contest data, and submissions.

Reverse proxy and TLS:

- Terminate TLS in nginx, Caddy, Traefik, or a similar host-level proxy.
- Proxy the public API origin to `127.0.0.1:${BACKEND_PORT}` when using
  `docker-compose.prod.yml`; the override binds backend only to loopback.
- The frontend image currently runs the Vite development server. For production,
  serve a built frontend with your reverse proxy or another static server and
  keep the compose `frontend` service disabled. The prod override assigns it to
  the `dev` profile so it is skipped unless explicitly requested.
- Keep MariaDB off the public network. The prod override removes the host
  MariaDB port mapping.

Docker profiles and compose files:

- Development: `docker compose up --build` starts MariaDB, backend, Vite
  frontend, and one subprocess-mode judger.
- Production-style host: `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build`
  applies restart policies, disables the frontend dev server by default, binds
  backend to loopback, and avoids publishing MariaDB.
- Harder judging sandbox: add `--profile docker-sandbox` and run
  `judger-docker-sandbox` instead of the default worker. See
  [Hard Docker Sandbox Mode](#hard-docker-sandbox-mode) before enabling it.

Backups and restore:

- See [Backups And Restore](#backups-and-restore) for `scripts/backup.sh`,
  `scripts/restore.sh`, required confirmations, and off-host backup notes.
- Do not copy the MariaDB Docker volume while MariaDB is running.
- Stop `backend`, `judger`, and `judger-docker-sandbox` before restoring an
  active system.

Scaling judgers:

- Scale internal workers with `docker compose up -d --scale judger=3` for the
  default subprocess sandbox. See [Scale Judgers](#scale-judgers).
- Do not publish ports on judger services. They only need database and backend
  health dependencies.
- For Docker sandbox mode, scale only on hosts where Docker socket access and
  `/tmp/simple-contester-judger-work` are intentionally configured.

MariaDB volume caveats:

- The named volume `mariadb_data` is part of the Compose project name. Changing
  `COMPOSE_PROJECT_NAME` creates a different volume.
- `docker compose down -v` removes database data. Use it only for throwaway
  environments.
- Upgrading MariaDB major versions should be tested with a SQL dump/restore
  path, not by blindly reusing the same volume.

Healthchecks:

- Compose defines healthchecks for MariaDB, backend, frontend, and judger. Use
  `docker compose ps` and `docker compose logs -f backend judger` during rollout.
- The backend healthcheck currently hits `/docs`; if API docs are disabled in a
  future hardening pass, update the healthcheck to a dedicated health endpoint.

## Useful Commands

```bash
# Validate compose after changing env vars.
docker compose config
docker compose -f docker-compose.yml -f docker-compose.prod.yml config

# Warn about demo secrets before deployment.
bash scripts/check-env.sh .env

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

## Local CI

Run the same practical checks used by GitHub Actions from the repository root:

```bash
bash scripts/ci.sh
```

Individual checks can be run when iterating on one area:

```bash
bash scripts/ci.sh compose
bash scripts/ci.sh backend
bash scripts/ci.sh frontend
bash scripts/ci.sh judger
```

The CI wrapper checks shell syntax, runs `git diff --check` when the directory is
inside a Git worktree, validates `docker compose config`, compiles Python modules,
runs focused in-process backend pytest files, builds the frontend with Bun inside
Docker, and builds the judger image for Python/C++/JavaScript smoke tests. It
does not publish images and does not require secrets.

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

## Backups And Restore

Use SQL dumps for MariaDB backups. Do not copy Docker volumes directly while
MariaDB is running.

Create a timestamped backup from the Compose `mariadb` service:

```bash
bash scripts/backup.sh
```

By default the dump is written to `backups/simple_contester_YYYYMMDDTHHMMSSZ.sql`.
The script reads `.env` defaults when present and supports these overrides:

```bash
BACKUP_DIR=/safe/path/backups bash scripts/backup.sh
BACKUP_DB_USER=root BACKUP_DB_PASSWORD=root bash scripts/backup.sh
COMPOSE_PROJECT_NAME=staging bash scripts/backup.sh
```

Restore requires an explicit dump file and an interactive confirmation:

```bash
bash scripts/restore.sh backups/simple_contester_20260507T120000Z.sql
```

For non-interactive restore, set `RESTORE_YES=1`:

```bash
RESTORE_YES=1 bash scripts/restore.sh backups/simple_contester_20260507T120000Z.sql
```

Restore is destructive for the target database because the SQL dump can drop and
replace existing tables and rows. On active systems, stop API and judger
services first so workers do not write submissions while the database is being
replaced:

```bash
docker compose stop backend judger judger-docker-sandbox
bash scripts/restore.sh backups/simple_contester_20260507T120000Z.sql
docker compose up -d backend judger
```

If you run multiple Compose projects on one host, pass the target project name
with `COMPOSE_PROJECT_NAME`. The scripts also support `MARIADB_SERVICE` when the
database service name is changed from the default `mariadb`.

Keep backup files off the application host for real deployments. A cron entry is
enough for a local MVP, for example:

```cron
15 2 * * * cd /srv/simple_contester && BACKUP_DIR=/srv/backups/simple_contester bash scripts/backup.sh
```

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
| `ACCESS_TOKEN_MINUTES` | `1440` | JWT access token lifetime in minutes. Existing login response shape is unchanged. |
| `ADMIN_USERNAME` | `admin` | Bootstrap admin username. |
| `ADMIN_PASSWORD` | `admin` | Bootstrap admin password. |
| `LOGIN_RATE_LIMIT_ENABLED` | `true` | Enables in-memory login throttling by username and client IP. |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | `8` | Failed login attempts allowed within the rate-limit window before lockout. |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | `60` | Sliding window for failed login attempts. |
| `LOGIN_RATE_LIMIT_LOCKOUT_SECONDS` | `300` | Temporary lockout duration after too many failed login attempts. |
| `JUDGER_ID` | `docker-judger` | Worker ID written to claimed submissions. |
| `JUDGER_VERSION` | `local` | Version string reported in judger events/status. |
| `JUDGER_SANDBOX_MODE` | `subprocess` | Judger execution backend: `subprocess` keeps the compatible in-container runner, `docker` runs compile/run commands in per-invocation Docker containers. |
| `JUDGER_WORK_ROOT` | `/tmp/simple-contester-judger-work` in `.env.example` | Parent directory for judger workspaces. Required for Docker sandbox so the host Docker daemon can bind-mount the same path. |
| `JUDGER_DOCKER_IMAGE` | `simple-contester-judger:local` | Image used for per-invocation Docker sandbox containers. It must contain the language toolchains from `judger/Dockerfile`. |
| `JUDGER_DOCKER_USER` | `judge` | Non-root user passed to `docker run --user` for sandbox containers. |
| `JUDGER_DOCKER_CPUS` | `1` | CPU quota passed to Docker sandbox containers. |
| `JUDGER_DOCKER_TMPFS_SIZE` | `512m` | Size of the writable tmpfs mounted at `/tmp` in Docker sandbox containers. |
| `DOCKER_SOCK_GID` | `0` | Supplementary group added to `judger-docker-sandbox` so the non-root worker can access `/var/run/docker.sock`. Set it to `stat -c '%g' /var/run/docker.sock` when needed. |
| `POLL_INTERVAL_SECONDS` | `1` | Judger polling interval. |
| `JUDGER_HEARTBEAT_INTERVAL_SECONDS` | `5` | Interval for worker heartbeat/status updates. |
| `SUBMISSION_LEASE_SECONDS` | `60` | Lease duration for a claimed submission before another worker may reclaim it. |
| `SUBMISSION_MAX_ATTEMPTS` | `3` | Maximum claim attempts before an expired running submission is marked Internal Error. |
| `STOP_ON_FIRST_FAILED_TEST` | `1` | Set to `0` to run all tests after a failed test. |
| `OUTPUT_LIMIT_BYTES` | `1048576` | Maximum combined stdout/stderr captured from a compile or run before the process is killed and reported as a runtime error. |
| `PROCESS_LIMIT` | `256` | Per-run process limit applied with `RLIMIT_NPROC` where the host kernel enforces it. |
| `FILE_SIZE_LIMIT_BYTES` | `16777216` | Maximum file size a submitted program can create in subprocess mode. |
| `COMPILE_TIMEOUT_SECONDS` | `20` | Compiler wall-clock timeout. |
| `COMPILE_MEMORY_LIMIT_MB` | `4096` | Compiler address-space limit. |
| `COMPILE_PROCESS_LIMIT` | `256` | Compiler process limit. |
| `COMPILE_FILE_SIZE_LIMIT_BYTES` | `268435456` | Maximum compiler output/artifact file size. |
| `BACKUP_DIR` | `backups` | Directory where `scripts/backup.sh` writes SQL dumps. |
| `MARIADB_SERVICE` | `mariadb` | Compose service name used by backup/restore scripts. |
| `BACKUP_DB_USER` | `root` | Database user used by `scripts/backup.sh`. |
| `BACKUP_DB_PASSWORD` | `root` | Database password used by `scripts/backup.sh`. |
| `RESTORE_DB_USER` | `root` | Database user used by `scripts/restore.sh`. |
| `RESTORE_DB_PASSWORD` | `root` | Database password used by `scripts/restore.sh`. |
| `RESTORE_YES` | unset | Set to `1` to skip interactive restore confirmation. |

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

## Auth Security Notes

Simple Contester is built for closed local installations without email. Users can
change their own password from the account menu, and admins can still reset a
user password through `PATCH /api/users/{id}` with a `password` field. Password
recovery by email is intentionally not implemented.

JWT access tokens are stateless and expire according to `ACCESS_TOKEN_MINUTES`.
There is no server-side session revocation list in this MVP, so logout only
removes the token from the browser. Rotate `JWT_SECRET` to invalidate all
existing tokens for an installation.

Login throttling is intentionally in-memory. It is useful for one local backend
process, but it is not shared across multiple backend replicas or hosts; use a
distributed store or reverse-proxy rate limiting for a distributed deployment.

## Scoring

Each task has a maximum `points` value. By default, scoring is all-or-nothing:
an accepted submission receives the full task points, and any non-accepted
submission receives `0`.

Admins can enable `partial_scoring` on a task. When no per-test points are set,
partial scoring splits the task points evenly across non-sample tests only.
Sample tests are still judged and can prevent an all-or-nothing Accepted result,
but they do not award partial points unless the admin explicitly assigns points
to that sample test.

Admins can also set nullable `points` on individual tests. If at least one test
has explicit points, the submission score is the sum of points for passed tests
and is capped by the task's maximum points. Tests without explicit points
contribute `0` in this mode. `group_name` is stored with tests for future group
policies, but the MVP does not apply group min/max rules.

## Task Versions

Standalone tasks keep immutable task version snapshots for reproducible judging.
The backend creates version `1` when a task is created, then creates a new
version when task text, limits, scoring metadata, or tests change. New
submissions store `task_version_id` and the judger uses that snapshot for tests,
limits, and scoring even if admins later edit the live task.

Existing submissions with no `task_version_id` are treated as legacy rows and
are judged against the current live task. The admin API exposes task history at
`GET /api/tasks/{task_id}/versions` and version details at
`GET /api/tasks/{task_id}/versions/{version_id}`. The admin UI currently shows
the current version number only; restoring an old version is intentionally not
implemented in this MVP. Task and contest packages still export/import the
current task state, not the full version history.

## Clarifications

Contest participants can ask jury questions from the contest `Questions` tab.
Questions may be general or linked to a contest task. Participants see their own
private questions plus any broadcast clarifications in the same contest; they do
not see other participants' private questions. Admins can review open questions,
answer them, close them, and mark an answer as broadcast for all contest
participants.

## Task And Contest Packages

Admins can move standalone tasks and basic contest definitions between local
installations with ZIP packages from the admin `Packages` tab or the API:

- `GET /api/tasks/{task_id}/package` exports one task.
- `POST /api/tasks/import-package` imports one task package.
- `GET /api/contests/{contest_id}/package` exports one contest with its attached tasks.
- `POST /api/contests/import-package` imports a contest package.

Task package layout:

```text
metadata.json
statement.md
tests/001.in
tests/001.out
tests/002.in
tests/002.out
```

`metadata.json` uses the v2 package format:

```json
{
  "format": "simple-contester-package",
  "format_version": 2,
  "type": "task",
  "task": {
    "title": "A + B",
    "statement_file": "statement.md",
    "input_format": "",
    "output_format": "",
    "samples": [],
    "time_limit_ms": 2000,
    "memory_limit_mb": 256,
    "points": 100,
    "partial_scoring": false,
    "scoring_policy": "all_or_nothing",
    "language_templates": {},
    "checker": { "enabled": false, "type": null, "source": null, "language": null, "entrypoint": null },
    "validator": { "enabled": false, "type": null, "source": null, "language": null, "entrypoint": null },
    "interactor": { "enabled": false, "type": null, "source": null, "language": null, "entrypoint": null }
  },
  "tests": [
    { "name": "001", "is_sample": true, "points": null, "group_name": null }
  ]
}
```

Tests are stored as numbered `tests/NNN.in` and `tests/NNN.out` files. Test
metadata preserves `is_sample`, nullable `points`, and nullable `group_name`.
`statement.txt` is also accepted on import when `statement.md` is absent.
Checker, validator, and interactor objects are future metadata only in this
MVP; they are imported as inert data and are not executed.

Contest packages use a root `metadata.json` with `type: "contest"` and task
directories:

```text
metadata.json
tasks/001/metadata.json
tasks/001/statement.md
tasks/001/tests/001.in
tasks/001/tests/001.out
```

The contest metadata preserves title, description, original status/public flag
for reference, registration flags, time mode, participation mode, contest
window, individual duration, scoreboard freeze timestamp, unfreeze flag, and
attached task order. Contest imports intentionally create a draft, private
contest by default while preserving schedule, mode, registration, freeze, and
task order settings. Users, teams, access lists, registrations, participant
starts/deadlines, submissions, and results are not exported. Task imports
always create new standalone tasks; if a task or contest with the same title
already exists, it is not overwritten.

The importer accepts v1 task and contest packages for backward compatibility.
It rejects unsupported future `format_version` values, missing required v2
metadata fields, invalid ZIP files, duplicate archive member names, unsafe
absolute/traversal/backslash paths, and non-UTF-8 text files. The package
format still exports only the current task state, not full task version history
or executable checker/validator/interactor behavior.

Package archives are limited to 500 files, 20 MiB total uncompressed content,
and 5 MiB per file. Package import rejects absolute paths, `..` traversal,
backslash paths, invalid ZIP files, and non-UTF-8 text files.

## Team Contest MVP

Contests default to individual participation. Admins can switch a contest to
team participation and assign teams through the contest teams allowlist. In a
team contest, participant submissions are attached to the participant's assigned
team and the scoreboard groups rows by team.

MVP membership rule: a participant must belong to exactly one team assigned to
the contest before submitting. Participants with no assigned team, or with more
than one assigned team for the same contest, receive a 403 response explaining
that exactly one assigned team membership is required.

## Contest Registration

Private contests can optionally enable participant registration without email.
Admins keep the existing public/private switch and allowlists, then can turn on
`registration_enabled` and choose whether `registration_requires_approval` is
needed. Participants can see registration-enabled contests and request access.

For individual contests, an approved or auto-approved request adds the user to
the existing participant allowlist. For team contests, the request is made by
the participant's single current team; users with zero or multiple teams receive
a 403 response. Approved team requests add that team to the contest team
allowlist. Rejected requests remain visible as rejected and do not grant access.

## Scoreboard Freeze MVP

Admins can set an optional `scoreboard_freeze_at` timestamp on a contest. Once
that time is reached, participant scoreboards keep accepting submissions but do
not include submissions created at or after the freeze time. Admin scoreboards
always show the full current result.

Setting `scoreboard_unfrozen` to true manually reveals the full scoreboard to
participants again. The same visibility rule is used by the normal scoreboard
endpoint, live snapshot endpoint, and SSE contest updates. This MVP only hides
score visibility; it does not implement ICPC-style frozen penalty reveal
details.

## Scale Judgers

Judger workers use row locking with `SKIP LOCKED`, so several workers can poll the same queue. A worker claim also writes a unique `claim_token`, `claimed_at`, `claim_expires_at`, `attempt_number`, and `judger_id` to the submission row.

```bash
docker compose up --build --scale judger=3
```

Do not publish ports on `judger`; scaling works because it is an internal worker service.

Before each polling cycle, workers reclaim expired running submissions where `claim_expires_at` is in the past. Attempts below `SUBMISSION_MAX_ATTEMPTS` are returned to `Queued` and may be claimed again; once the max attempt count is reached, the submission is marked `Internal Error`. Active workers extend their lease around compile/run phases and before each test. Final reports and test-result writes are guarded by the current `claim_token`, so a stale worker cannot overwrite a submission that has already been reclaimed by another worker.

Workers also write a compact audit trail to `judger_events` for startup,
submission claim, compile/run start, finish, internal error, and shutdown.
Admins can inspect recent events on the Status page or through
`GET /api/admin/judger-events?limit=50` and
`GET /api/admin/judgers/{judger_id}/events?limit=50`.

## Judger Sandbox Boundaries

The default judger mode is `JUDGER_SANDBOX_MODE=subprocess` for compatibility.
In this mode each compile and test run executes in an isolated temporary
working directory with a restricted environment. For every test case, the
compiled artifacts are copied into a fresh temp directory, so files created by
one run do not persist into the next run.

Subprocess-mode submissions are run with:

- wall-clock and CPU time limits;
- address-space limits where compatible with the runtime;
- process, open-file, core-dump, and file-size limits;
- bounded stdout/stderr capture with truncation handling;
- `HOME` and `TMPDIR` pointed at the per-run temp directory.

The Docker Compose `judger` service also runs as a non-root user with a
read-only root filesystem, writable `/tmp` tmpfs, dropped Linux capabilities,
`no-new-privileges`, and a container-level `pids_limit`.

### Hard Docker Sandbox Mode

For stronger per-invocation isolation, enable the explicit Compose profile:

```bash
# Build the judger image used both by the worker and sandbox containers.
docker compose build judger-docker-sandbox

# If your Docker socket group is not root, pass its numeric gid.
DOCKER_SOCK_GID="$(stat -c '%g' /var/run/docker.sock)" \
  docker compose --profile docker-sandbox up --scale judger=0 judger-docker-sandbox
```

`judger-docker-sandbox` mounts `/var/run/docker.sock` and
`/tmp/simple-contester-judger-work`. The matching absolute work path is
important: the judger process creates temporary submission directories there,
and the host Docker daemon bind-mounts those same directories into each sandbox
container at `/workspace`.

In `JUDGER_SANDBOX_MODE=docker`, each compile command and each test run is
executed with `docker run --rm` using:

- `--network none`;
- read-only root filesystem;
- writable `/tmp` tmpfs;
- bind-mounted per-run `/workspace`;
- non-root `--user judge` by default;
- memory, pids, CPU, file-size, open-file, and core limits where Docker/kernel support them;
- dropped capabilities and `no-new-privileges`.

The normal `judger` service does not mount the Docker socket. Hard sandbox mode
must be enabled explicitly through the `docker-sandbox` profile.

Important caveats:

- Subprocess mode does not provide a reliable per-submission network namespace. The judger needs database network access, so untrusted code can still attempt outbound connections from inside the judger container.
- Mounting `/var/run/docker.sock` gives the judger service powerful control over the host Docker daemon. Treat `judger-docker-sandbox` as privileged infrastructure, run it only on dedicated judging hosts, and do not expose it to tenant-controlled code or APIs.
- Docker sandbox mode is a practical hardening layer, not a complete hostile-code boundary. Strong multi-tenant production deployments should still consider dedicated hosts, VMs, or microVMs, strict image provenance, cgroup/runtime monitoring, and regular kernel/runtime patching.
- `RLIMIT_NPROC` is kernel/user dependent and is not reliably enforced for root; the Docker image runs as the non-root `judge` user to make it effective.
- Language runtimes such as JVM, Node.js, Go, and Mono manage memory internally, so memory verdicts are best-effort and may appear as runtime errors for some failure modes.
- Docker memory kills may be reported as memory or runtime errors depending on how the runtime exits.

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

Then run the demo script. It logs in as admin, creates two participants, creates a team, creates a private individual contest with assigned participants, creates a private team contest with an assigned team, adds sample tasks, and submits Python/JavaScript solutions.

```bash
bash scripts/demo.sh
```

The script prints the created IDs and `curl` commands for both scoreboards. A judger should move the submissions from `Queued` to final verdicts.

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
- Partial scoring is optional per task through `partial_scoring`. Without per-test points it splits `task.points` across non-sample tests only; with explicit test points it sums the points for passed tests and caps the result at `task.points`. Scoreboard totals use the best score per task.
- Team-based scoring and team-only contest access are not enforced yet; current submissions and scoreboard remain participant-based.

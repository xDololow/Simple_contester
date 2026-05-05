import atexit
import json
import os
import signal
import socket
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

from runners import (
    Limits,
    RUNNERS,
    VERDICT_ACCEPTED,
    VERDICT_COMPILATION_ERROR,
    VERDICT_INTERNAL_ERROR,
    VERDICT_MEMORY_LIMIT,
    VERDICT_RUNTIME_ERROR,
    VERDICT_TIME_LIMIT,
    VERDICT_WRONG_ANSWER,
    copy_run_workspace,
    create_runner,
    env_for_workdir,
    run_program,
)


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./simple_contester.db")
JUDGER_ID = os.getenv("JUDGER_ID", "local-judger")
JUDGER_VERSION = os.getenv("JUDGER_VERSION", os.getenv("APP_VERSION", "unknown"))
JUDGER_SANDBOX_MODE = os.getenv("JUDGER_SANDBOX_MODE", "subprocess")
JUDGER_WORK_ROOT = os.getenv("JUDGER_WORK_ROOT")
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
HEARTBEAT_INTERVAL_SECONDS = float(os.getenv("JUDGER_HEARTBEAT_INTERVAL_SECONDS", "5"))
SUBMISSION_LEASE_SECONDS = int(os.getenv("SUBMISSION_LEASE_SECONDS", "60"))
SUBMISSION_MAX_ATTEMPTS = int(os.getenv("SUBMISSION_MAX_ATTEMPTS", "3"))
STOP_ON_FIRST_FAILED_TEST = os.getenv("STOP_ON_FIRST_FAILED_TEST", "0") != "0"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
state_lock = threading.Lock()
state_status = "starting"
state_current_submission_id: int | None = None
state_last_error: str | None = None
stop_event = threading.Event()


def utc_now() -> datetime:
    return datetime.utcnow()


def supported_languages() -> list[str]:
    return sorted(RUNNERS)


def judger_capabilities() -> dict[str, object]:
    return {
        "sandbox_mode": JUDGER_SANDBOX_MODE,
        "stop_on_first_failed_test": STOP_ON_FIRST_FAILED_TEST,
        "output_limit_bytes": int(os.getenv("OUTPUT_LIMIT_BYTES", str(1024 * 1024))),
        "process_limit": int(os.getenv("PROCESS_LIMIT", "256")),
        "file_size_limit_bytes": int(os.getenv("FILE_SIZE_LIMIT_BYTES", str(16 * 1024 * 1024))),
        "docker_image": os.getenv("JUDGER_DOCKER_IMAGE", "simple-contester-judger:local")
        if JUDGER_SANDBOX_MODE == "docker"
        else None,
    }


def submission_work_root() -> str | None:
    if not JUDGER_WORK_ROOT:
        return None
    root = Path(JUDGER_WORK_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    return str(root)


def register_or_update_judger(
    status: str,
    current_submission_id: int | None = None,
    last_error: str | None = None,
) -> None:
    now = utc_now()
    metadata = {
        "judger_id": JUDGER_ID,
        "hostname": socket.gethostname(),
        "version": JUDGER_VERSION,
        "supported_languages": json.dumps(supported_languages()),
        "sandbox_mode": JUDGER_SANDBOX_MODE,
        "capabilities": json.dumps(judger_capabilities(), sort_keys=True),
        "status": status,
        "current_submission_id": current_submission_id,
        "last_error": last_error,
        "now": now,
    }
    with engine.begin() as conn:
        existing = conn.execute(
            text("SELECT status FROM judgers WHERE judger_id = :judger_id"),
            {"judger_id": JUDGER_ID},
        ).mappings().first()
        if existing is None:
            conn.execute(
                text(
                    """
                    INSERT INTO judgers (
                        judger_id, hostname, version, supported_languages, sandbox_mode, capabilities,
                        status, current_submission_id, registered_at, last_seen_at,
                        last_state_change_at, enabled, last_error
                    )
                    VALUES (
                        :judger_id, :hostname, :version, :supported_languages, :sandbox_mode, :capabilities,
                        :status, :current_submission_id, :now, :now, :now, 1, :last_error
                    )
                    """
                ),
                metadata,
            )
            return
        last_state_change_at = now if existing["status"] != status else None
        conn.execute(
            text(
                """
                UPDATE judgers
                SET hostname = :hostname,
                    version = :version,
                    supported_languages = :supported_languages,
                    sandbox_mode = :sandbox_mode,
                    capabilities = :capabilities,
                    status = :status,
                    current_submission_id = :current_submission_id,
                    last_seen_at = :now,
                    last_state_change_at = COALESCE(:last_state_change_at, last_state_change_at),
                    enabled = 1,
                    last_error = :last_error
                WHERE judger_id = :judger_id
                """
            ),
            {**metadata, "last_state_change_at": last_state_change_at},
        )


def write_judger_event(
    event_type: str,
    submission_id: int | None = None,
    message: str | None = None,
    payload: dict[str, object] | None = None,
) -> bool:
    try:
        payload_text = json.dumps(payload, sort_keys=True, default=str) if payload is not None else None
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO judger_events (judger_id, event_type, submission_id, message, payload, created_at)
                    VALUES (:judger_id, :event_type, :submission_id, :message, :payload, :created_at)
                    """
                ),
                {
                    "judger_id": JUDGER_ID,
                    "event_type": event_type,
                    "submission_id": submission_id,
                    "message": message,
                    "payload": payload_text,
                    "created_at": utc_now(),
                },
            )
        return True
    except Exception:
        return False


def set_judger_state(
    status: str,
    current_submission_id: int | None = None,
    last_error: str | None = None,
    write_now: bool = True,
) -> None:
    global state_status, state_current_submission_id, state_last_error
    with state_lock:
        state_status = status
        state_current_submission_id = current_submission_id
        state_last_error = last_error
    if write_now:
        register_or_update_judger(status, current_submission_id, last_error)


def heartbeat_loop() -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        with state_lock:
            status = state_status
            current_submission_id = state_current_submission_id
            last_error = state_last_error
        register_or_update_judger(status, current_submission_id, last_error)


def request_stop(signum: int, frame: object) -> None:
    stop_event.set()


def mark_stopping() -> None:
    try:
        set_judger_state("stopping", None, state_last_error, write_now=True)
        write_judger_event("stopping", message=state_last_error)
    except Exception:
        pass


def normalize_output(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()


def acquire_submission() -> dict | None:
    claim_token = uuid.uuid4().hex
    claimed_at = utc_now()
    claim_expires_at = claimed_at + timedelta(seconds=SUBMISSION_LEASE_SECONDS)
    with engine.begin() as conn:
        # The row lock plus SKIP LOCKED lets several judgers poll concurrently
        # without blocking each other or claiming the same queued submission.
        lock_clause = "" if conn.dialect.name == "sqlite" else "FOR UPDATE SKIP LOCKED"
        row = conn.execute(
            text(
                f"""
                SELECT submissions.id, submissions.language, submissions.source_code, submissions.task_id,
                       submissions.attempt_number,
                       tasks.time_limit_ms, tasks.memory_limit_mb, tasks.points, tasks.partial_scoring
                FROM submissions
                JOIN tasks ON tasks.id = submissions.task_id
                WHERE submissions.verdict = 'queued'
                ORDER BY submissions.created_at
                LIMIT 1
                {lock_clause}
                """
            )
        ).mappings().first()
        if row is None:
            return None
        result = conn.execute(
            text(
                """
                UPDATE submissions
                SET verdict = 'running',
                    started_at = COALESCE(started_at, :claimed_at),
                    judger_id = :judger_id,
                    claimed_at = :claimed_at,
                    claim_expires_at = :claim_expires_at,
                    claim_token = :claim_token,
                    attempt_number = attempt_number + 1
                WHERE id = :id AND verdict = 'queued'
                """
            ),
            {
                "id": row["id"],
                "claimed_at": claimed_at,
                "claim_expires_at": claim_expires_at,
                "claim_token": claim_token,
                "judger_id": JUDGER_ID,
            },
        )
        if result.rowcount != 1:
            return None
        claimed = dict(row)
        claimed["claim_token"] = claim_token
        claimed["claimed_at"] = claimed_at
        claimed["claim_expires_at"] = claim_expires_at
        return claimed


def extend_submission_lease(submission_id: int, claim_token: str) -> bool:
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                UPDATE submissions
                SET claim_expires_at = :claim_expires_at
                WHERE id = :id AND claim_token = :claim_token AND verdict = 'running'
                """
            ),
            {
                "id": submission_id,
                "claim_token": claim_token,
                "claim_expires_at": utc_now() + timedelta(seconds=SUBMISSION_LEASE_SECONDS),
            },
        )
        return result.rowcount == 1


def reclaim_expired_submissions() -> int:
    now = utc_now()
    with engine.begin() as conn:
        rows = list(
            conn.execute(
                text(
                    """
                    SELECT id, attempt_number
                    FROM submissions
                    WHERE verdict = 'running'
                      AND claim_expires_at IS NOT NULL
                      AND claim_expires_at < :now
                    """
                ),
                {"now": now},
            ).mappings()
        )
        reclaimed = 0
        for row in rows:
            if int(row["attempt_number"] or 0) >= SUBMISSION_MAX_ATTEMPTS:
                result = conn.execute(
                    text(
                        """
                        UPDATE submissions
                        SET verdict = 'internal_error',
                            score = 0,
                            compile_output = :compile_output,
                            finished_at = :finished_at,
                            claim_token = NULL,
                            claim_expires_at = NULL,
                            judger_id = NULL
                        WHERE id = :id
                          AND verdict = 'running'
                          AND claim_expires_at IS NOT NULL
                          AND claim_expires_at < :now
                        """
                    ),
                    {
                        "id": row["id"],
                        "now": now,
                        "finished_at": now,
                        "compile_output": f"Submission lease expired after {SUBMISSION_MAX_ATTEMPTS} attempts",
                    },
                )
            else:
                conn.execute(text("DELETE FROM test_results WHERE submission_id = :id"), {"id": row["id"]})
                result = conn.execute(
                    text(
                        """
                        UPDATE submissions
                        SET verdict = 'queued',
                            started_at = NULL,
                            finished_at = NULL,
                            judger_id = NULL,
                            claimed_at = NULL,
                            claim_expires_at = NULL,
                            claim_token = NULL
                        WHERE id = :id
                          AND verdict = 'running'
                          AND claim_expires_at IS NOT NULL
                          AND claim_expires_at < :now
                        """
                    ),
                    {"id": row["id"], "now": now},
                )
            reclaimed += result.rowcount
        return reclaimed


def fetch_tests(task_id: int) -> list[dict]:
    with engine.begin() as conn:
        return list(
            conn.execute(
                text("SELECT id, input_data, output_data FROM task_tests WHERE task_id = :task_id ORDER BY id"),
                {"task_id": task_id},
            ).mappings()
        )


def verdict_to_db(verdict: str) -> str:
    verdicts = {
        VERDICT_ACCEPTED: "accepted",
        VERDICT_WRONG_ANSWER: "wrong_answer",
        VERDICT_TIME_LIMIT: "time_limit",
        VERDICT_MEMORY_LIMIT: "memory_limit",
        VERDICT_RUNTIME_ERROR: "runtime_error",
        VERDICT_COMPILATION_ERROR: "compilation_error",
        VERDICT_INTERNAL_ERROR: "internal_error",
    }
    return verdicts.get(verdict, verdict)


def calculate_score(points: float, accepted_count: int, test_count: int, partial_scoring: bool = False) -> float:
    if test_count <= 0:
        return 0.0
    if not partial_scoring:
        return round(float(points), 2) if accepted_count == test_count else 0.0
    return round((accepted_count / test_count) * float(points), 2)


def finish_submission(submission_id: int, verdict: str, score: float, compile_output: str = "", claim_token: str | None = None) -> bool:
    token_filter = "" if claim_token is None else "AND claim_token = :claim_token"
    with engine.begin() as conn:
        result = conn.execute(
            text(
                f"""
                UPDATE submissions
                SET verdict = :verdict,
                    score = :score,
                    compile_output = :compile_output,
                    finished_at = :finished_at,
                    claim_token = NULL,
                    claim_expires_at = NULL
                WHERE id = :id
                {token_filter}
                """
            ),
            {
                "id": submission_id,
                "claim_token": claim_token,
                "verdict": verdict_to_db(verdict),
                "score": score,
                "compile_output": compile_output[:8000],
                "finished_at": utc_now(),
            },
        )
        return result.rowcount == 1


def insert_result(submission_id: int, test_id: int, verdict: str, time_ms: int, output: str, error: str, claim_token: str | None = None) -> bool:
    with engine.begin() as conn:
        if claim_token is not None:
            current = conn.execute(
                text(
                    """
                    SELECT 1
                    FROM submissions
                    WHERE id = :submission_id AND claim_token = :claim_token AND verdict = 'running'
                    """
                ),
                {"submission_id": submission_id, "claim_token": claim_token},
            ).first()
            if current is None:
                return False
        conn.execute(
            text(
                """
                INSERT INTO test_results (submission_id, task_test_id, verdict, time_ms, output, error)
                VALUES (:submission_id, :task_test_id, :verdict, :time_ms, :output, :error)
                """
            ),
            {
                "submission_id": submission_id,
                "task_test_id": test_id,
                "verdict": verdict_to_db(verdict),
                "time_ms": time_ms,
                "output": output[:8000],
                "error": error[:8000],
            },
        )
        return True


def judge(submission: dict) -> None:
    claim_token = submission["claim_token"]
    event_payload = {"claim_token": claim_token, "attempt_number": submission.get("attempt_number")}
    tests = fetch_tests(submission["task_id"])
    if not tests:
        set_judger_state("reporting", submission["id"])
        finish_submission(submission["id"], VERDICT_INTERNAL_ERROR, 0, "Task has no tests", claim_token)
        write_judger_event("failed_submission", submission["id"], "Task has no tests", event_payload)
        return

    with tempfile.TemporaryDirectory(prefix="simple-contester-", dir=submission_work_root()) as tmp:
        workdir = Path(tmp)
        limits = Limits(
            time_limit_ms=submission["time_limit_ms"],
            memory_limit_mb=submission["memory_limit_mb"],
        )
        if not extend_submission_lease(submission["id"], claim_token):
            return
        set_judger_state("compiling", submission["id"])
        write_judger_event("compile_started", submission["id"], payload=event_payload)
        runner = create_runner(submission["language"], workdir, submission["source_code"], limits)
        if runner is None:
            set_judger_state("reporting", submission["id"])
            finish_submission(
                submission["id"],
                VERDICT_COMPILATION_ERROR,
                0,
                f"Unsupported language: {submission['language']}",
                claim_token,
            )
            write_judger_event(
                "failed_submission",
                submission["id"],
                f"Unsupported language: {submission['language']}",
                event_payload,
            )
            return
        compiled = runner.compile()
        if not extend_submission_lease(submission["id"], claim_token):
            return
        if compiled.command is None:
            set_judger_state("reporting", submission["id"])
            finish_submission(
                submission["id"],
                compiled.verdict or VERDICT_COMPILATION_ERROR,
                0,
                compiled.output,
                claim_token,
            )
            write_judger_event(
                "failed_submission",
                submission["id"],
                compiled.output[:500] or "Compilation failed",
                {**event_payload, "verdict": compiled.verdict or VERDICT_COMPILATION_ERROR},
            )
            return

        final_verdict = VERDICT_ACCEPTED
        accepted_count = 0
        set_judger_state("running", submission["id"])
        write_judger_event("run_started", submission["id"], payload={**event_payload, "tests": len(tests)})
        for case in tests:
            if not extend_submission_lease(submission["id"], claim_token):
                return
            with copy_run_workspace(workdir) as run_tmp:
                run_workdir = Path(run_tmp)
                run_result = run_program(
                    compiled.command,
                    case["input_data"],
                    cwd=run_workdir,
                    limits=limits,
                    env=env_for_workdir(runner.run_env(), run_workdir),
                    address_space_limit_bytes=runner.address_space_limit_bytes(),
                )
            if run_result.verdict != VERDICT_ACCEPTED:
                verdict = run_result.verdict
            elif normalize_output(run_result.stdout) != normalize_output(case["output_data"]):
                verdict = VERDICT_WRONG_ANSWER
            else:
                verdict = VERDICT_ACCEPTED
                accepted_count += 1
            insert_result(
                submission["id"],
                case["id"],
                verdict,
                run_result.time_ms,
                run_result.stdout,
                run_result.stderr,
                claim_token,
            )
            if final_verdict == VERDICT_ACCEPTED and verdict != VERDICT_ACCEPTED:
                final_verdict = verdict
            if STOP_ON_FIRST_FAILED_TEST and verdict != VERDICT_ACCEPTED:
                break
        score = calculate_score(submission["points"], accepted_count, len(tests), bool(submission["partial_scoring"]))
        set_judger_state("reporting", submission["id"])
        finish_submission(
            submission["id"],
            final_verdict,
            score,
            claim_token=claim_token,
        )
        write_judger_event(
            "finished_submission",
            submission["id"],
            payload={**event_payload, "verdict": final_verdict, "score": score},
        )


def main() -> None:
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    atexit.register(mark_stopping)
    set_judger_state("starting", None)
    write_judger_event("started", message="Judger registered", payload={"version": JUDGER_VERSION})
    heartbeat = threading.Thread(target=heartbeat_loop, daemon=True)
    heartbeat.start()
    try:
        while not stop_event.is_set():
            set_judger_state("polling", None, write_now=False)
            reclaim_expired_submissions()
            set_judger_state("claiming", None, write_now=False)
            submission = acquire_submission()
            if submission is None:
                set_judger_state("idle", None, write_now=False)
                stop_event.wait(POLL_INTERVAL_SECONDS)
                continue
            write_judger_event(
                "claimed_submission",
                submission["id"],
                payload={
                    "claim_token": submission.get("claim_token"),
                    "claim_expires_at": submission.get("claim_expires_at"),
                    "attempt_number": submission.get("attempt_number"),
                },
            )
            try:
                judge(submission)
                set_judger_state("idle", None)
            except Exception as exc:
                message = str(exc)
                set_judger_state("reporting", submission["id"], message)
                finish_submission(submission["id"], VERDICT_INTERNAL_ERROR, 0, message, submission.get("claim_token"))
                write_judger_event(
                    "internal_error",
                    submission["id"],
                    message,
                    {"claim_token": submission.get("claim_token"), "attempt_number": submission.get("attempt_number")},
                )
                set_judger_state("idle", None, message)
    finally:
        stop_event.set()
        mark_stopping()


if __name__ == "__main__":
    main()

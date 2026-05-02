import os
import tempfile
import time
from datetime import datetime
from pathlib import Path

from sqlalchemy import create_engine, text

from runners import (
    Limits,
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
POLL_INTERVAL_SECONDS = float(os.getenv("POLL_INTERVAL_SECONDS", "1"))
STOP_ON_FIRST_FAILED_TEST = os.getenv("STOP_ON_FIRST_FAILED_TEST", "0") != "0"

engine = create_engine(DATABASE_URL, pool_pre_ping=True)


def utc_now() -> datetime:
    return datetime.utcnow()


def normalize_output(value: str) -> str:
    return "\n".join(line.rstrip() for line in value.strip().splitlines()).strip()


def acquire_submission() -> dict | None:
    with engine.begin() as conn:
        # The row lock plus SKIP LOCKED lets several judgers poll concurrently
        # without blocking each other or claiming the same queued submission.
        row = conn.execute(
            text(
                """
                SELECT submissions.id, submissions.language, submissions.source_code, submissions.task_id,
                       tasks.time_limit_ms, tasks.memory_limit_mb, tasks.points, tasks.partial_scoring
                FROM submissions
                JOIN tasks ON tasks.id = submissions.task_id
                WHERE verdict = 'queued'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """
            )
        ).mappings().first()
        if row is None:
            return None
        result = conn.execute(
            text(
                """
                UPDATE submissions
                SET verdict = 'running', started_at = :started_at, judger_id = :judger_id
                WHERE id = :id AND verdict = 'queued'
                """
            ),
            {"id": row["id"], "started_at": utc_now(), "judger_id": JUDGER_ID},
        )
        if result.rowcount != 1:
            return None
        return dict(row)


def fetch_tests(task_id: int) -> list[dict]:
    with engine.begin() as conn:
        return list(
            conn.execute(
                text("SELECT id, input_data, output_data FROM task_tests WHERE task_id = :task_id ORDER BY id"),
                {"task_id": task_id},
            ).mappings()
        )


def verdict_to_db(verdict: str) -> str:
    return {
        VERDICT_ACCEPTED: "accepted",
        VERDICT_WRONG_ANSWER: "wrong_answer",
        VERDICT_TIME_LIMIT: "time_limit",
        VERDICT_MEMORY_LIMIT: "memory_limit",
        VERDICT_RUNTIME_ERROR: "runtime_error",
        VERDICT_COMPILATION_ERROR: "compilation_error",
        VERDICT_INTERNAL_ERROR: "internal_error",
    }[verdict]


def calculate_score(points: float, accepted_count: int, test_count: int, partial_scoring: bool = False) -> float:
    if test_count <= 0:
        return 0.0
    if not partial_scoring:
        return round(float(points), 2) if accepted_count == test_count else 0.0
    return round((accepted_count / test_count) * float(points), 2)


def finish_submission(submission_id: int, verdict: str, score: float, compile_output: str = "") -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                UPDATE submissions
                SET verdict = :verdict, score = :score, compile_output = :compile_output, finished_at = :finished_at
                WHERE id = :id
                """
            ),
            {
                "id": submission_id,
                "verdict": verdict_to_db(verdict),
                "score": score,
                "compile_output": compile_output[:8000],
                "finished_at": utc_now(),
            },
        )


def insert_result(submission_id: int, test_id: int, verdict: str, time_ms: int, output: str, error: str) -> None:
    with engine.begin() as conn:
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


def judge(submission: dict) -> None:
    tests = fetch_tests(submission["task_id"])
    if not tests:
        finish_submission(submission["id"], VERDICT_INTERNAL_ERROR, 0, "Task has no tests")
        return

    with tempfile.TemporaryDirectory(prefix="simple-contester-") as tmp:
        workdir = Path(tmp)
        limits = Limits(
            time_limit_ms=submission["time_limit_ms"],
            memory_limit_mb=submission["memory_limit_mb"],
        )
        runner = create_runner(submission["language"], workdir, submission["source_code"], limits)
        if runner is None:
            finish_submission(
                submission["id"],
                VERDICT_COMPILATION_ERROR,
                0,
                f"Unsupported language: {submission['language']}",
            )
            return
        compiled = runner.compile()
        if compiled.command is None:
            finish_submission(
                submission["id"],
                compiled.verdict or VERDICT_COMPILATION_ERROR,
                0,
                compiled.output,
            )
            return

        final_verdict = VERDICT_ACCEPTED
        accepted_count = 0
        for case in tests:
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
            )
            if final_verdict == VERDICT_ACCEPTED and verdict != VERDICT_ACCEPTED:
                final_verdict = verdict
            if STOP_ON_FIRST_FAILED_TEST and verdict != VERDICT_ACCEPTED:
                break
        score = calculate_score(submission["points"], accepted_count, len(tests), bool(submission["partial_scoring"]))
        finish_submission(
            submission["id"],
            final_verdict,
            score,
        )


def main() -> None:
    while True:
        submission = acquire_submission()
        if submission is None:
            time.sleep(POLL_INTERVAL_SECONDS)
            continue
        try:
            judge(submission)
        except Exception as exc:
            finish_submission(submission["id"], "internal_error", 0, str(exc))


if __name__ == "__main__":
    main()

"""Initial schema.

Revision ID: 20260502_0001
Revises:
Create Date: 2026-05-02 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260502_0001"
down_revision = None
branch_labels = None
depends_on = None


conteststatus = sa.Enum("draft", "scheduled", "running", "finished", "archived", name="conteststatus")
contesttimemode = sa.Enum("fixed", "individual", name="contesttimemode")
language = sa.Enum(
    "python",
    "java",
    "javascript",
    "typescript",
    "c11",
    "cpp17",
    "cpp20",
    "csharp",
    "object_pascal",
    "fortran",
    "go",
    "lua",
    name="language",
)
submissionverdict = sa.Enum(
    "queued",
    "running",
    "accepted",
    "wrong_answer",
    "time_limit",
    "memory_limit",
    "runtime_error",
    "compilation_error",
    "internal_error",
    name="submissionverdict",
)
userrole = sa.Enum("admin", "participant", name="userrole")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("role", userrole, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_teams_name"), "teams", ["name"], unique=True)

    op.create_table(
        "contests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", conteststatus, nullable=False),
        sa.Column("time_mode", contesttimemode, nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("individual_duration_minutes", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "team_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_team_user"),
    )

    op.create_table(
        "contest_teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "team_id", name="uq_contest_team"),
    )
    op.create_index(op.f("ix_contest_teams_contest_id"), "contest_teams", ["contest_id"], unique=False)
    op.create_index(op.f("ix_contest_teams_team_id"), "contest_teams", ["team_id"], unique=False)

    op.create_table(
        "participant_contests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "user_id", name="uq_participant_contest"),
    )

    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("input_format", sa.Text(), nullable=False),
        sa.Column("output_format", sa.Text(), nullable=False),
        sa.Column("samples", sa.Text(), nullable=False),
        sa.Column("time_limit_ms", sa.Integer(), nullable=False),
        sa.Column("memory_limit_mb", sa.Integer(), nullable=False),
        sa.Column("points", sa.Float(), nullable=False),
        sa.Column("partial_scoring", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_tasks_contest_id"), "tasks", ["contest_id"], unique=False)

    op.create_table(
        "contest_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contest_id", "task_id", name="uq_contest_task"),
    )
    op.create_index(op.f("ix_contest_tasks_contest_id"), "contest_tasks", ["contest_id"], unique=False)
    op.create_index(op.f("ix_contest_tasks_task_id"), "contest_tasks", ["task_id"], unique=False)

    op.create_table(
        "task_tests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("input_data", sa.Text(), nullable=False),
        sa.Column("output_data", sa.Text(), nullable=False),
        sa.Column("is_sample", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_tests_task_id"), "task_tests", ["task_id"], unique=False)

    op.create_table(
        "submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("contest_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("language", language, nullable=False),
        sa.Column("source_code", sa.Text(), nullable=False),
        sa.Column("verdict", submissionverdict, nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("compile_output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("judger_id", sa.String(length=120), nullable=True),
        sa.ForeignKeyConstraint(["contest_id"], ["contests.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_submissions_contest_id"), "submissions", ["contest_id"], unique=False)
    op.create_index(op.f("ix_submissions_created_at"), "submissions", ["created_at"], unique=False)
    op.create_index(op.f("ix_submissions_task_id"), "submissions", ["task_id"], unique=False)
    op.create_index(op.f("ix_submissions_user_id"), "submissions", ["user_id"], unique=False)
    op.create_index(op.f("ix_submissions_verdict"), "submissions", ["verdict"], unique=False)

    op.create_table(
        "test_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=False),
        sa.Column("task_test_id", sa.Integer(), nullable=False),
        sa.Column("verdict", submissionverdict, nullable=False),
        sa.Column("time_ms", sa.Integer(), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_test_id"], ["task_tests.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_test_results_submission_id"), "test_results", ["submission_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_test_results_submission_id"), table_name="test_results")
    op.drop_table("test_results")
    op.drop_index(op.f("ix_submissions_verdict"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_user_id"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_task_id"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_created_at"), table_name="submissions")
    op.drop_index(op.f("ix_submissions_contest_id"), table_name="submissions")
    op.drop_table("submissions")
    op.drop_index(op.f("ix_task_tests_task_id"), table_name="task_tests")
    op.drop_table("task_tests")
    op.drop_index(op.f("ix_contest_tasks_task_id"), table_name="contest_tasks")
    op.drop_index(op.f("ix_contest_tasks_contest_id"), table_name="contest_tasks")
    op.drop_table("contest_tasks")
    op.drop_index(op.f("ix_tasks_contest_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("participant_contests")
    op.drop_index(op.f("ix_contest_teams_team_id"), table_name="contest_teams")
    op.drop_index(op.f("ix_contest_teams_contest_id"), table_name="contest_teams")
    op.drop_table("contest_teams")
    op.drop_table("team_members")
    op.drop_table("contests")
    op.drop_index(op.f("ix_teams_name"), table_name="teams")
    op.drop_table("teams")
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_table("users")

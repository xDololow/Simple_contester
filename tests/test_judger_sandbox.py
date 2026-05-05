from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


JUDGER_PATH = Path(__file__).resolve().parents[1] / "judger"
sys.path.insert(0, str(JUDGER_PATH))

import runners  # noqa: E402
from runners import (  # noqa: E402
    Limits,
    VERDICT_ACCEPTED,
    VERDICT_MEMORY_LIMIT,
    VERDICT_RUNTIME_ERROR,
    VERDICT_TIME_LIMIT,
    build_docker_run_command,
    copy_run_workspace,
    create_runner,
    docker_env_for_workdir,
    env_for_workdir,
    run_program,
)


def compile_python(source: str, limits: Limits):
    build_tmp = tempfile.TemporaryDirectory(prefix="judger-sandbox-build-")
    runner = create_runner("python", Path(build_tmp.name), source, limits)
    assert runner is not None
    compiled = runner.compile()
    assert compiled.command is not None, compiled.output
    return build_tmp, runner, compiled


def run_python_source(source: str, limits: Limits, input_data: str = ""):
    build_tmp, runner, compiled = compile_python(source, limits)
    with build_tmp:
        with copy_run_workspace(Path(build_tmp.name)) as run_tmp:
            run_dir = Path(run_tmp)
            return run_program(
                compiled.command,
                input_data,
                cwd=run_dir,
                limits=limits,
                env=env_for_workdir(runner.run_env(), run_dir),
                address_space_limit_bytes=runner.address_space_limit_bytes(),
            )


def test_huge_output_is_bounded_and_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runners, "OUTPUT_LIMIT_BYTES", 8192)
    result = run_python_source(
        "import sys\nsys.stdout.write('x' * 20000)\nsys.stdout.flush()\n",
        Limits(time_limit_ms=2000, memory_limit_mb=128),
    )

    assert result.verdict == VERDICT_RUNTIME_ERROR
    assert result.output_truncated
    assert len(result.stdout.encode("utf-8")) <= 9000
    assert "Output limit exceeded" in result.stderr


def test_each_run_gets_fresh_workdir() -> None:
    limits = Limits(time_limit_ms=2000, memory_limit_mb=128)
    build_tmp, runner, compiled = compile_python(
        """
from pathlib import Path
marker = Path("leak.txt")
print("leaked" if marker.exists() else "clean")
marker.write_text("created by previous run")
""",
        limits,
    )

    with build_tmp:
        outputs = []
        for _ in range(2):
            with copy_run_workspace(Path(build_tmp.name)) as run_tmp:
                run_dir = Path(run_tmp)
                result = run_program(
                    compiled.command,
                    "",
                    cwd=run_dir,
                    limits=limits,
                    env=env_for_workdir(runner.run_env(), run_dir),
                    address_space_limit_bytes=runner.address_space_limit_bytes(),
                )
                assert result.verdict == VERDICT_ACCEPTED, result.stderr
                outputs.append(result.stdout.strip())

    assert outputs == ["clean", "clean"]


def test_time_limit_is_reported() -> None:
    result = run_python_source(
        "while True:\n    pass\n",
        Limits(time_limit_ms=200, memory_limit_mb=128),
    )

    assert result.verdict == VERDICT_TIME_LIMIT


def test_memory_limit_is_reported() -> None:
    result = run_python_source(
        "data = bytearray(512 * 1024 * 1024)\nprint(len(data))\n",
        Limits(time_limit_ms=2000, memory_limit_mb=128),
    )

    assert result.verdict == VERDICT_MEMORY_LIMIT


def test_process_limit_blocks_small_fork_bomb(monkeypatch: pytest.MonkeyPatch) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("RLIMIT_NPROC is not reliably enforced for root")
    if not hasattr(os, "fork"):
        pytest.skip("fork is not available on this platform")

    monkeypatch.setattr(runners, "PROCESS_LIMIT", 8)
    result = run_python_source(
        """
import os
import time

children = []
for _ in range(64):
    try:
        pid = os.fork()
    except OSError:
        print("blocked")
        break
    if pid == 0:
        time.sleep(0.5)
        os._exit(0)
    children.append(pid)
else:
    print("not blocked")

for pid in children:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
""",
        Limits(time_limit_ms=2000, memory_limit_mb=128),
    )

    assert result.verdict == VERDICT_ACCEPTED
    assert "blocked" in result.stdout


def test_docker_command_builder_applies_hard_sandbox_flags() -> None:
    with tempfile.TemporaryDirectory(prefix="judger-docker-builder-") as tmp:
        workdir = Path(tmp)
        command = build_docker_run_command(
            ["python", "main.py"],
            workdir,
            {"PATH": "/usr/bin", "HOME": str(workdir), "TMPDIR": str(workdir)},
            memory_limit_mb=128,
            pids_limit=16,
            file_size_limit_bytes=4096,
            container_name="simple-contester-test",
        )

    assert command[:4] == ["docker", "run", "--rm", "--name"]
    assert "--network" in command
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert "--tmpfs" in command
    assert "--user" in command
    assert command[command.index("--user") + 1] == "judge"
    assert "--cap-drop" in command
    assert command[command.index("--cap-drop") + 1] == "ALL"
    assert "--security-opt" in command
    assert command[command.index("--security-opt") + 1] == "no-new-privileges:true"
    assert "--pids-limit" in command
    assert command[command.index("--pids-limit") + 1] == "16"
    assert "--memory" in command
    assert command[command.index("--memory") + 1] == "128m"
    assert "--memory-swap" in command
    assert command[command.index("--memory-swap") + 1] == "128m"
    assert "--cpus" in command
    assert "--ulimit" in command
    assert "fsize=4096:4096" in command
    assert any(part.startswith("type=bind,") and "dst=/workspace,rw" in part for part in command)
    assert command[-3:] == ["simple-contester-judger:local", "python", "main.py"]


def test_docker_env_translates_workspace_paths() -> None:
    with tempfile.TemporaryDirectory(prefix="judger-docker-env-") as tmp:
        workdir = Path(tmp)
        env = docker_env_for_workdir(
            {
                "HOME": str(workdir),
                "TMPDIR": str(workdir),
                "GOCACHE": str(workdir / ".gocache"),
                "PATH": "/usr/local/bin:/usr/bin:/bin",
            },
            workdir,
            "/workspace",
        )

    assert env["HOME"] == "/tmp"
    assert env["TMPDIR"] == "/tmp"
    assert env["GOCACHE"] == "/workspace/.gocache"
    assert env["PATH"] == "/usr/local/bin:/usr/bin:/bin"


def docker_smoke_available() -> bool:
    if shutil.which("docker") is None:
        return False
    image = os.getenv("JUDGER_DOCKER_IMAGE", "simple-contester-judger:local")
    return subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0


@pytest.mark.skipif(not docker_smoke_available(), reason="docker or sandbox image is not available")
def test_docker_sandbox_denies_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGER_SANDBOX_MODE", "docker")
    result = run_python_source(
        """
import socket
try:
    socket.create_connection(("1.1.1.1", 80), timeout=1)
except OSError:
    print("denied")
else:
    print("connected")
""",
        Limits(time_limit_ms=2000, memory_limit_mb=128),
    )

    assert result.verdict == VERDICT_ACCEPTED
    assert result.stdout.strip() == "denied"


@pytest.mark.skipif(not docker_smoke_available(), reason="docker or sandbox image is not available")
def test_docker_sandbox_uses_fresh_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGER_SANDBOX_MODE", "docker")
    test_each_run_gets_fresh_workdir()


@pytest.mark.skipif(not docker_smoke_available(), reason="docker or sandbox image is not available")
def test_docker_sandbox_reports_huge_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JUDGER_SANDBOX_MODE", "docker")
    test_huge_output_is_bounded_and_reported(monkeypatch)

from __future__ import annotations

import math
import os
import resource
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


VERDICT_ACCEPTED = "accepted"
VERDICT_WRONG_ANSWER = "wrong_answer"
VERDICT_TIME_LIMIT = "time_limit"
VERDICT_MEMORY_LIMIT = "memory_limit"
VERDICT_RUNTIME_ERROR = "runtime_error"
VERDICT_COMPILATION_ERROR = "compilation_error"
VERDICT_INTERNAL_ERROR = "internal_error"

COMPILE_TIMEOUT_SECONDS = int(os.getenv("COMPILE_TIMEOUT_SECONDS", "20"))
OUTPUT_LIMIT_BYTES = int(os.getenv("OUTPUT_LIMIT_BYTES", str(1024 * 1024)))


@dataclass(frozen=True)
class Limits:
    time_limit_ms: int
    memory_limit_mb: int

    @property
    def timeout_seconds(self) -> float:
        return max(0.05, self.time_limit_ms / 1000)

    @property
    def cpu_limit_seconds(self) -> int:
        return max(1, math.ceil(self.timeout_seconds) + 1)

    @property
    def memory_bytes(self) -> int:
        return max(16, self.memory_limit_mb) * 1024 * 1024


@dataclass(frozen=True)
class CompileResult:
    command: list[str] | None
    verdict: str | None = None
    output: str = ""


@dataclass(frozen=True)
class RunResult:
    verdict: str
    time_ms: int
    stdout: str = ""
    stderr: str = ""


class Runner:
    language: str = ""
    source_name: str = ""

    def __init__(self, workdir: Path, source_code: str, limits: Limits):
        self.workdir = workdir
        self.source_code = source_code
        self.limits = limits

    def compile(self) -> CompileResult:
        source = self.workdir / self.source_name
        source.write_text(self.source_code, encoding="utf-8")
        return CompileResult(command=self.command())

    def command(self) -> list[str]:
        raise NotImplementedError

    def compile_env(self) -> dict[str, str]:
        return isolated_env(self.workdir)

    def run_env(self) -> dict[str, str]:
        return isolated_env(self.workdir)

    def address_space_limit_bytes(self) -> int | None:
        return self.limits.memory_bytes


class PythonRunner(Runner):
    language = "python"
    source_name = "main.py"

    def command(self) -> list[str]:
        return ["python", "main.py"]


class JavaScriptRunner(Runner):
    language = "javascript"
    source_name = "main.js"

    def command(self) -> list[str]:
        return ["node", "main.js"]

    def run_env(self) -> dict[str, str]:
        env = isolated_env(self.workdir)
        env["NODE_OPTIONS"] = f"--no-warnings --max-old-space-size={self.limits.memory_limit_mb}"
        return env

    def address_space_limit_bytes(self) -> int | None:
        return None


class TypeScriptRunner(Runner):
    language = "typescript"
    source_name = "main.ts"

    def compile(self) -> CompileResult:
        source = self.workdir / self.source_name
        source.write_text(self.source_code, encoding="utf-8")
        completed = run_compile(
            ["tsc", "main.ts", "--target", "ES2020", "--module", "commonjs", "--outDir", "."],
            cwd=self.workdir,
            env=self.compile_env(),
        )
        if completed.returncode != 0:
            return CompileResult(
                command=None,
                verdict=VERDICT_COMPILATION_ERROR,
                output=combine_output(completed.stdout, completed.stderr),
            )
        return CompileResult(command=["node", "main.js"])

    def run_env(self) -> dict[str, str]:
        env = isolated_env(self.workdir)
        env["NODE_OPTIONS"] = f"--no-warnings --max-old-space-size={self.limits.memory_limit_mb}"
        return env

    def address_space_limit_bytes(self) -> int | None:
        return None


class CompiledBinaryRunner(Runner):
    output_name = "main"
    compile_command: list[str] = []

    def compile(self) -> CompileResult:
        source = self.workdir / self.source_name
        source.write_text(self.source_code, encoding="utf-8")
        completed = run_compile(self.compile_command, cwd=self.workdir, env=self.compile_env())
        if completed.returncode != 0:
            return CompileResult(
                command=None,
                verdict=VERDICT_COMPILATION_ERROR,
                output=combine_output(completed.stdout, completed.stderr),
            )
        return CompileResult(command=self.command())

    def command(self) -> list[str]:
        return [f"./{self.output_name}"]


class C11Runner(CompiledBinaryRunner):
    language = "c11"
    source_name = "main.c"
    compile_command = ["gcc", "-std=c11", "-O2", "-pipe", "-o", "main", "main.c"]


class Cpp17Runner(CompiledBinaryRunner):
    language = "cpp17"
    source_name = "main.cpp"
    compile_command = ["g++", "-std=c++17", "-O2", "-pipe", "-o", "main", "main.cpp"]


class Cpp20Runner(CompiledBinaryRunner):
    language = "cpp20"
    source_name = "main.cpp"
    compile_command = ["g++", "-std=c++20", "-O2", "-pipe", "-o", "main", "main.cpp"]


class CSharpRunner(Runner):
    language = "csharp"
    source_name = "Main.cs"

    def compile(self) -> CompileResult:
        source = self.workdir / self.source_name
        source.write_text(self.source_code, encoding="utf-8")
        completed = run_compile(["mcs", "-out:Main.exe", "Main.cs"], cwd=self.workdir, env=self.compile_env())
        if completed.returncode != 0:
            return CompileResult(
                command=None,
                verdict=VERDICT_COMPILATION_ERROR,
                output=combine_output(completed.stdout, completed.stderr),
            )
        return CompileResult(command=self.command())

    def command(self) -> list[str]:
        return ["mono", "Main.exe"]

    def address_space_limit_bytes(self) -> int | None:
        return None


class ObjectPascalRunner(CompiledBinaryRunner):
    language = "object_pascal"
    source_name = "main.pas"
    compile_command = ["fpc", "-omain", "main.pas"]


class FortranRunner(CompiledBinaryRunner):
    language = "fortran"
    source_name = "main.f90"
    compile_command = ["gfortran", "-O2", "-pipe", "-o", "main", "main.f90"]


class GoRunner(CompiledBinaryRunner):
    language = "go"
    source_name = "main.go"
    compile_command = ["go", "build", "-o", "main", "main.go"]

    def compile_env(self) -> dict[str, str]:
        env = isolated_env(self.workdir)
        env["GOCACHE"] = str(self.workdir / ".gocache")
        env["GOPATH"] = str(self.workdir / ".gopath")
        return env

    def run_env(self) -> dict[str, str]:
        env = isolated_env(self.workdir)
        env["GOMEMLIMIT"] = f"{self.limits.memory_limit_mb}MiB"
        return env

    def address_space_limit_bytes(self) -> int | None:
        return None


class LuaRunner(Runner):
    language = "lua"
    source_name = "main.lua"

    def command(self) -> list[str]:
        return ["lua5.4", "main.lua"]


class JavaRunner(Runner):
    language = "java"
    source_name = "Main.java"

    def compile(self) -> CompileResult:
        source = self.workdir / self.source_name
        source.write_text(self.source_code, encoding="utf-8")
        completed = run_compile(["javac", "Main.java"], cwd=self.workdir, env=self.compile_env())
        if completed.returncode != 0:
            return CompileResult(
                command=None,
                verdict=VERDICT_COMPILATION_ERROR,
                output=combine_output(completed.stdout, completed.stderr),
            )
        return CompileResult(command=self.command())

    def command(self) -> list[str]:
        return ["java", f"-Xmx{self.limits.memory_limit_mb}m", "-cp", ".", "Main"]

    def address_space_limit_bytes(self) -> int | None:
        return None


RUNNERS: dict[str, type[Runner]] = {
    PythonRunner.language: PythonRunner,
    JavaRunner.language: JavaRunner,
    JavaScriptRunner.language: JavaScriptRunner,
    TypeScriptRunner.language: TypeScriptRunner,
    C11Runner.language: C11Runner,
    Cpp17Runner.language: Cpp17Runner,
    Cpp20Runner.language: Cpp20Runner,
    CSharpRunner.language: CSharpRunner,
    ObjectPascalRunner.language: ObjectPascalRunner,
    FortranRunner.language: FortranRunner,
    GoRunner.language: GoRunner,
    LuaRunner.language: LuaRunner,
}


def create_runner(language: str, workdir: Path, source_code: str, limits: Limits) -> Runner | None:
    runner_type = RUNNERS.get(language)
    if runner_type is None:
        return None
    return runner_type(workdir, source_code, limits)


def run_compile(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=COMPILE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        return subprocess.CompletedProcess(
            command,
            returncode=-signal.SIGXCPU,
            stdout=exc.stdout or "",
            stderr=(exc.stderr or "") + "\nCompilation timed out",
        )


def run_program(
    command: list[str],
    input_data: str,
    cwd: Path,
    limits: Limits,
    env: dict[str, str],
    address_space_limit_bytes: int | None = None,
) -> RunResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            input=input_data,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=limits.timeout_seconds,
            preexec_fn=lambda: apply_resource_limits(limits, address_space_limit_bytes),
            start_new_session=True,
        )
    except subprocess.TimeoutExpired as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return RunResult(
            verdict=VERDICT_TIME_LIMIT,
            time_ms=elapsed_ms,
            stdout=exc.stdout or "",
            stderr=exc.stderr or "",
        )

    elapsed_ms = int((time.monotonic() - started) * 1000)
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    if completed.returncode == 0:
        return RunResult(verdict=VERDICT_ACCEPTED, time_ms=elapsed_ms, stdout=stdout, stderr=stderr)

    return RunResult(
        verdict=classify_failure(completed.returncode, stdout, stderr),
        time_ms=elapsed_ms,
        stdout=stdout,
        stderr=stderr,
    )


def apply_resource_limits(limits: Limits, address_space_limit_bytes: int | None) -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_limit_seconds, limits.cpu_limit_seconds + 1))
    if address_space_limit_bytes is not None:
        resource.setrlimit(resource.RLIMIT_AS, (address_space_limit_bytes, address_space_limit_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_LIMIT_BYTES, OUTPUT_LIMIT_BYTES))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))


def isolated_env(workdir: Path) -> dict[str, str]:
    path = os.getenv("PATH", "/usr/local/bin:/usr/bin:/bin")
    return {
        "PATH": path,
        "HOME": str(workdir),
        "TMPDIR": str(workdir),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONUNBUFFERED": "1",
        "NODE_OPTIONS": "--no-warnings",
    }


def classify_failure(returncode: int, stdout: str, stderr: str) -> str:
    if returncode in {-signal.SIGXCPU, -signal.SIGALRM}:
        return VERDICT_TIME_LIMIT
    if returncode in {-signal.SIGKILL, -signal.SIGSEGV, -signal.SIGABRT, -signal.SIGBUS}:
        return VERDICT_MEMORY_LIMIT
    combined = f"{stdout}\n{stderr}".lower()
    memory_markers = (
        "memoryerror",
        "outofmemoryerror",
        "javascript heap out of memory",
        "allocation failed",
        "cannot allocate memory",
        "std::bad_alloc",
    )
    if any(marker in combined for marker in memory_markers):
        return VERDICT_MEMORY_LIMIT
    return VERDICT_RUNTIME_ERROR


def combine_output(stdout: str | None, stderr: str | None) -> str:
    return "\n".join(part for part in ((stdout or "").strip(), (stderr or "").strip()) if part)

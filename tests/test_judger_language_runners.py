from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from app.schemas import SubmissionCreate


JUDGER_PATH = Path(__file__).resolve().parents[1] / "judger"
sys.path.insert(0, str(JUDGER_PATH))

from runners import (  # noqa: E402
    Limits,
    VERDICT_ACCEPTED,
    VERDICT_COMPILATION_ERROR,
    VERDICT_RUNTIME_ERROR,
    create_runner,
    run_program,
)
from worker import calculate_score  # noqa: E402


LIMITS = Limits(time_limit_ms=2000, memory_limit_mb=256)

ACCEPTED_SOURCES = {
    "c11": (
        "gcc",
        """
#include <stdio.h>

int main(void) {
    long long a, b;
    if (scanf("%lld %lld", &a, &b) != 2) return 1;
    printf("%lld\\n", a + b);
    return 0;
}
""",
    ),
    "cpp17": (
        "g++",
        """
#include <iostream>

int main() {
    long long a, b;
    std::cin >> a >> b;
    std::cout << a + b << '\\n';
    return 0;
}
""",
    ),
    "cpp20": (
        "g++",
        """
#include <iostream>
#include <span>

int main() {
    long long values[2] {};
    for (long long& value : std::span<long long, 2>(values)) {
        std::cin >> value;
    }
    std::cout << values[0] + values[1] << '\\n';
    return 0;
}
""",
    ),
    "csharp": (
        "mcs",
        """
using System;

class MainClass {
    static void Main() {
        var parts = Console.ReadLine().Split();
        Console.WriteLine(long.Parse(parts[0]) + long.Parse(parts[1]));
    }
}
""",
    ),
    "object_pascal": (
        "fpc",
        """
program Main;
var
  A, B: Int64;
begin
  ReadLn(A, B);
  WriteLn(A + B);
end.
""",
    ),
    "fortran": (
        "gfortran",
        """
program main
  implicit none
  integer :: a, b
  read (*, *) a, b
  print *, a + b
end program main
""",
    ),
    "go": (
        "go",
        """
package main

import "fmt"

func main() {
    var a, b int64
    fmt.Scan(&a, &b)
    fmt.Println(a + b)
}
""",
    ),
    "lua": (
        "lua5.4",
        """
local line = io.read("*line")
local a, b = line:match("(%S+)%s+(%S+)")
print(tonumber(a) + tonumber(b))
""",
    ),
}


def require_tool(tool: str) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} is not installed")


def run_source(language: str, source: str, input_data: str = "40 2\n"):
    with tempfile.TemporaryDirectory(prefix="judger-test-") as tmp:
        runner = create_runner(language, Path(tmp), source, LIMITS)
        assert runner is not None
        compiled = runner.compile()
        if compiled.command is None:
            return compiled, None
        result = run_program(
            compiled.command,
            input_data,
            cwd=Path(tmp),
            limits=LIMITS,
            env=runner.run_env(),
            address_space_limit_bytes=runner.address_space_limit_bytes(),
        )
        return compiled, result


@pytest.mark.parametrize("language", sorted(ACCEPTED_SOURCES))
def test_new_language_runner_accepts_a_plus_b(language: str) -> None:
    tool, source = ACCEPTED_SOURCES[language]
    require_tool(tool)
    compiled, result = run_source(language, source)
    assert compiled.command is not None, compiled.output
    assert result is not None
    assert result.verdict == VERDICT_ACCEPTED, result.stderr
    assert result.stdout.strip() == "42"


def test_compiled_language_reports_compilation_error() -> None:
    require_tool("gcc")
    compiled, result = run_source("c11", "int main(void) { return missing_symbol }\n")
    assert result is None
    assert compiled.command is None
    assert compiled.verdict == VERDICT_COMPILATION_ERROR
    assert compiled.output


def test_interpreted_language_reports_runtime_error() -> None:
    require_tool("lua5.4")
    compiled, result = run_source("lua", "error('boom')\n", "")
    assert compiled.command is not None
    assert result is not None
    assert result.verdict == VERDICT_RUNTIME_ERROR
    assert "boom" in result.stderr


@pytest.mark.parametrize("language", sorted(ACCEPTED_SOURCES))
def test_submission_schema_accepts_new_language_ids(language: str) -> None:
    data = SubmissionCreate(language=language, source_code="print(42)")
    assert data.language.value == language


def test_default_score_is_all_or_nothing() -> None:
    assert calculate_score(100, 5, 10) == 0.0
    assert calculate_score(100, 10, 10) == 100.0


def test_partial_score_is_optional_and_rounded_to_two_decimals() -> None:
    assert calculate_score(100, 5, 10, partial_scoring=True) == 50.0
    assert calculate_score(100, 1, 3, partial_scoring=True) == 33.33
    assert calculate_score(75.5, 2, 4, partial_scoring=True) == 37.75

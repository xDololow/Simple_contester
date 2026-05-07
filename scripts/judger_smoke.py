from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


judger_path = Path(os.environ.get("JUDGER_PATH", "/judger"))
sys.path.insert(0, str(judger_path))

from runners import Limits, VERDICT_ACCEPTED, create_runner, run_program  # noqa: E402


LIMITS = Limits(time_limit_ms=2000, memory_limit_mb=256)


def run_source(language: str, source: str, input_data: str = "40 2\n") -> None:
    with tempfile.TemporaryDirectory(prefix="judger-ci-smoke-") as tmp:
        workdir = Path(tmp)
        runner = create_runner(language, workdir, source, LIMITS)
        if runner is None:
            raise AssertionError(f"runner is missing for language: {language}")

        compiled = runner.compile()
        if compiled.command is None:
            raise AssertionError(f"{language} compilation failed: {compiled.output}")

        result = run_program(
            compiled.command,
            input_data,
            cwd=workdir,
            limits=LIMITS,
            env=runner.run_env(),
            address_space_limit_bytes=runner.address_space_limit_bytes(),
        )
        if result.verdict != VERDICT_ACCEPTED:
            raise AssertionError(f"{language} smoke returned {result.verdict}: {result.stderr}")
        if result.stdout.strip() != "42":
            raise AssertionError(f"{language} smoke returned unexpected output: {result.stdout!r}")


def main() -> None:
    run_source("python", "a, b = map(int, input().split())\nprint(a + b)\n")
    run_source(
        "cpp17",
        """
#include <iostream>

int main() {
    long long a, b;
    std::cin >> a >> b;
    std::cout << a + b << '\\n';
    return 0;
}
""",
    )

    if shutil.which("node"):
        run_source(
            "javascript",
            "const fs = require('fs');\n"
            "const [a, b] = fs.readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);\n"
            "console.log(a + b);\n",
        )


if __name__ == "__main__":
    main()

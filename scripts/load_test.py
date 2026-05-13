#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from itertools import cycle
from typing import Any


LANGUAGES = [
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
]

SOURCE_BY_LANGUAGE = {
    "python": "import sys\nprint(sum(map(int, sys.stdin.read().split())))\n",
    "java": """
import java.io.*;
import java.util.*;

public class Main {
  public static void main(String[] args) throws Exception {
    Scanner scanner = new Scanner(System.in);
    long a = scanner.nextLong();
    long b = scanner.nextLong();
    System.out.println(a + b);
  }
}
""".strip()
    + "\n",
    "javascript": """
const fs = require('fs');
const [a, b] = fs.readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
console.log(a + b);
""".strip()
    + "\n",
    "typescript": """
declare function require(name: string): any;
const fs = require('fs');
const [a, b] = fs.readFileSync(0, 'utf8').trim().split(/\\s+/).map(Number);
console.log(a + b);
""".strip()
    + "\n",
    "c11": """
#include <stdio.h>

int main(void) {
  long long a, b;
  if (scanf("%lld %lld", &a, &b) != 2) return 0;
  printf("%lld\\n", a + b);
  return 0;
}
""".strip()
    + "\n",
    "cpp17": """
#include <bits/stdc++.h>
using namespace std;

int main() {
  long long a, b;
  cin >> a >> b;
  cout << a + b << '\\n';
  return 0;
}
""".strip()
    + "\n",
    "cpp20": """
#include <bits/stdc++.h>
using namespace std;

int main() {
  long long a, b;
  cin >> a >> b;
  cout << a + b << '\\n';
  return 0;
}
""".strip()
    + "\n",
    "csharp": """
using System;

public class MainClass {
  public static void Main() {
    var parts = Console.In.ReadToEnd().Split((char[])null, StringSplitOptions.RemoveEmptyEntries);
    Console.WriteLine(long.Parse(parts[0]) + long.Parse(parts[1]));
  }
}
""".strip()
    + "\n",
    "object_pascal": """
program Main;
var
  a, b: Int64;
begin
  ReadLn(a, b);
  WriteLn(a + b);
end.
""".strip()
    + "\n",
    "fortran": """
program main
  implicit none
  integer(kind=8) :: a, b
  read (*,*) a, b
  print *, a + b
end program main
""".strip()
    + "\n",
    "go": """
package main

import "fmt"

func main() {
  var a, b int64
  fmt.Scan(&a, &b)
  fmt.Println(a + b)
}
""".strip()
    + "\n",
    "lua": """
local input = io.read("*a")
local values = {}
for value in string.gmatch(input, "%S+") do
  table.insert(values, tonumber(value))
end
print(values[1] + values[2])
""".strip()
    + "\n",
}


class ApiError(RuntimeError):
    def __init__(self, method: str, path: str, status: int, body: str):
        super().__init__(f"{method} {path} failed with HTTP {status}: {body}")
        self.status = status
        self.body = body


class ApiClient:
    def __init__(self, base_url: str, token: str | None = None, timeout: float = 15):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def with_token(self, token: str) -> "ApiClient":
        return ApiClient(self.base_url, token=token, timeout=self.timeout)

    def request(self, method: str, path: str, data: dict[str, Any] | None = None) -> Any:
        body = None if data is None else json.dumps(data).encode("utf-8")
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(f"{self.base_url}{path}", data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = response.read().decode("utf-8")
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as error:
            payload = error.read().decode("utf-8", errors="replace")
            raise ApiError(method, path, error.code, payload) from error
        except urllib.error.URLError as error:
            raise RuntimeError(f"{method} {path} failed: {error}") from error

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(self, path: str, data: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, data)

    def put(self, path: str, data: dict[str, Any]) -> Any:
        return self.request("PUT", path, data)


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return default if value is None or value == "" else int(value)


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    return default if value is None or value == "" else float(value)


def parse_languages(value: str) -> list[str]:
    if value.strip().lower() in {"", "all"}:
        return LANGUAGES
    selected = [item.strip() for item in value.split(",") if item.strip()]
    unknown = sorted(set(selected) - set(LANGUAGES))
    if unknown:
        raise SystemExit(f"Unknown language(s): {', '.join(unknown)}")
    return selected


def login(api: ApiClient, username: str, password: str) -> str:
    payload = api.post("/api/auth/login", {"username": username, "password": password})
    return str(payload["access_token"])


def create_user(admin: ApiClient, username: str, password: str, display_name: str) -> dict[str, Any]:
    return admin.post(
        "/api/users",
        {
            "username": username,
            "password": password,
            "display_name": display_name,
            "role": "participant",
        },
    )


def create_contest(admin: ApiClient, prefix: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return admin.post(
        "/api/contests",
        {
            "title": f"{prefix} Load Contest",
            "description": "Generated by scripts/load_test.py",
            "status": "running",
            "is_public": False,
            "registration_enabled": False,
            "registration_requires_approval": True,
            "time_mode": "fixed",
            "participation_mode": "individual",
            "starts_at": (now - timedelta(minutes=10)).isoformat(),
            "ends_at": (now + timedelta(days=1)).isoformat(),
            "individual_duration_minutes": None,
        },
    )


def create_task(admin: ApiClient, contest_id: int, prefix: str) -> dict[str, Any]:
    return admin.post(
        "/api/tasks",
        {
            "contest_id": contest_id,
            "title": f"{prefix} A + B",
            "statement": "Read two integers and print their sum.",
            "input_format": "Two integers.",
            "output_format": "One integer.",
            "samples": [{"input": "2 3\n", "output": "5\n"}],
            "time_limit_ms": 3000,
            "memory_limit_mb": 256,
            "points": 100,
            "partial_scoring": False,
            "tests": [
                {"input_data": "2 3\n", "output_data": "5\n", "is_sample": True},
                {"input_data": "40 2\n", "output_data": "42\n", "is_sample": False},
                {"input_data": "-10 7\n", "output_data": "-3\n", "is_sample": False},
            ],
        },
    )


def create_fixture(api: ApiClient, args: argparse.Namespace) -> tuple[ApiClient, dict[str, Any], dict[str, Any], list[ApiClient]]:
    admin_token = login(api, args.admin_username, args.admin_password)
    admin = api.with_token(admin_token)
    prefix = args.prefix or f"load_{int(time.time())}"
    password = args.participant_password

    participants = []
    participant_clients = []
    for index in range(args.participants):
        username = f"{prefix}_user_{index + 1}"
        user = create_user(admin, username, password, f"Load User {index + 1}")
        participants.append(user)
        participant_clients.append(api.with_token(login(api, username, password)))

    contest = create_contest(admin, prefix)
    admin.put(f"/api/contests/{contest['id']}/participants", {"user_ids": [user["id"] for user in participants]})
    task = create_task(admin, contest["id"], prefix)
    print(
        f"fixture prefix={prefix} contest_id={contest['id']} task_id={task['id']} "
        f"participants={len(participants)} languages={','.join(args.languages)}",
        flush=True,
    )
    return admin, contest, task, participant_clients


def submit_solution(client: ApiClient, contest_id: int, task_id: int, language: str, wrong: bool) -> dict[str, Any]:
    source = SOURCE_BY_LANGUAGE[language]
    if wrong:
        source = wrong_source(language)
    return client.post(
        f"/api/contests/{contest_id}/tasks/{task_id}/submissions",
        {"language": language, "source_code": source},
    )


def wrong_source(language: str) -> str:
    if language == "python":
        return "print(0)\n"
    if language == "java":
        return "public class Main { public static void main(String[] args) { System.out.println(0); } }\n"
    if language in {"javascript", "typescript"}:
        return "console.log(0);\n"
    if language == "c11":
        return "#include <stdio.h>\nint main(void) { puts(\"0\"); return 0; }\n"
    if language in {"cpp17", "cpp20"}:
        return "#include <iostream>\nint main() { std::cout << 0 << '\\n'; }\n"
    if language == "csharp":
        return "using System; public class MainClass { public static void Main() { Console.WriteLine(0); } }\n"
    if language == "object_pascal":
        return "program Main; begin WriteLn(0); end.\n"
    if language == "fortran":
        return "program main\nprint *, 0\nend program main\n"
    if language == "go":
        return "package main\nimport \"fmt\"\nfunc main() { fmt.Println(0) }\n"
    if language == "lua":
        return "print(0)\n"
    raise ValueError(language)


def verdict_summary(submissions: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for submission in submissions:
        counts[str(submission.get("verdict", "unknown"))] = counts.get(str(submission.get("verdict", "unknown")), 0) + 1
    return ", ".join(f"{key}={value}" for key, value in sorted(counts.items())) or "none"


def run_load(admin: ApiClient, contest: dict[str, Any], task: dict[str, Any], participants: list[ApiClient], args: argparse.Namespace) -> None:
    contest_id = int(contest["id"])
    task_id = int(task["id"])
    participant_cycle = cycle(participants)
    submitted_ids: list[int] = []
    total = 0
    started = time.monotonic()

    for iteration in range(1, args.iterations + 1 if args.iterations else sys.maxsize):
        for language in args.languages:
            total += 1
            wrong = bool(args.wrong_every and total % args.wrong_every == 0)
            try:
                submission = submit_solution(next(participant_cycle), contest_id, task_id, language, wrong=wrong)
                submitted_ids.append(int(submission["id"]))
                print(
                    f"submitted #{submission['id']} language={language} verdict={submission['verdict']} "
                    f"wrong={str(wrong).lower()}",
                    flush=True,
                )
            except Exception as error:
                print(f"submit failed language={language}: {error}", file=sys.stderr, flush=True)

            if args.rejudge_every and submitted_ids and total % args.rejudge_every == 0:
                target_id = random.choice(submitted_ids)
                try:
                    rejudged = admin.post(f"/api/admin/submissions/{target_id}/rejudge")
                    print(f"rejudged #{target_id} verdict={rejudged['verdict']}", flush=True)
                except Exception as error:
                    print(f"rejudge failed submission={target_id}: {error}", file=sys.stderr, flush=True)

            try:
                live = admin.get(f"/api/contests/{contest_id}/live-snapshot")
                scoreboard = admin.get(f"/api/contests/{contest_id}/scoreboard")
                submissions = admin.get(f"/api/submissions?contest_id={contest_id}")
                elapsed = max(0.001, time.monotonic() - started)
                print(
                    f"status iteration={iteration} total={total} rate={total / elapsed:.2f}/s "
                    f"live_submissions={len(live['submissions'])} scoreboard_rows={len(scoreboard)} "
                    f"verdicts=[{verdict_summary(submissions)}]",
                    flush=True,
                )
            except Exception as error:
                print(f"poll failed: {error}", file=sys.stderr, flush=True)

            if args.interval > 0:
                time.sleep(args.interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Continuously submit solutions and poll Simple Contester endpoints.")
    parser.add_argument("--api-base", default=os.getenv("API_BASE", "http://localhost:8001"))
    parser.add_argument("--admin-username", default=os.getenv("ADMIN_USERNAME", "admin"))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", "admin"))
    parser.add_argument("--prefix", default=os.getenv("LOAD_PREFIX", ""))
    parser.add_argument("--participant-password", default=os.getenv("LOAD_PARTICIPANT_PASSWORD", "load123"))
    parser.add_argument("--participants", type=int, default=env_int("LOAD_PARTICIPANTS", 3))
    parser.add_argument("--interval", type=float, default=env_float("LOAD_INTERVAL_SECONDS", 1.0))
    parser.add_argument("--iterations", type=int, default=env_int("LOAD_ITERATIONS", 0), help="0 means run forever.")
    parser.add_argument("--languages", default=os.getenv("LOAD_LANGUAGES", "all"), help="Comma-separated values or 'all'.")
    parser.add_argument("--wrong-every", type=int, default=env_int("LOAD_WRONG_EVERY", 0), help="Submit a wrong answer every N submissions.")
    parser.add_argument("--rejudge-every", type=int, default=env_int("LOAD_REJUDGE_EVERY", 0), help="Admin rejudges a random previous submission every N submissions.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.languages = parse_languages(args.languages)
    if args.participants <= 0:
        raise SystemExit("--participants must be positive")

    api = ApiClient(args.api_base)
    admin, contest, task, participants = create_fixture(api, args)
    try:
        run_load(admin, contest, task, participants, args)
    except KeyboardInterrupt:
        print("\nstopped", flush=True)


if __name__ == "__main__":
    main()

# Backend integration tests

Run the in-process backend integration tests from the repository root:

```bash
python3 -m pip install -r backend/requirements.txt
python3 -m pytest
```

The tests use a temporary SQLite database at `tests/.simple_contester_pytest.db` and do not require Docker.

Optional Docker Compose/API smoke check:

```bash
docker compose up -d --build mariadb backend
SIMPLE_CONTESTER_API_BASE=http://localhost:8001 python3 -m pytest -m smoke
```

The smoke test logs in through the running API using `admin` / `admin` by default. Override with
`SIMPLE_CONTESTER_ADMIN_USERNAME` and `SIMPLE_CONTESTER_ADMIN_PASSWORD` when needed.

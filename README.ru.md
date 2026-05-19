# Simple Contester

Закрытая платформа для локальных олимпиад и тренировочных соревнований.

## Стек

- Backend: FastAPI + SQLAlchemy
- Frontend: React + Vite, основной runtime для разработки - Bun, fallback - Node.js/npm
- База данных: MariaDB
- Judger: Python worker, можно запускать несколько экземпляров через Docker Compose

## Требования

- Git
- Docker Engine с Compose plugin
- 4 GB+ свободной RAM для полного стека и toolchain-ов judger
- Опционально для запуска скриптов вне Docker: Python 3.12+, Bun, Node.js/npm

## Быстрый старт

```bash
git clone https://github.com/xDololow/Simple_contester.git
cd Simple_contester
cp .env.example .env
docker compose up --build
```

Адреса по умолчанию:

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8001/docs
- MariaDB на хосте: `3307`, внутри контейнера `3306`

Администратор по умолчанию:

```text
username: admin
password: admin
```

После первого входа поменяйте пароль администратора и секреты в `.env`.

Полезные команды после первого запуска:

```bash
# Запустить стек в фоне.
docker compose up -d

# Смотреть логи API и judger.
docker compose logs -f backend judger

# Остановить контейнеры, сохранив данные MariaDB.
docker compose down
```

## Основные возможности

- Вход по `username` и паролю без email.
- Роли `admin` и `participant`.
- Ручное создание пользователей и массовый импорт из CSV, JSON, YAML.
- Команды с поиском участников при добавлении.
- Библиотека задач отдельно от соревнований.
- Привязка одной задачи к нескольким соревнованиям.
- Markdown-условия задач и предпросмотр.
- Импорт тестов ZIP-архивом с файлами `*.in` и `*.out`.
- Соревнования с фиксированным окном или индивидуальным временем участника.
- Открытые соревнования, ручные списки доступа и заявки на участие.
- Посылки на Python, Java, JavaScript, TypeScript, C, C++, C#, Object Pascal, Fortran, Go и Lua.
- Live-обновления посылок и scoreboard через SSE с fallback на polling.
- Админский просмотр посылок, результатов по тестам, статуса judger-воркеров и статистики сайта.
- Перепроверка посылки администратором после изменения тестов.
- Docker-запуск backend, frontend, MariaDB и judger.

## Настройки окружения

Основные параметры лежат в `.env.example`.

| Переменная | Значение по умолчанию | Назначение |
| --- | --- | --- |
| `MARIADB_DATABASE` | `simple_contester` | Имя базы MariaDB. |
| `MARIADB_USER` | `contestant` | Пользователь базы приложения. |
| `MARIADB_PASSWORD` | `contestant` | Пароль пользователя базы. |
| `MARIADB_ROOT_PASSWORD` | `root` | Root-пароль MariaDB. |
| `BACKEND_PORT` | `8001` | Порт backend на хосте. |
| `FRONTEND_PORT` | `5173` | Порт frontend на хосте. |
| `VITE_API_BASE` | `http://localhost:8001` | URL API для frontend. |
| `CORS_ORIGINS` | `http://localhost:5173` | Разрешенные browser origins для API. |
| `SITE_TIMEZONE` | `Asia/Krasnoyarsk` | IANA timezone для отображения и выбора времени в интерфейсе. |
| `DATABASE_URL` | `mysql+pymysql://contestant:contestant@mariadb:3306/simple_contester` | URL базы для backend и judger внутри Docker. |
| `JWT_SECRET` | `change-me-in-production` | Секрет подписи JWT. Обязательно заменить. |
| `ADMIN_USERNAME` | `admin` | Bootstrap-логин администратора. |
| `ADMIN_PASSWORD` | `admin` | Bootstrap-пароль администратора. |
| `JUDGER_SANDBOX_MODE` | `subprocess` | Режим запуска решений: `subprocess` или `docker`. |
| `SUBMISSION_LEASE_SECONDS` | `60` | Время аренды посылки judger-воркером. |
| `SUBMISSION_MAX_ATTEMPTS` | `3` | Максимум повторных захватов зависшей посылки. |

`SITE_TIMEZONE` должен быть валидной IANA-зоной, например `Asia/Krasnoyarsk`, `Europe/Moscow`, `UTC`. Backend отдает ее через `GET /api/config`, а frontend использует ее для всех `datetime-local` форм, чтобы выбранное время не зависело от timezone браузера.

## Production-style запуск

Для закрытой установки на сервере используйте override:

```bash
cp .env.example .env
$EDITOR .env
bash scripts/check-env.sh .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml config
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

Минимальный checklist:

- Заменить `JWT_SECRET`, `ADMIN_PASSWORD`, `MARIADB_PASSWORD`, `MARIADB_ROOT_PASSWORD`.
- Настроить `VITE_API_BASE`, `CORS_ORIGINS` и `SITE_TIMEZONE`.
- Не публиковать MariaDB наружу.
- Держать `.env`, SQL dumps, TLS private keys и backup-архивы вне git.
- Проверить backup/restore на отдельном проекте Docker Compose.

## Reverse Proxy

В production TLS обычно завершается на Caddy, nginx, Traefik или другом proxy. При использовании `docker-compose.prod.yml` backend слушает только `127.0.0.1:${BACKEND_PORT}`.

### Caddy

```caddyfile
contest.example.com {
  encode zstd gzip

  reverse_proxy /api/* 127.0.0.1:8001
  reverse_proxy /docs* 127.0.0.1:8001
  reverse_proxy /openapi.json 127.0.0.1:8001

  reverse_proxy 127.0.0.1:5173
}
```

### Nginx

```nginx
server {
  listen 80;
  server_name contest.example.com;
  client_max_body_size 100m;

  location /api/ {
    proxy_pass http://127.0.0.1:8001;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 3600s;
  }

  location /docs {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location = /openapi.json {
    proxy_pass http://127.0.0.1:8001;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location / {
    proxy_pass http://127.0.0.1:5173;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

`proxy_buffering off` нужен для быстрых live-обновлений через Server-Sent Events.

## Judger

По умолчанию стартует один `judger` в subprocess-режиме:

```bash
docker compose up --scale judger=3
```

Так можно поднять несколько worker-экземпляров. Посылки атомарно захватываются через MariaDB lease, поэтому два judger не должны обрабатывать одну посылку одновременно.

Для более жесткой изоляции есть профиль Docker sandbox:

```bash
docker compose --profile docker-sandbox up --build judger-docker-sandbox
```

Перед включением проверьте `DOCKER_SOCK_GID` и ограничения в `.env`.

## Backup и Restore

```bash
bash scripts/backup.sh
bash scripts/restore.sh backups/<file>.sql.gz
```

Перед restore остановите `backend`, `judger` и `judger-docker-sandbox`, чтобы воркеры не писали результаты в базу во время восстановления.

## Demo

```bash
bash scripts/demo.sh
```

Скрипт создает demo-пользователей, соревнование, задачу, тесты и отправки через API. Для обработки очереди должен быть запущен judger.

## Нагрузочное тестирование

`scripts/load_test.py` создает закрытое соревнование, несколько участников, задачу A+B и затем постоянно отправляет решения, одновременно опрашивая live snapshot, scoreboard и историю посылок. По умолчанию скрипт проходит по всем поддерживаемым языкам: Python, Java, JavaScript, TypeScript, C11, C++17, C++20, C#, Object Pascal, Fortran, Go и Lua.

Сначала поднимите стек и один или несколько judger:

```bash
docker compose up --build -d
docker compose up -d --scale judger=3
```

Бесконечный запуск до `Ctrl+C`:

```bash
python3 scripts/load_test.py
```

Короткая проверка по всем языкам:

```bash
python3 scripts/load_test.py --iterations 1 --interval 0
```

Полезные настройки:

```bash
API_BASE=http://localhost:8001 \
ADMIN_USERNAME=admin \
ADMIN_PASSWORD=admin \
LOAD_PARTICIPANTS=5 \
LOAD_LANGUAGES=python,cpp17,go \
LOAD_WRONG_EVERY=10 \
LOAD_REJUDGE_EVERY=25 \
python3 scripts/load_test.py
```

`LOAD_WRONG_EVERY` специально отправляет неверное решение каждые N посылок.
`LOAD_REJUDGE_EVERY` периодически отправляет случайную старую посылку на перепроверку через admin API.

## Проверки

```bash
bash scripts/ci.sh
```

Локально также полезны:

```bash
python -m pytest
cd frontend && bun run build
```

Чтобы отдельно сравнить системы оценивания IOI/ECOO/ICPC/AtCoder на одинаковых посылках:

```bash
docker build -f backend/Dockerfile -t simple-contester-backend-ci:local .
docker run --rm \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/workspace/backend:/workspace/judger \
  -v "$PWD:/workspace" \
  -w /workspace \
  --entrypoint python \
  simple-contester-backend-ci:local \
  -m pytest tests/test_scoring_modes_comparison.py -q
```

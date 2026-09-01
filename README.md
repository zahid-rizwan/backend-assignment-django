# Artikate Checkout API

A Django + DRF service for checking assets in and out, tracking employee usage, generating overdue reports, and flagging overdue items via Celery.

## Stack

- Django 5.0.6
- Django REST Framework 3.15.2
- PostgreSQL 15 (via Docker) / SQLite for local default
- Redis 7
- Celery 5.4.0

## Local setup

1. Copy the environment file:
   ```bash
   cp .env.example .env
   ```
2. Start the stack:
   ```bash
   docker compose up --build
   ```
3. Run database migrations and seed demo data:
   ```bash
   docker compose exec web python manage.py migrate
   docker compose exec web python manage.py seed_demo_data
   ```
4. Open the API at:
   ```text
   http://localhost:8000/api/v1/
   ```

## Primary endpoints

- `GET /api/v1/health/` - app and database health check
- `POST /api/v1/checkouts/` - checkout an asset
- `POST /api/v1/checkouts/<id>/return/` - return an asset
- `GET /api/v1/employees/<employee_code>/summary/` - per-employee summary
- `GET /api/v1/reports/overdue/` - overdue report

## Celery task

The overdue notifier task is registered as:

```python
flag_overdue_checkouts
```

It is designed to be idempotent by using the unique constraint on `OverdueNotice` rows. Re-running the task will skip duplicate notices for the same checkout/day instead of crashing.

## Notes and assumptions

- The default project configuration uses SQLite locally when `USE_POSTGRES=False`.
- Docker Compose runs PostgreSQL and Redis for the full-stack environment.
- The project uses a simple DRF response envelope with `success`, `data`, `error`, and `meta` keys.
- Employee auth is out of scope for this assignment; the API relies on the Django test client and direct session-based authentication in the local tests.

## Known gaps / follow-ups

- The repo does not include a browser-based screen recording in this headless environment.
- The project is intentionally kept lean and assignment-focused; production hardening such as OAuth, RBAC, and deployment ingress is outside the current scope.

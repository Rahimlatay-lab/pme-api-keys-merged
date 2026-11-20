# PME API Keys

FastAPI + Postgres (SQLAlchemy async / asyncpg) + Redis.

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env        # fill DATABASE_URL, REDIS_URL, KEY_PEPPER, SESSION_SECRET
python migrate.py           # creates tables (idempotent)
uvicorn main:app --reload   # dashboard: /   docs: /docs
```

## Tests (real Postgres + Redis, throwaway DB only)
```bash
createdb pme_test
TEST_DATABASE_URL=postgresql+asyncpg://user:pw@localhost/pme_test pytest
```

## How it works
| Piece | File |
|---|---|
| Key generation, HMAC-SHA256 + pepper, scrypt passwords, session tokens | `security.py` |
| Bearer auth -> per-minute limit -> daily limit (Redis) -> usage record (Postgres) | `ratelimit.py` |
| Account + key + usage endpoints, protected `/v1/ping` | `main.py` |
| API key schema | `migrations/001_security.sql` |
| Department employee permissions | `migrations/002_department_access.sql` |
| JSON logs, API keys masked | `logging_config.py` |

Add a protected endpoint: `@app.get("/v1/x")` + `auth=Depends(enforce_limits)`.

The department migration seeds `sales_employee`, `production_employee`,
`stocks_employee`, `supply_employee`, `finance_employee`, and `manager`.
Use `employee_has_department_permission(employee_id, department_code, permission)`
with the employee identity resolved from the authenticated user; do not trust an
employee ID supplied directly by a client. The migration defines the SQL access
rules but does not add department dashboard, resume, or file-deployment routes.

## Production notes
- `KEY_PEPPER` and `SESSION_SECRET`: random, >= 32 chars, never in git. Changing the pepper invalidates all keys.
- Serve over HTTPS only.
- Behind a proxy, start uvicorn with `--proxy-headers` so the login limiter sees real client IPs.
- Run `python migrate.py` on each deploy.

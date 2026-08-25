# Append-Only Activity Log

`activity_logs` is separate from the existing `audit_log` (HTTP request log) and
`security_audit` (auth events) tables. It answers a different question: **what
changed in the data**, independent of which endpoint or code path caused it.

## How it's populated

Rows are written exclusively by **database triggers**, not by application code,
on every `INSERT` / `UPDATE` / `DELETE` against `predictions` and `alerts`
(see migration `0001_activity_logs_append_only_audit_trail`). This means a bug
in `main.py`/`database.py` — or a future maintainer forgetting to call an
"audit this" helper — cannot cause a change to go unrecorded, because the
recording doesn't route through application code at all.

Each row captures: `table_name`, `operation` (`INSERT`/`UPDATE`/`DELETE`),
`row_id`, `old_data` / `new_data` (JSON snapshots), `changed_by`, `changed_at`.

## Immutability guarantee

**PostgreSQL (production path):**
```sql
REVOKE UPDATE, DELETE ON activity_logs FROM PUBLIC;
```
This is enforced by the database itself. Even the application's own DB role
cannot alter or erase a row — including via a SQL injection bug, a compromised
backend process, or an admin-level bug in the FastAPI app. Only a Postgres
superuser (outside the app entirely) could bypass this. `INSERT`s from the
trigger function still work because the trigger runs as `SECURITY INVOKER`
under the function owner's `INSERT` grant, which is never revoked.

**SQLite (local dev only):** SQLite has no GRANT/REVOKE/role model, so this
guarantee does not exist there — the SQLite trigger set exists purely for
local development parity (so `/audit/immutable-log` returns something while
developing without Postgres). Do not treat the SQLite path as tamper-proof.

## User attribution

Postgres triggers read `current_setting('app.username', true)`, set per
request via `SET LOCAL` (wired up alongside Row-Level Security). SQLite
triggers instead read a single-row `_session_context` table that
`database.set_session_context()` updates from `auth.get_current_user()` on
every authenticated request — this is a global, not per-connection, value,
so it can race under concurrent local requests. Acceptable for dev; not used
in production.

## Endpoint

`GET /audit/immutable-log` — admin only. Filters: `username`, `operation`,
`table_name`, `start_date`, `end_date`, `limit`, `offset`.

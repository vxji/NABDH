# Row-Level Security Policies

Enabled only on PostgreSQL (`config.DATABASE_URL` set to a `postgresql://`
DSN). SQLite has no RLS equivalent — it remains local-dev-only, unenforced.
Defined in migration `0004_equipment_and_row_level_security`.

## How session identity reaches Postgres

Every FastAPI request resolves a user in `auth.get_current_user()`, which
calls `database.set_session_context(username, role)`. On PostgreSQL, this
just stores the values in context vars — they're actually applied to the
database session in `database._connect()`, on **every new connection
checkout**, via:

```sql
SELECT set_config('app.username', :u, false);
SELECT set_config('app.user_role', :r, false);
```

`is_local=false` makes these session-level (persist for the life of that
connection, not just one transaction) — appropriate here since each
`_connect()` call already represents one logical unit of work. Policies read
them back with `current_setting('app.username', true)` /
`current_setting('app.user_role', true)` — the `true` second argument means
"return NULL instead of raising if unset," which matters: **if the session
variable is ever unset, none of the three role policies match, and the
query returns zero rows.** Unset defaults to deny, not allow.

## Equipment model

NABDH didn't have an "equipment" concept before this migration — the 10
sensors are a single implicit machine. `equipment` is new; `predictions` and
`alerts` gained a nullable `equipment_id` FK, backfilled to a single
"Default Unit" (id=1) row so every pre-existing row stays visible to
everyone exactly as before. `user_equipment_scope` (username, equipment_id)
is how an admin grants a viewer access to a specific piece of equipment —
via `POST /admin/user-equipment-scope`.

## Policies

### `predictions`, `alerts`

Row-Level Security enabled **and forced** (`FORCE ROW LEVEL SECURITY` — see
gotcha below). Three permissive policies (Postgres OR's them together):

| Policy | Role | Rule |
|---|---|---|
| `{table}_admin_policy` | admin | `current_setting('app.user_role', true) = 'admin'` — sees everything |
| `{table}_operator_policy` | operator | `current_setting('app.user_role', true) = 'operator'` — sees everything (matches today's app behavior; operators aren't equipment-scoped) |
| `{table}_viewer_policy` | viewer | `role = 'viewer' AND (equipment_id IS NULL OR equipment_id = 1 OR equipment_id IN (SELECT equipment_id FROM user_equipment_scope WHERE username = current_setting('app.username', true)))` |

`equipment_id = 1` (the seeded "Default Unit", guaranteed to exist) and
`equipment_id IS NULL` are both treated as globally visible — that's what
keeps single-equipment deployments unaffected. Equipment id > 1 requires an
explicit `user_equipment_scope` grant.

> **Corrected in migration `0006`.** The original `0004` policy only
> exempted `NULL`, on the assumption pre-existing rows would be left
> unscoped. But `0004`'s own backfill set every row's `equipment_id` to `1`
> (never `NULL`), and `insert_prediction()`'s default does the same for new
> rows — so in practice no row was ever actually `NULL`, and every existing
> viewer account would have seen **zero** rows on Postgres until explicitly
> granted equipment 1. `0006` fixes this by also exempting `equipment_id = 1`.
> Caught while building §5 (equipment timeline), before this was ever
> deployed to a real Postgres instance.

### `audit_log`

No equipment concept applies here — it's the HTTP request log, already
admin-only in the application layer (`main.py`'s `/audit` endpoints). RLS
here is defense-in-depth: only one policy exists, `audit_log_admin_policy`,
requiring `app.user_role = 'admin'`. A viewer or operator session — even one
that reached this table via a hypothetical application bug bypassing
`require_admin` — sees zero rows, because no policy exists for those roles
and RLS defaults to deny when nothing matches.

## The "table owner bypasses RLS" gotcha

PostgreSQL's RLS **does not apply to the table owner** by default, even with
RLS enabled — only `FORCE ROW LEVEL SECURITY` makes it apply to the owner
too. This migration always applies `FORCE` for exactly that reason. But it
still doesn't protect against a session connecting as an actual Postgres
**superuser**, which always bypasses RLS regardless of `FORCE`. In
production, the application's DB role must be a non-superuser role — ideally
one that isn't the table owner either, for defense-in-depth, though `FORCE`
alone is sufficient for the common case of the app connecting as the
table-owning role.

## Cost of this design

`_connect()` re-applies both `set_config()` calls on **every** connection
checkout, not once per request — a request that makes several DB calls
(e.g. `/predict`, which inserts a prediction, alert, prescriptive record,
and RCA record) repeats them several times. Each is a trivial no-I/O
statement; this trades a small amount of redundant work for not having to
introduce a request-scoped single connection/transaction, which would have
been a much larger change to `database.py`'s "open one connection per call"
architecture used throughout the rest of this file.

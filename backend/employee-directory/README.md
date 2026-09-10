# employee-directory

FastAPI behind Mangum, deployed as a single Lambda behind a Function URL
(local) / CloudFront (`https://<cloudfront-domain>/api/employee-directory/*`
on AWS). See `app/main.py` for the entry point and `function.py` for the
Lambda handler.

## Database migrations

There is no migration framework (no Alembic). `schema.sql` and `seed.sql`
are applied by the app itself, idempotently, on the first database call in
a given Lambda container (`app/db_init.py`, called from
`app/repositories/db.py`). This is a deliberate workshop-scope choice: the
VDI terminal cannot reach Aurora directly (it lives in a VPC only the
Lambda can talk to), so a manual `psql -f schema.sql` step would work
locally and silently fail to run against AWS. Self-migration behaves
identically in both environments, and a fresh clone just works.

In a production setting, schema migration would be a CI/CD step run
against the database directly (e.g. via a bastion or a migration job with
network access to the VPC), not something the application does at startup.

**Heads-up for adding columns/constraints to an existing table** (not
needed as of slice 3): `CREATE TABLE IF NOT EXISTS` is a silent no-op on
any database that's already run it — Aurora has every table already.
Editing a `CREATE TABLE` statement in place does nothing there. Growing
an existing table needs its own idempotent statement alongside the
create, e.g. `ALTER TABLE employees ADD COLUMN IF NOT EXISTS ... ;` —
otherwise the symptom is "the column isn't there but the code looks
fine," discovered the hard way instead of read here first.

## Aurora cold start (connect_timeout)

`infra/rds.tf` sets `min_capacity = 0.0` on the Aurora Serverless v2
cluster, so it scales to zero after a few idle minutes. The next
connection has to wait for it to resume from a cold ACU, which can exceed
a typical 10-15s connect timeout — confirmed empirically against the real
cluster (first request after idle timed out at 15s, a retry moments later
succeeded in ~1.4s). `app/repositories/db.py` uses `connect_timeout=30` to
tolerate this. Local Postgres is never scaled down, so this only ever
matters against Aurora.

## Why not-found responses are 410 Gone, not 404

The provided `infra/cloudfront.tf` has a `custom_error_response` mapping
404 -> 200 `/index.html`, for SPA deep-link fallback. CloudFront applies
this **distribution-wide**, not scoped to a cache behavior — classic
CloudFront has no per-behavior error override — so it would also rewrite
any genuine 404 our own code returned (e.g. `GET /work-locations/{id}`
for an id that doesn't exist) into a 200 HTML page before it reaches the
browser. Only 404 is mapped this way, not 403 (checked `cloudfront.tf`
directly), so slice 2's permission denials are unaffected and can use 403
normally.

Per workshop guidance, 404 is reserved by the platform, so this backend's
domain-level not-found responses use **410 Gone** instead — mapped in
exactly one place, the `NotFoundError` exception handler in `app/main.py`,
not repeated per controller. Being honest about what this is: 410
semantically means "this existed and was removed," and 404 ("this never
existed") would be the *correct* HTTP code for e.g. an unknown work
location id. We are not claiming 410 is the better choice — we're
following a platform constraint someone else put in place, using the
nearest code CloudFront leaves available, not modifying `infra/` to
reclaim 404 for our own use.

This only covers our *own* raised exceptions. FastAPI's own 404 for a
genuinely unmatched route (a typo'd path, wrong method) is a framework
response we don't raise and can't redirect to 410 the same way — that one
still gets rewritten by CloudFront into a 200 HTML page. The frontend's
`apiFetch` (`frontend/src/services/api.js`) is a backstop for exactly that
case: it detects a 200 with non-JSON content-type (this API never
legitimately returns HTML) and restores it to a 404. It no longer needs
to do anything for our domain not-found responses, since 410 passes
through CloudFront untouched.

Test coverage: `tests/test_work_locations.py`'s not-found test asserts
410 directly against the FastAPI app, and — unlike the old 404 version of
this test — that status code is expected to survive unchanged through
CloudFront too, since only 404 is rewritten; verified manually against
the deployed CloudFront URL. The remaining untestable-by-automation gap is
narrower now: FastAPI's native unmatched-route 404 still can't be proven
through CloudFront by an automated test, only by `curl`/manual check.

## Known issues in the provided tooling (this VDI)

Three latent bugs in `bin/` scripts, all diagnosed via logs (or, for the
third, by bypassing the suspected component) before touching anything,
all worth recording so they aren't rediscovered from scratch:

1. **`start-dev.sh`'s pip install used the wrong Python.** Line ~342 ran
   bare `pip install --target=<service_dir> -r requirements.txt`. On this
   VDI, `pip` on `PATH` resolves to a Python 3.14 install
   (`~/.local/lib/python3.14/site-packages/pip`), while `python3` — and the
   Lambda runtime Terraform declares (`runtime = "python3.13"`) — is 3.13.
   `pydantic_core` and `psycopg` both ship compiled extensions; a
   cp314-tagged build can't load under python3.13, and the failure mode is
   an opaque `ImportModuleError: No module named 'pydantic_core._pydantic_core'`
   at Lambda cold start, which looks like a code bug, not a tooling one.
   Fixed by pinning the install to `/usr/bin/python3.13 -m pip` (line 342).
2. **`start-dev.sh`'s "is the React dev server already running" check
   false-positives.** After killing a stale `npm run dev` process (e.g. to
   pick up a fresh `.env.local`), the very next `start-dev.sh` run
   frequently reports "React dev server is already running on port 3000"
   and skips starting a new one — nothing is actually listening. Root
   cause not fully isolated (a port-release timing race is the likely
   culprit), so it's recorded rather than patched. Workaround: check
   `lsof -iTCP:3000 -sTCP:LISTEN` yourself and start `npm run dev` by hand
   if the script's claim doesn't match reality.
3. **`bin/proxy-server.js` silently dropped the `Authorization` header.**
   Its header forwarding is a hardcoded whitelist (`accept`,
   `content-type`, `user-agent`, `host`) written in slice 0, before auth
   existed. Every unauthenticated endpoint hid this completely; the first
   authenticated call (`GET /me` with a real, valid token) failed with a
   401 that had nothing to do with the token — confirmed by bypassing the
   proxy and hitting the raw LocalStack Lambda URL directly with the same
   token, which worked. Fixed by forwarding `Authorization` when present.
   Never reproduces on AWS: CloudFront's `AllViewerExceptHostHeader`
   origin request policy already forwards every viewer header except
   `Host`.

## infra/ confirmed off-limits: two settled constraints

Both of these were originally flagged as open questions pending a decision
on whether `infra/` could be touched. Confirmed with the workshop:
`infra/` is off-limits entirely. Both are now closed, not pending:

- **bcrypt cost factor is 10, not 12.** The provided Lambda is 128MB
  (`infra/lambda.tf`'s `memory_size = 128`), and AWS Lambda scales CPU
  allocation with memory — at 128MB there's very little CPU, and bcrypt is
  deliberately CPU-heavy. Cost 12 measured ~4.5s per login on this
  hardware (confirmed via CloudWatch — every sample was a warm
  invocation, not a cold start; it was really bcrypt). Asked whether
  `memory_size` could be raised instead; `infra/` cannot be modified, so
  the cost factor was lowered instead: still ~1.1s on this hardware, and
  still at the [OWASP-recommended floor](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)
  for bcrypt. `app/config.py`'s `BCRYPT_ROUNDS` is the one place this
  lives (moved out of `auth_service` in slice 4, once employee creation
  and the login dummy-hash both needed the same constant); raising it
  back to 12 (or higher) is a one-line change if more Lambda memory ever
  becomes available.
- **The JWT signing secret is a documented placeholder, permanently.**
  `infra/locals.tf`'s `env_vars` map has no slot for a custom secret, and
  since `infra/` cannot be modified, there is no way to inject a real one
  via Terraform. `app/services/auth_service.py` falls back to a hardcoded
  constant (`dev-placeholder-not-a-real-secret`) for both local and AWS.
  This is a workshop-scope shortcut, not a real secret — never commit an
  actual production secret here. In production this would come from
  Secrets Manager or Parameter Store, injected as a real environment
  variable, not hardcoded.

## Slice 4: employees

### The org chart is derived, not editable

`manager_id` is never accepted as input on any request — not on create,
not on update, not from an Admin, not even for a CEO submitting for
themselves. It's computed by one helper (`employee_repository.compute_manager_id` —
promoted from `_compute_manager_id` in slice 5, once `team_repository`
needed the same derivation),
called from every write path that touches `team_id` or `role`:

```
role = CEO      -> manager_id = NULL       (and team_id = NULL)
role = MANAGER  -> manager_id = the CEO's id
anyone else     -> manager_id = their team's manager,
                    or the CEO's id if they have no team (ADMIN included)
```

This makes a `manager_id` cycle structurally impossible — every chain is
at most IC -> manager -> CEO — so the `manager_id != id` self-reference
check that used to guard against a cycle is now unreachable and kept only
as an internal `assert`, not a user-facing guard. Team assignment doesn't
exist yet (slice 5), so every employee created this slice has `team_id =
NULL` and therefore `manager_id` = the CEO's id, including newly-created
MANAGERs — a MANAGER with no team yet is a legal, transient state, not a
bug, on the way to slice 5's "CEO creates the team around them" flow.

### Contact info, this slice: first name, last name, and phone

`PUT /employees/{id}` is self-only and covers exactly three fields:
`first_name`, `last_name`, and `phone`. Nothing else about "your own
info" is editable through the API yet (email, work location, expertise,
availability) — this is a stated scope decision for this slice, not
something quietly missed.

`phone` strips whitespace and stores an empty-after-strip value as `NULL`,
not `""` — the same invisible-value bug fixed for names elsewhere, but in
a column that can actually express "not set" (`first_name`/`last_name`
can't: they're `NOT NULL`, so `min_length=1` is their fix instead).

### Why an email change doesn't force a logout

Considered and decided against. An email change is an administrative
correction (nobody edits their own email this slice — email isn't in
`EmployeeUpdate` at all), not a security event; the actual security
action for a compromised or departing account is deactivation, and that
is already immediate — `current_user` re-reads the employee row from the
database on every request rather than trusting the JWT payload, so a
deactivated employee's existing token stops working on their very next
call, not just at natural expiry. Forcing every other token holder to
re-authenticate over an email edit would be a bigger user-facing cost
than the risk it addresses.

### Four new invariants

1. **Exactly one active CEO.** `CREATE UNIQUE INDEX IF NOT EXISTS
   idx_employees_one_active_ceo ON employees (role) WHERE role = 'CEO'
   AND is_active` (`schema.sql`). Checked Aurora for pre-existing active
   CEOs before adding it, same precaution as the case-insensitive email
   index in slice 3 — seed data has exactly one, so this was clean, but
   confirmed rather than assumed.
2. **At least one active Admin must always remain.** Enforced in
   `soft_delete_employee` before a deactivation is allowed — covers both
   the last Admin deactivating themselves and one Admin deactivating the
   only other one. Without it: nobody could create employees, nobody
   could reactivate anyone, and the CEO has no employee-management
   powers to fix it — permanently stuck, no recovery path through the
   API. Since `DELETE /employees/{id}` requires the ADMIN role, the only
   reachable case in practice is "the last Admin deletes themselves" —
   once the count is down to one, that one Admin is necessarily the only
   caller who could still be authorized to try.
3. **The CEO can never be deactivated.** Checked first, before the
   Admin-count and active-reports guards, in `soft_delete_employee`.
4. **A manager with active direct reports can't be deactivated.** Same
   `EXISTS` shape as the department delete guard (slice 3). Otherwise a
   manager could be deactivated leaving reports pointing at an inactive
   person — a broken org chart, visible in the demo.

A fifth guard is written but dormant this slice, same treatment as the
department delete guard: rejecting a role change away from MANAGER for
someone who currently manages an active team. No teams exist yet, so it
can't fire; the positive case is a slice-5 test.

### `/work-locations` and `/expertise` now require authentication

Both were slice 1 code, written before auth existed in slice 2, and
nothing went back to add the `current_user` dependency the other GETs
use — until now. The data was never sensitive; the inconsistency (a
stranger with the CloudFront URL could curl either one with no token)
was the problem. `/expertise` wasn't explicitly named when this was
scoped, but the identical gap and identical reasoning applied, so it was
fixed alongside `/work-locations` rather than left inconsistent on a
technicality.

### Email is normalized on create, not just at login

`POST /employees` strips and lowercases the submitted email before
storing it, the same normalization `login` already applied to its input.
The `LOWER(email)` unique index (slice 3) stops two rows differing only
by case; it does nothing to stop *one* row being stored mixed-case in
the first place, which the case-insensitive lookup could then still fail
to find. A duplicate email, including a case variant, is a 409.

## Slice 5: teams

Added retroactively — this section didn't get written when the slice
landed; caught while keeping the README current for slice 6 (see the
"OpenAPI schema as Figma input" note below on why that now matters more
than it used to).

### MANAGER is conferred by team assignment, and by nothing else

`POST`/`PUT /employees` restrict `role` to `Literal[EMPLOYEE, ADMIN]` —
MANAGER and CEO are both rejected at the schema layer. There is no
direct promotion and no direct demotion: MANAGER only ever comes from
`POST /teams` (nominating someone) or `PUT /teams` (replacing a team's
manager), and only ever goes away via `PUT /teams` replacement,
`DELETE /teams`, or deactivating the manager through `DELETE /employees`.
A MANAGER can no longer exist without an active team.

### Team creation, replacement, and deletion are atomic

`POST /teams` inserts the team and promotes the nominee (role, team_id,
manager_id) in one transaction. `PUT /teams` manager replacement demotes
the outgoing manager (who stays on the team as an IC), promotes the
incoming one, and bulk-repoints everyone else's `manager_id` — one
`UPDATE`, not a per-row loop — all in one transaction. `DELETE /teams`
deactivates the team and pools its manager (`team_id` NULL, role
EMPLOYEE, `manager_id` the CEO) together.

These are this codebase's first genuinely multi-statement, atomic
writes. `app/repositories/db.py` connects with `autocommit=True`, so
every write before slice 5 was a single statement, atomic on its own by
construction. `with conn.transaction():` (psycopg3) is what makes a
multi-statement operation atomic under autocommit — it issues a real
`BEGIN`, then commits on a clean exit or rolls back on any exception.
Whether a rolled-back transaction leaves the module-level cached
connection usable for the *next* request on the same warm Lambda
container was proved, not assumed:
`tests/test_db_connection.py::test_connection_survives_a_rolled_back_transaction`
forces a real `UniqueViolation` inside a transaction block and confirms
an ordinary statement succeeds immediately after, on the same connection
object — `db.py`'s reset-on-failure only covers a failed `get_connection()`
call itself, never a mid-request rollback.

### The manager permission model

On `PUT /employees/{id}`, a manager may edit `first_name`/`last_name`/
`phone`/`work_location_id`/`project_availability`/`expertise_id` for
members of their own team (scope checked against the target's `team_id`
as fetched before any change — not before-or-after, since the CEO's
`team_id` is NULL and an after-the-fact check would let a manager claim
the CEO onto their team and then edit them), and release a member
(`team_id` -> `null` only; placing a real value is Admin-only). Every
field family is authorized independently and rejects (403) a caller who
isn't allowed to touch it, rather than silently dropping the field.
`team_id` is separately LOCKED for anyone who currently manages an
active team, for every caller including Admin — the only path that
moves a team's manager is `PUT /teams`. Authorization is always checked
before this lock: a caller with no standing to touch `team_id` at all
gets 403 for that reason, never a 409 revealing a business invariant
that isn't theirs to trip.

### Four new invariants

1. At most one active team per manager
   (`idx_teams_one_active_manager`), backing the app-level
   "already manages another active team" check with a real constraint —
   closing the TOCTOU race the app-level check alone can't.
2. The CEO can't be nominated or renominated as a manager (would leave
   the app with zero CEOs — the single-CEO index only prevents two).
3. Admin can't be nominated either without losing Admin access
   invisibly (slice 4's "at least one Admin" guard only fires on
   deactivation, never on a role change).
4. Deactivating a manager whose team has no other active members also
   deactivates that now-manager-less team, in the same transaction —
   `teams.manager_id` is `NOT NULL` and can't point at an inactive
   person.

## Slice 6: skills

### Get-or-create, and the insert race

Attaching a skill by name looks it up case-insensitively
(`idx_skills_name_lower`, additive to the existing plain
`UNIQUE(name)` — same relationship the email-lowercase index has to
`employees.email UNIQUE`) and creates it if missing. Two Lambda
containers attaching "Python" at the same instant can both miss the
initial `SELECT` and both attempt the `INSERT`; one wins, the other's
`UniqueViolation` is caught and re-`SELECT`s to attach to whatever row
is there now. The caller never sees an error for this — it's expected
concurrent behaviour, not an edge case, and
`tests/test_skills.py::test_get_or_create_skill_handles_the_insert_race`
exercises the exact code path (a real `UniqueViolation`, forced
deterministically rather than relying on true concurrency, which this
codebase's single shared connection can't reproduce in-process).

**Known, accepted limitation**: "JavaScript" and "JS" are different
rows and are never merged automatically — only exact case-insensitive
matches reuse a row. Already decided; this is the first slice where
it's actually reachable rather than theoretical.

### Idempotency, stated explicitly

`POST /employees/{id}/skills` attaching a skill the employee already
has is 200, not 409 — a POST that lands on the same end state succeeds
quietly. `DELETE /employees/{id}/skills/{skill_id}` detaching a skill
they don't have is also a clean 200 — `employee_skills` is a join row,
not an entity, so there's no "not found" to report. Both endpoints
return the employee's current skill list, not a single row or an empty
body — consistent with this codebase's existing DELETE convention
(departments/employees/teams all return post-change state), which
matters more here than textbook REST purity (`204 No Content` would
have been the strict answer). `POST` returns 201 whenever a *new*
`employee_skills` link is created — regardless of whether the skill
lookup row itself was also new — and 200 only when nothing changed.

### Attaching to an inactive employee is rejected; detaching isn't

`POST /employees/{id}/skills` on a deactivated employee is 409
(`DependentsExistError`, message says "employee is inactive"
explicitly). Attaching creates a *new* row, unlike editing an existing
field, so there's a real case for "don't create new associations
against an inactive record" here. `DELETE` has no such guard — removing
data from an inactive record is never harmful.

**Recorded, not fixed**: `PUT /employees/{id}` has no equivalent
`is_active` guard at all — an Admin (or a manager, or self) can
currently edit any field on a deactivated employee's row with nothing
blocking it. A real inconsistency with the rule above, deliberately left
open as a design question for a later slice (should an inactive
employee be frozen except for reactivation, the way departments are?) —
not slice 6 scope.

### Frontend

Per-employee skills display deferred; the Skills lookup page and
underlying API are complete and testable via the endpoints directly.

### OpenAPI schema as later Figma input

Starting this slice, every endpoint's `responses={...}` is kept accurate
for every status code it can actually return, and schema field names
stay consistent across resources — not just a nicety anymore. The React
pages built so far (WorkLocations, Departments, Employees, Teams,
Skills) are scaffolding proving the authenticated fetch path through
CloudFront each slice, not the real frontend; the real one is built
later in Figma from a metaprompt derived from the finished backend +
this README, so `/openapi.json` becomes literal input to that process,
not just documentation for us.

## Slice 7: projects

### Two operations, not one endpoint with two moods

`POST /employees/{id}/projects` is get-or-create by name (mirroring
skills) and **never** sets `description` — attaching to an existing
project must not let the joiner rewrite its description for everyone.
`POST /projects` is a *separate*, explicit-create operation, open to any
authenticated user, that 409s on a name collision (checked
case-insensitively via `idx_projects_name_lower`, same relationship to
the plain `UNIQUE(name)` as the skills/email lowercase indexes) rather
than reusing the existing row. That distinction is load-bearing for
`PUT /projects/{id}` being Admin-only: if `POST` instead merged into an
existing row, anyone could route around the Admin gate by re-POSTing a
new description under the same name. `name` is also editable via `PUT`,
same collision check.

No `is_active` on `projects`, and none is planned — projects have no
lifecycle of their own here. State lives on
`employee_projects.completed_at`: "this project is over" is already
expressible as "everyone assigned has a completion date." Adding a
lifecycle column would invent one and immediately demand new guards,
for no capability this app actually needs.

### Completion is self-reported and manager-correctable, not verified

Self may set (and clear — reopen) their own `completed_at` via
`PUT /employees/{id}/projects/{project_id}`, same as a manager can for
their team, or Admin for anyone. Nobody's write is authoritative over
anyone else's — if the question ever comes up, that's the honest answer
for whether someone could inflate their own numbers: yes, the same way
they could misreport any self-service field in this app, and a
manager/Admin can correct it after the fact, not before.

### `GET /teams/{id}/achievements?month=YYYY-MM`

Completed projects (`completed_at IS NOT NULL` — an assignment with no
completion date is in-progress, not an achievement) for a team, `month`
optional (omitted = all-time, which is what answers "total done ever,"
not just "what shipped this month"). Two attribution caveats stack, both
following from there being no historical team-assignment record:

- Credited to whoever is on the team **now**, not who was on it when the
  project was completed.
- Active employees only — someone who's since left takes their
  completions out of their former team's total.

Neither is fixable without a real assignment-history table, which is a
bigger change than this slice's scope.

## Demo credentials (bootstrap accounts)

`seed.sql` stores password hashes, not plaintext, so the plaintext has to
be written down somewhere for the demo to actually be usable. All three
accounts share one password for simplicity. These are **demo accounts
only**, not real credentials:

| Role  | Email | Password | Notes |
| ----- | ----- | -------- | ----- |
| CEO   | `ceo@example.com` | `Password123!` | |
| Admin | `admin@example.com` | `Password123!` | |
| Employee | `deactivated@example.com` | `Password123!` | `is_active = false` on purpose — login always fails. Exists so "deactivated account can't log in" is testable against a real seeded row on both local and AWS, not just a local-only test fixture. |

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

## Demo credentials (bootstrap accounts)

`seed.sql` stores password hashes, not plaintext, so the plaintext has to
be written down somewhere for the demo to actually be usable. Both
accounts share one password for simplicity. These are **demo accounts
only**, not real credentials:

| Role  | Email | Password |
| ----- | ----- | -------- |
| CEO   | `ceo@example.com` | `Password123!` |
| Admin | `admin@example.com` | `Password123!` |

-- Idempotent seed data, applied by app/db_init.py right after schema.sql.

INSERT INTO work_locations (name)
VALUES ('Remote')
ON CONFLICT (name) DO NOTHING;

INSERT INTO expertise (name)
VALUES ('Backend'), ('Frontend'), ('DevOps'), ('Support')
ON CONFLICT (name) DO NOTHING;

-- Bootstrap CEO + Admin accounts (demo credentials, see README). Foreign
-- keys are resolved by natural key (name/email), never hardcoded ids —
-- work_locations/expertise/employees all use GENERATED ALWAYS AS IDENTITY,
-- so their ids depend on seeding order and are not something to guess at.
-- Password for all three demo accounts, plaintext for the demo: Password123!
-- Hash generated with bcrypt, cost factor 10 — the same constant
-- app/services/auth_service.py uses for its dummy-hash timing defence, so
-- a real check and the dummy check always cost the same. (Was cost 12;
-- see README — reduced because the provided 128MB Lambda makes 12 take
-- ~4.5s per login and infra/ cannot be changed to give it more CPU.)
-- ON CONFLICT DO UPDATE, not DO NOTHING: these are documented demo
-- credentials expected to match seed.sql exactly, so self-migration
-- reconciles the hash if it's ever regenerated (as it was here, cost
-- 12 -> 10) rather than leaving already-seeded rows stale.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'CEO', 'ceo@example.com',
    '$2b$10$XtdljLQ5odsc6g1Ozytt8ulF2cPucApoJhiDg9pXoC1udAYrp9UC2', 'CEO',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL,
    NULL,
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- Depends on the CEO row above already existing (manager_id looks it up
-- by email), so this must run after it.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'Admin', 'admin@example.com',
    '$2b$10$XtdljLQ5odsc6g1Ozytt8ulF2cPucApoJhiDg9pXoC1udAYrp9UC2', 'ADMIN',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL,
    (SELECT id FROM employees WHERE email = 'ceo@example.com'),
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- A permanently-seeded deactivated demo account, so "deactivated account
-- can't log in" is testable against both local and AWS (smoke_test.py
-- check 13) without the test/smoke-test having to write anything itself.
-- Same demo password as the others.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'Deactivated', 'deactivated@example.com',
    '$2b$10$XtdljLQ5odsc6g1Ozytt8ulF2cPucApoJhiDg9pXoC1udAYrp9UC2', 'EMPLOYEE',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL,
    (SELECT id FROM employees WHERE email = 'ceo@example.com'),
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, false
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

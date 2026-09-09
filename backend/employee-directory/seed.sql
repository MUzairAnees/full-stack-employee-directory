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
-- Password for both, plaintext for the demo: Password123!
-- Hash generated with bcrypt, cost factor 12 — the same constant
-- app/services/auth_service.py uses for its dummy-hash timing defence, so
-- a real check and the dummy check always cost the same.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'CEO', 'ceo@example.com',
    '$2b$12$7rkQfo212ZvTmki.W1vj8OTLe4d6wBougeF.87FplZnyUiTYhp.du', 'CEO',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL,
    NULL,
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO NOTHING;

-- Depends on the CEO row above already existing (manager_id looks it up
-- by email), so this must run after it.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'Admin', 'admin@example.com',
    '$2b$12$7rkQfo212ZvTmki.W1vj8OTLe4d6wBougeF.87FplZnyUiTYhp.du', 'ADMIN',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL,
    (SELECT id FROM employees WHERE email = 'ceo@example.com'),
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO NOTHING;

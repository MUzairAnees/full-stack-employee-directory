-- Idempotent seed data, applied by app/db_init.py right after schema.sql.
--
-- Final-pass rewrite: a directory that looks like a real company rather
-- than three bootstrap accounts. 24 employees total — Aurora and local
-- ALREADY hold three (ceo@example.com, admin@example.com,
-- deactivated@example.com); this file REUSES those exact emails rather
-- than creating new people, so per-row ON CONFLICT resolves them to the
-- same three rows, not three plus three more. Seeding a second CEO here
-- would hit idx_employees_one_active_ceo and fail the migration at cold
-- start against Aurora — checked local Postgres for exactly one active
-- CEO before writing a second CEO row anywhere in this file (there is
-- exactly one, the existing one, and this file never inserts another).
--
-- Order matters, and it's the same shape as every FK-dependency comment
-- already in this file: lookups (work_locations/expertise/skills/
-- projects) -> employees (team_id and manager_id both NULL at this
-- point — teams don't exist yet, and the org-chart derivation hasn't
-- run) -> departments -> teams (each needs its manager to already exist
-- as an employee row, which is why employees come first) -> UPDATE
-- team_id (assigns members to the teams that now exist) -> UPDATE
-- manager_id (the org-chart derivation, which READS team_id — must run
-- last, in ONE CASE statement covering every employee, not a per-row
-- value at insert time).
--
-- Every foreign key is wired by natural key (name/email), never a
-- hardcoded id: work_locations/expertise/skills/projects/departments/
-- teams/employees all use GENERATED ALWAYS AS IDENTITY, so ids depend on
-- insertion order and are not something to guess at, here or anywhere
-- else in this app.

-- ---------------------------------------------------------------------
-- Lookups
-- ---------------------------------------------------------------------

INSERT INTO work_locations (name)
VALUES ('Remote'), ('New York HQ'), ('London Office'), ('Austin Office')
ON CONFLICT (name) DO NOTHING;

INSERT INTO expertise (name)
VALUES ('Backend'), ('Frontend'), ('DevOps'), ('Support'), ('Sales'), ('Data')
ON CONFLICT (name) DO NOTHING;

INSERT INTO skills (name)
VALUES
    ('Python'), ('JavaScript'), ('SQL'), ('Kubernetes'), ('AWS'), ('React'),
    ('Figma'), ('Salesforce'), ('Excel'), ('Public Speaking'),
    ('Project Management'), ('Communication')
ON CONFLICT (name) DO NOTHING;

INSERT INTO projects (name, description)
VALUES
    ('Website Redesign', 'Public-facing site refresh'),
    ('Mobile App Launch', 'First release of the companion mobile app'),
    ('Q3 Marketing Campaign', 'Cross-channel push for the quarter'),
    ('Data Warehouse Migration', 'Move reporting off the legacy warehouse'),
    ('Customer Portal', 'Self-service portal for external customers'),
    ('Onboarding Automation', 'Automating new-hire paperwork and provisioning'),
    ('Security Audit', 'Annual third-party security review')
ON CONFLICT (name) DO NOTHING;

-- ---------------------------------------------------------------------
-- Employees — three existing (password reconciled, nothing else touched
-- so a name edited during a demo isn't stomped on the next cold start),
-- twenty-one new. team_id and manager_id are NULL for every new row
-- here; both are set below, after teams exist.
--
-- Password reconciliation: ON CONFLICT (email) DO UPDATE SET
-- password_hash ONLY, on every one of these 24 rows, not split between
-- "existing" and "new" — one rule instead of a rule-plus-exception. On
-- first run this is identical to DO NOTHING for the 21 new rows (there's
-- nothing to reconcile yet); on every later cold start it re-asserts
-- the seeded password, so the README's documented passwords are ALWAYS
-- the database's passwords, not a value that can drift after a demo
-- where a name got edited.
--
-- Passwords: four demo accounts get DISTINCT passwords (see
-- scripts/gen_demo_hashes.py, committed so these are reproducible) —
-- ceo@example.com, admin@example.com, and one manager/IC pair on the
-- SAME team (backend.manager@example.com / ava.patel@example.com), so
-- logging in as each demonstrates both "manager edits own team member"
-- and the 403 on a different team, not just the success case. The other
-- twenty share one password (nobody logs in as them). rounds=10 is the
-- constant app.config.BCRYPT_ROUNDS uses — NOT the higher cost that was
-- tried and reverted in slice 2 (~4s per login on this Lambda's 128MB).
-- ---------------------------------------------------------------------

INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'CEO', 'ceo@example.com',
    '$2b$10$.7wS5Zxrj9puwxtabBmSr.Q8m6uQyeoEhsNTvJqUxt54Zk7tS1CG2', 'CEO',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL, NULL,
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'Admin', 'admin@example.com',
    '$2b$10$4qyJaeN4pR6E8DMUfKe8WOAdgTURf9M7h4rYGPIyfGMMAlSJDniC6', 'ADMIN',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL, NULL,
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, true
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- Deliberately left team_id NULL and untouched otherwise: this is the
-- one place an INACTIVE employee sits in the unassigned pool. It
-- satisfies "at least one employee with team_id NULL" on paper, but an
-- inactive row is hidden from the default list — see hana.suzuki below
-- for the ACTIVE pooled employee that actually makes the release/place
-- workflow visible in a demo.
INSERT INTO employees (
    first_name, last_name, email, password_hash, role,
    work_location_id, team_id, manager_id, expertise_id,
    project_availability, is_active
)
VALUES (
    'Demo', 'Deactivated', 'deactivated@example.com',
    '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE',
    (SELECT id FROM work_locations WHERE name = 'Remote'),
    NULL, NULL,
    (SELECT id FROM expertise WHERE name = 'Backend'),
    true, false
)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- Seven managers, one per team created below. role = 'MANAGER' is set
-- directly here — the app-level restriction (POST/PUT /employees reject
-- role MANAGER, see slice 5) is a Pydantic schema constraint on the API
-- surface, not a database rule, and doesn't apply to this file. team_id
-- is set in the UPDATE below, once each manager's team exists.

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Olivia', 'Bennett', 'hr.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'New York HQ'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Support'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Marcus', 'Chen', 'backend.manager@example.com', '$2b$10$2BGJbFaEUlUGtvY/FB6nWu.CWff.8VCZOqj.rqB2834BPTy.9AAE2', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Backend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Priya', 'Sharma', 'frontend.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'Austin Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Frontend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Daniel', 'Kim', 'devops.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'DevOps'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Grace', 'Okafor', 'support.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'London Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Support'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Liam', 'Torres', 'sales.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'New York HQ'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Sales'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Sofia', 'Rossi', 'data.manager@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'MANAGER', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Data'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- Fourteen individual contributors: thirteen distributed unevenly across
-- the seven teams below (HR 1, Backend 3, Frontend 3, DevOps 2, Support
-- 1, Sales 2, Data 1), one (hana.suzuki) left permanently unassigned —
-- the ACTIVE unassigned-pool example. Three have project_availability =
-- false (noah.kim, zoe.ahmed, leo.dubois), spread across different
-- teams, so ?available= actually filters rather than trivially matching
-- everyone.

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Ethan', 'Walsh', 'ethan.walsh@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'New York HQ'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Support'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Ava', 'Patel', 'ava.patel@example.com', '$2b$10$7VGiNPgJVv4AngYJKrQCw.8zn2atzONp57d9p2Igz6gLITJeOreAu', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Backend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Noah', 'Kim', 'noah.kim@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Austin Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Backend'), false, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Mia', 'Fischer', 'mia.fischer@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Backend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Lucas', 'Novak', 'lucas.novak@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'London Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Frontend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Zoe', 'Ahmed', 'zoe.ahmed@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Frontend'), false, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Ben', 'Nakamura', 'ben.nakamura@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Austin Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Frontend'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Ivy', 'Larsson', 'ivy.larsson@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'DevOps'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Oscar', 'Mendes', 'oscar.mendes@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'London Office'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'DevOps'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Ruby', 'Costa', 'ruby.costa@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Support'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Leo', 'Dubois', 'leo.dubois@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'New York HQ'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Sales'), false, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Nina', 'Petrov', 'nina.petrov@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Sales'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Felix', 'Adebayo', 'felix.adebayo@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'New York HQ'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Data'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- The active unassigned-pool employee — team_id is never set for this
-- one, on purpose (see the comment on the block above).
INSERT INTO employees (first_name, last_name, email, password_hash, role, work_location_id, team_id, manager_id, expertise_id, project_availability, is_active)
VALUES ('Hana', 'Suzuki', 'hana.suzuki@example.com', '$2b$10$dH08N/uDGoi5ybt3HZ52DO.3Fyvy7Duc0IaX2g1BC0GS3TLw41i8W', 'EMPLOYEE', (SELECT id FROM work_locations WHERE name = 'Remote'), NULL, NULL, (SELECT id FROM expertise WHERE name = 'Data'), true, true)
ON CONFLICT (email) DO UPDATE SET password_hash = EXCLUDED.password_hash;

-- ---------------------------------------------------------------------
-- Departments and teams
-- ---------------------------------------------------------------------

INSERT INTO departments (name) VALUES ('HR'), ('IT'), ('Marketing')
ON CONFLICT (name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('HR', (SELECT id FROM departments WHERE name = 'HR'), (SELECT id FROM employees WHERE email = 'hr.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('Backend', (SELECT id FROM departments WHERE name = 'IT'), (SELECT id FROM employees WHERE email = 'backend.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('Frontend', (SELECT id FROM departments WHERE name = 'IT'), (SELECT id FROM employees WHERE email = 'frontend.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('DevOps', (SELECT id FROM departments WHERE name = 'IT'), (SELECT id FROM employees WHERE email = 'devops.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('Support', (SELECT id FROM departments WHERE name = 'IT'), (SELECT id FROM employees WHERE email = 'support.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('Sales', (SELECT id FROM departments WHERE name = 'Marketing'), (SELECT id FROM employees WHERE email = 'sales.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

INSERT INTO teams (name, department_id, manager_id)
VALUES ('Data', (SELECT id FROM departments WHERE name = 'Marketing'), (SELECT id FROM employees WHERE email = 'data.manager@example.com'))
ON CONFLICT (department_id, name) DO NOTHING;

-- ---------------------------------------------------------------------
-- team_id — managers onto their own team, ICs onto their assigned team.
-- hana.suzuki is deliberately absent from this list (stays NULL).
-- Must run before the manager_id derivation below, which reads it.
-- ---------------------------------------------------------------------

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'HR')
WHERE email IN ('hr.manager@example.com', 'ethan.walsh@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'Backend')
WHERE email IN ('backend.manager@example.com', 'ava.patel@example.com', 'noah.kim@example.com', 'mia.fischer@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'Frontend')
WHERE email IN ('frontend.manager@example.com', 'lucas.novak@example.com', 'zoe.ahmed@example.com', 'ben.nakamura@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'DevOps')
WHERE email IN ('devops.manager@example.com', 'ivy.larsson@example.com', 'oscar.mendes@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'Support')
WHERE email IN ('support.manager@example.com', 'ruby.costa@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'Sales')
WHERE email IN ('sales.manager@example.com', 'leo.dubois@example.com', 'nina.petrov@example.com');

UPDATE employees SET team_id = (SELECT id FROM teams WHERE name = 'Data')
WHERE email IN ('data.manager@example.com', 'felix.adebayo@example.com');

-- ---------------------------------------------------------------------
-- manager_id — the org-chart derivation, ONE CASE statement over every
-- employee, matching employee_repository.compute_manager_id exactly:
--     CEO      -> NULL
--     MANAGER  -> the CEO's id
--     everyone -> their team's manager, or the CEO if they have no team
-- Runs last because it reads team_id, set immediately above.
-- ---------------------------------------------------------------------

UPDATE employees SET manager_id = CASE
    WHEN role = 'CEO' THEN NULL
    WHEN role = 'MANAGER' THEN (SELECT id FROM employees WHERE role = 'CEO')
    WHEN team_id IS NOT NULL THEN (SELECT t.manager_id FROM teams t WHERE t.id = employees.team_id)
    ELSE (SELECT id FROM employees WHERE role = 'CEO')
END;

-- ---------------------------------------------------------------------
-- employee_skills — most active employees get 2-4 skills, overlapping
-- (Communication/Excel/SQL/Python/React/AWS/Project Management/
-- Salesforce each appear on several people) so ?skill_id= returns
-- meaningful, differently-sized subsets rather than either everyone or
-- one person. The deactivated employee is skipped — inactive, and it
-- doesn't matter.
-- ---------------------------------------------------------------------

INSERT INTO employee_skills (employee_id, skill_id)
SELECT (SELECT id FROM employees WHERE email = pairing.email), (SELECT id FROM skills WHERE name = pairing.skill)
FROM (VALUES
    ('ceo@example.com', 'Communication'),
    ('ceo@example.com', 'Project Management'),
    ('admin@example.com', 'Excel'),
    ('admin@example.com', 'Communication'),
    ('admin@example.com', 'Project Management'),
    ('hr.manager@example.com', 'Communication'),
    ('hr.manager@example.com', 'Public Speaking'),
    ('hr.manager@example.com', 'Project Management'),
    ('backend.manager@example.com', 'Python'),
    ('backend.manager@example.com', 'SQL'),
    ('backend.manager@example.com', 'AWS'),
    ('backend.manager@example.com', 'Project Management'),
    ('frontend.manager@example.com', 'JavaScript'),
    ('frontend.manager@example.com', 'React'),
    ('frontend.manager@example.com', 'Project Management'),
    ('devops.manager@example.com', 'Kubernetes'),
    ('devops.manager@example.com', 'AWS'),
    ('devops.manager@example.com', 'Python'),
    ('support.manager@example.com', 'Communication'),
    ('support.manager@example.com', 'Excel'),
    ('support.manager@example.com', 'Project Management'),
    ('sales.manager@example.com', 'Salesforce'),
    ('sales.manager@example.com', 'Public Speaking'),
    ('sales.manager@example.com', 'Communication'),
    ('data.manager@example.com', 'SQL'),
    ('data.manager@example.com', 'Excel'),
    ('data.manager@example.com', 'Project Management'),
    ('ethan.walsh@example.com', 'Communication'),
    ('ethan.walsh@example.com', 'Excel'),
    ('ava.patel@example.com', 'Python'),
    ('ava.patel@example.com', 'SQL'),
    ('ava.patel@example.com', 'AWS'),
    ('noah.kim@example.com', 'Python'),
    ('noah.kim@example.com', 'JavaScript'),
    ('noah.kim@example.com', 'Kubernetes'),
    ('mia.fischer@example.com', 'SQL'),
    ('mia.fischer@example.com', 'Python'),
    ('mia.fischer@example.com', 'React'),
    ('lucas.novak@example.com', 'JavaScript'),
    ('lucas.novak@example.com', 'React'),
    ('lucas.novak@example.com', 'Figma'),
    ('zoe.ahmed@example.com', 'JavaScript'),
    ('zoe.ahmed@example.com', 'React'),
    ('ben.nakamura@example.com', 'React'),
    ('ben.nakamura@example.com', 'Figma'),
    ('ben.nakamura@example.com', 'JavaScript'),
    ('ivy.larsson@example.com', 'Kubernetes'),
    ('ivy.larsson@example.com', 'AWS'),
    ('oscar.mendes@example.com', 'Kubernetes'),
    ('oscar.mendes@example.com', 'AWS'),
    ('oscar.mendes@example.com', 'Python'),
    ('ruby.costa@example.com', 'Communication'),
    ('ruby.costa@example.com', 'Excel'),
    ('leo.dubois@example.com', 'Salesforce'),
    ('leo.dubois@example.com', 'Communication'),
    ('nina.petrov@example.com', 'Salesforce'),
    ('nina.petrov@example.com', 'Public Speaking'),
    ('nina.petrov@example.com', 'Excel'),
    ('felix.adebayo@example.com', 'SQL'),
    ('felix.adebayo@example.com', 'Excel'),
    ('felix.adebayo@example.com', 'Project Management'),
    ('hana.suzuki@example.com', 'SQL'),
    ('hana.suzuki@example.com', 'Excel')
) AS pairing(email, skill)
ON CONFLICT (employee_id, skill_id) DO NOTHING;

-- ---------------------------------------------------------------------
-- employee_projects — completions spread across FOUR distinct months
-- AND four distinct teams (Backend/January, Frontend/March, Sales/June,
-- DevOps/September — the last one recent, so "what did this team ship
-- lately" is answerable, not just "does filtering by month work"), plus
-- three in-progress rows (completed_at NULL) so achievements correctly
-- excludes them. ava.patel's in-progress row is the one used in the
-- self-service proof (section 4) — she marks it complete herself.
-- ---------------------------------------------------------------------

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'backend.manager@example.com'),
    (SELECT id FROM projects WHERE name = 'Data Warehouse Migration'),
    '2026-01-15'
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'lucas.novak@example.com'),
    (SELECT id FROM projects WHERE name = 'Website Redesign'),
    '2026-03-20'
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'sales.manager@example.com'),
    (SELECT id FROM projects WHERE name = 'Q3 Marketing Campaign'),
    '2026-06-10'
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'devops.manager@example.com'),
    (SELECT id FROM projects WHERE name = 'Security Audit'),
    '2026-09-02'
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'hr.manager@example.com'),
    (SELECT id FROM projects WHERE name = 'Onboarding Automation'),
    NULL
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'data.manager@example.com'),
    (SELECT id FROM projects WHERE name = 'Customer Portal'),
    NULL
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

INSERT INTO employee_projects (employee_id, project_id, completed_at)
VALUES (
    (SELECT id FROM employees WHERE email = 'ava.patel@example.com'),
    (SELECT id FROM projects WHERE name = 'Mobile App Launch'),
    NULL
)
ON CONFLICT (employee_id, project_id) DO NOTHING;

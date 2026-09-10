-- Employee Directory schema.
--
-- Idempotent by design: every statement is safe to run against an
-- already-migrated database. This file is applied by app/db_init.py at
-- Lambda cold start, not by a separate migration tool — see README.md for
-- why, and for what a production setup would do instead.
--
-- Table order matters: employees references work_locations and expertise,
-- teams references departments and employees(manager_id), and
-- employees.team_id references teams. That last edge is circular
-- (employees <-> teams), so employees is created without it and it is
-- added afterwards via ALTER TABLE once teams exists.

CREATE TABLE IF NOT EXISTS work_locations (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    address_line_1  TEXT,
    city            TEXT,
    state           TEXT,
    zip             TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS expertise (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS skills (
    id   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    description TEXT
);

CREATE TABLE IF NOT EXISTS departments (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    is_active  BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS employees (
    id                   INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    first_name           TEXT NOT NULL,
    last_name            TEXT NOT NULL,
    email                TEXT NOT NULL UNIQUE,
    phone                TEXT,
    password_hash        TEXT NOT NULL,
    role                 TEXT NOT NULL,
    work_location_id     INTEGER NOT NULL REFERENCES work_locations(id),
    team_id              INTEGER,
    manager_id           INTEGER REFERENCES employees(id),
    expertise_id         INTEGER NOT NULL REFERENCES expertise(id),
    project_availability BOOLEAN NOT NULL DEFAULT true,
    is_active            BOOLEAN NOT NULL DEFAULT true,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS teams (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          TEXT NOT NULL,
    department_id INTEGER NOT NULL REFERENCES departments(id),
    manager_id    INTEGER NOT NULL REFERENCES employees(id),
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (department_id, name)
);

-- Postgres has no "ADD CONSTRAINT IF NOT EXISTS", so this is guarded by hand.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'employees_team_id_fkey'
    ) THEN
        ALTER TABLE employees
            ADD CONSTRAINT employees_team_id_fkey
            FOREIGN KEY (team_id) REFERENCES teams(id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS employee_skills (
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    skill_id    INTEGER NOT NULL REFERENCES skills(id),
    PRIMARY KEY (employee_id, skill_id)
);

CREATE TABLE IF NOT EXISTS employee_projects (
    employee_id  INTEGER NOT NULL REFERENCES employees(id),
    project_id   INTEGER NOT NULL REFERENCES projects(id),
    completed_at DATE,
    PRIMARY KEY (employee_id, project_id)
);

-- Case-insensitive email uniqueness. employees.email UNIQUE alone isn't
-- enough: Postgres TEXT equality is case-sensitive, so "a@x.com" and
-- "A@x.com" would satisfy it as two distinct rows — two logins for one
-- person, since email IS the login. Safe to add to an existing database
-- (unlike editing a CREATE TABLE, see the README) — but if this fails,
-- case-insensitive duplicates already exist and need resolving by hand,
-- not silently worked around here.
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_email_lower ON employees (LOWER(email));

-- At most one active CEO. All qualifying rows share the same role value
-- ('CEO'), so uniqueness on that column, restricted to this partial
-- condition, means at most one row can satisfy it simultaneously —
-- the standard Postgres idiom for "exactly one of X". Checked local
-- Postgres for existing active-CEO count before adding this (1, the
-- seeded row) — same precaution as idx_employees_email_lower above; a
-- failed index creation inside cold-start migration is a bad way to
-- find out there were already two.
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_one_active_ceo ON employees (role) WHERE role = 'CEO' AND is_active;

CREATE INDEX IF NOT EXISTS idx_employees_team_id ON employees(team_id);
CREATE INDEX IF NOT EXISTS idx_employees_manager_id ON employees(manager_id);
CREATE INDEX IF NOT EXISTS idx_employees_work_location_id ON employees(work_location_id);
CREATE INDEX IF NOT EXISTS idx_employees_is_active ON employees(is_active);
CREATE INDEX IF NOT EXISTS idx_employees_expertise_id ON employees(expertise_id);

-- At most one active team per manager. A slice 5 correction: this was
-- documented as already existing (it wasn't — a planning error, never
-- built). Checked local Postgres for existing violations before adding
-- it (0 teams rows, so trivially clean) — same discipline as
-- idx_employees_one_active_ceo, run anyway because the identical check
-- runs against real Aurora data at cold start and the habit is the
-- point, not the local result. Also the backstop behind
-- team_repository's "already manages another active team" app-level
-- check: that check alone has a TOCTOU race window between its SELECT
-- and the UPDATE; this index is what actually closes it, translated to
-- a clean 409 rather than a raw constraint error reaching the caller.
CREATE UNIQUE INDEX IF NOT EXISTS idx_teams_one_active_manager ON teams (manager_id) WHERE is_active;

CREATE INDEX IF NOT EXISTS idx_teams_department_id ON teams(department_id);
CREATE INDEX IF NOT EXISTS idx_teams_manager_id ON teams(manager_id);
CREATE INDEX IF NOT EXISTS idx_employee_skills_skill_id ON employee_skills(skill_id);
CREATE INDEX IF NOT EXISTS idx_employee_projects_project_id ON employee_projects(project_id);
CREATE INDEX IF NOT EXISTS idx_employee_projects_completed_at ON employee_projects(completed_at);

-- Case-insensitive skill-name uniqueness, same relationship to skills'
-- existing plain UNIQUE(name) as idx_employees_email_lower has to
-- employees.email UNIQUE: the plain constraint stops "Python"/"Python"
-- but not "Python"/"python" — two rows a get-or-create lookup by
-- LOWER(name) would otherwise conflate. Checked local Postgres for
-- existing case-duplicate skill names before adding it (0 rows in
-- skills at all — nothing writes to it yet — so trivially clean), same
-- discipline as every prior index in this file.
CREATE UNIQUE INDEX IF NOT EXISTS idx_skills_name_lower ON skills (LOWER(name));

"""Baseline assertions against the seeded directory itself (final-pass
seed rewrite: 24 employees / 7 teams / 3 departments / 12 skills /
7 projects / 4 work locations / 6 expertise values), not against data a
test creates and cleans up.

Named to sort LAST among test files (test_zz_...) — not load-bearing for
correctness (pytest runs serially against one shared connection, so file
order doesn't create a race), but it minimizes false-positive-looking
failures here that are actually leftover residue from an earlier test
failing before its own cleanup ran. If this file fails, look at what ran
before it, not necessarily at the seed.

No such exact-count assertion existed before this pass — the baseline
had been checked by hand each slice ("run this query, eyeball 3
employees"). At this data volume that's no longer safe: a two-row leak
against a baseline of 24 isn't something inspection catches, so it has
to be a test now, not a habit — same reasoning as the hard-DELETE
teardown fix in slice 5, one step earlier in the same problem.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "ceo1234"
_ADMIN_EMAIL = "admin@example.com"
_ADMIN_PASSWORD = "admin1234"


def _token_for(email: str, password: str) -> str:
    return client.post("/login", json={"email": email, "password": password}).json()["access_token"]


def _ceo_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_CEO_EMAIL, _CEO_PASSWORD)}"}


def _admin_headers() -> dict:
    return {"Authorization": f"Bearer {_token_for(_ADMIN_EMAIL, _ADMIN_PASSWORD)}"}


def test_seed_baseline_counts_are_exact() -> None:
    """EXACT, not "at least N" — a weaker assertion here would throw
    away exactly the leak detection this test exists to provide.
    """
    headers = _admin_headers()

    employees = client.get("/employees?include_inactive=true", headers=headers).json()
    teams = client.get("/teams?include_inactive=true", headers=headers).json()
    departments = client.get("/departments?include_inactive=true", headers=headers).json()
    skills = client.get("/skills", headers=headers).json()
    projects = client.get("/projects", headers=headers).json()
    work_locations = client.get("/work-locations", headers=headers).json()
    expertise = client.get("/expertise", headers=headers).json()

    assert len(employees) == 24, f"expected 24 employees, got {len(employees)}"
    assert len(teams) == 7, f"expected 7 teams, got {len(teams)}"
    assert len(departments) == 3, f"expected 3 departments, got {len(departments)}"
    assert len(skills) == 12, f"expected 12 skills, got {len(skills)}"
    assert len(projects) == 7, f"expected 7 projects, got {len(projects)}"
    assert len(work_locations) == 4, f"expected 4 work locations, got {len(work_locations)}"
    assert len(expertise) == 6, f"expected 6 expertise values, got {len(expertise)}"


def test_org_chart_invariants_hold_across_all_seeded_data() -> None:
    """The three org-chart invariants, checked against every one of the
    24 seeded employees through the real API — not a couple of spot
    examples. Catches drift between the two implementations of one rule:
    seed.sql's SQL CASE derivation and
    employee_repository.compute_manager_id, the Python helper every
    write path uses at runtime. If the seed's SQL ever diverges from
    what the app itself would derive, this is what catches it.

        role = CEO      -> manager_id IS NULL
        role = MANAGER  -> manager_id = the CEO's id
        anyone else     -> manager_id = their team's manager,
                           or the CEO's id if they have no team
    """
    headers = _ceo_headers()
    employees = client.get("/employees?include_inactive=true", headers=headers).json()
    teams_by_id = {t["id"]: t for t in client.get("/teams?include_inactive=true", headers=headers).json()}
    ceo = next(e for e in employees if e["role"] == "CEO")

    assert ceo["manager_id"] is None, ceo

    for employee in employees:
        if employee["id"] == ceo["id"]:
            continue
        if employee["role"] == "MANAGER":
            assert employee["manager_id"] == ceo["id"], employee
        elif employee["team_id"] is not None:
            expected = teams_by_id[employee["team_id"]]["manager_id"]
            assert employee["manager_id"] == expected, employee
        else:
            assert employee["manager_id"] == ceo["id"], employee

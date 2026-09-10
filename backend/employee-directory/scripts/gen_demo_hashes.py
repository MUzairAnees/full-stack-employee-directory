#!/usr/bin/env python3
"""Generates the bcrypt hashes pasted as literals into seed.sql.

seed.sql is raw SQL and cannot run bcrypt itself, so every password hash
in it has to be pre-computed and pasted in as a string. Committed so
those hashes are reproducible from a real source rather than magic
strings nobody could regenerate or verify.

Five passwords, not four: the four demo accounts used to show the four
permission perspectives during a walkthrough (CEO, Admin, one manager,
one IC — each gets a DISTINCT password), plus one shared password for
the other twenty seeded employees, who nobody logs in as directly.

rounds=10 is NOT optional — matches app.config.BCRYPT_ROUNDS exactly.
Generated at a higher cost (12 was tried in an earlier slice), logins
take ~4s on the provided 128MB Lambda, since the cost factor lives
inside the hash string itself, not in a column this app reads at
runtime. The seed is the one place that trap can quietly come back.

Usage:
    python scripts/gen_demo_hashes.py
"""

import bcrypt

from app.config import BCRYPT_ROUNDS

people = {
    "ceo@example.com": "ceo1234",
    "admin@example.com": "admin1234",
    "backend.manager@example.com": "manager1234",
    "ava.patel@example.com": "employee1234",
    "(the other twenty)": "team1234",
}

for email, password in people.items():
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()
    print(f"{email:32} {password:16} {password_hash}")

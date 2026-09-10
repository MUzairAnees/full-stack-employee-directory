"""Shared configuration constants.

One source, not duplicated per-consumer. bcrypt cost factor in
particular: after discovering that 128MB Lambda memory makes bcrypt cost
12 take ~4.5s (see README), that number must not live in two places
where one could get changed without the other.
"""

# Was 12; reduced to 10 (see README) — infra/ is off-limits (confirmed
# with the workshop), so this Lambda's memory_size=128 is fixed, and AWS
# scales CPU with memory. Cost 12 measured ~4.5s per login on that CPU
# allocation; cost 10 is still at the OWASP-recommended floor and is a
# one-line change back up if more memory ever becomes available.
#
# Four consumers: login verification, employee-create password hashing,
# the login timing defence's dummy hash, and (by hand, when regenerating
# seed.sql's bootstrap hashes) seed generation.
BCRYPT_ROUNDS = 10

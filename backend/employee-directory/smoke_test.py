#!/usr/bin/env python3
"""Smoke test for the employee-directory service: slices 0-2.

Permanent artifact, committed, grows with every slice — this is the
pre-demo checklist. Run it against either target:

    python smoke_test.py local   # http://localhost:3001, via the CORS proxy
    python smoke_test.py aws     # CloudFront website_url, via terraform output

Stdlib only, on purpose — no pip install needed to run this. Read-only
plus login: it never writes to the database itself (the one place that
might have needed a write, the deactivated-account check, uses a
permanently-seeded demo row instead — see seed.sql), so it's safe to run
repeatedly against AWS.

Both targets run the exact same assertions, so a passing local run and a
passing aws run mean the same thing. Never prints a token or a password —
see _mask().
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Same hardcoded fallback app/services/auth_service.py signs tokens with.
# Terraform injects no JWT_SECRET for either target today (checked
# infra/locals.tf), so both fall back to this same constant — which is
# what lets this script mint a validly-signed expired token without
# knowing a "real" secret. If a per-environment secret is ever added,
# check 19 (expired token) still correctly gets a 401 either way — just
# via "bad signature" rather than "expired" — so it stays a valid check,
# only slightly less precise about *why* it's a 401.
_JWT_SECRET_FALLBACK = "dev-placeholder-not-a-real-secret"

_CEO_EMAIL = "ceo@example.com"
_CEO_PASSWORD = "Password123!"
_DEACTIVATED_EMAIL = "deactivated@example.com"
_DEACTIVATED_PASSWORD = "Password123!"

_SECRETS_TO_MASK: list[str] = [_CEO_PASSWORD]  # tokens are added as minted


def _mask(text: str) -> str:
    """Redacts anything in _SECRETS_TO_MASK from text before it's printed."""
    for secret in _SECRETS_TO_MASK:
        if secret:
            text = text.replace(secret, "***")
    return text


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------


def http_request(
    method: str, url: str, body: dict | None = None, headers: dict | None = None
) -> tuple[int, dict, str]:
    """Makes one HTTP request. Returns (status, headers, raw_text_body).

    Never raises on a non-2xx status — that's a normal result for a
    smoke test to inspect, not an exception. Only raises if the request
    couldn't be made at all (DNS, connection refused, timeout).
    """
    data = None
    req_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        req_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        # 35s, not 30s: app/repositories/db.py's connect_timeout=30
        # covers Aurora resuming from a scaled-to-zero ACU; leave margin.
        with urllib.request.urlopen(request, timeout=35) as response:
            raw = response.read().decode()
            # Lowercased: HTTP headers are case-insensitive but a plain
            # dict() isn't, and dict(response.headers) keeps whatever
            # case the server sent (e.g. "Content-Type"). Every caller
            # here looks things up by lowercase key.
            return response.status, {k.lower(): v for k, v in response.headers.items()}, raw
    except urllib.error.HTTPError as err:
        raw = err.read().decode()
        return err.code, {k.lower(): v for k, v in err.headers.items()}, raw
    except urllib.error.URLError as err:
        raise RuntimeError(f"could not reach {url}: {err.reason}") from err


# ---------------------------------------------------------------------
# Target resolution
# ---------------------------------------------------------------------


def _terraform_output(key: str, target: str) -> dict | str:
    """Runs `terraform output -json <key>` against infra/, for whichever
    backend is currently initialized. Assumes you've already run
    `./bin/deploy-backend.sh <target>` in this shell (or at least once,
    for this target) — this script does not re-run `terraform init`.
    """
    infra_dir = Path(__file__).resolve().parents[2] / "infra"
    env = os.environ.copy()
    if target == "local":
        env.setdefault("AWS_ENDPOINT_URL", "http://localhost.localstack.cloud:4566")
        env.setdefault("AWS_ACCESS_KEY_ID", "test")
        env.setdefault("AWS_SECRET_ACCESS_KEY", "test")
        env.setdefault("AWS_REGION", "us-east-1")
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={infra_dir}", "output", "-json", key],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as err:
        raise RuntimeError(
            f"couldn't read terraform output '{key}' for target={target} — "
            f"is infra/ initialized against the right backend? "
            f"Run ./bin/deploy-backend.sh {target} first."
        ) from err
    return json.loads(result.stdout)


def resolve_base_url(target: str) -> str:
    """The front door: the proxy for local, CloudFront for aws — what the
    frontend actually calls.
    """
    if target == "local":
        return "http://localhost:3001"
    if target == "aws":
        url = _terraform_output("website_url", "aws")
        assert isinstance(url, str) and url, "terraform output website_url was empty"
        return url.rstrip("/")
    raise ValueError(f"unknown target {target!r}, expected 'local' or 'aws'")


def resolve_lambda_url(target: str) -> str:
    """The raw Lambda Function URL, bypassing the proxy/CloudFront
    entirely — needed for check 2, which tests Mangum's
    api_gateway_base_path stripping directly, not whatever the proxy or
    CloudFront does to the path first.
    """
    urls = _terraform_output("lambda_urls", target)
    assert isinstance(urls, dict) and len(urls) == 1, f"expected exactly one Lambda, got {urls!r}"
    return next(iter(urls.values())).rstrip("/")


# ---------------------------------------------------------------------
# JWT helpers (hand-rolled, stdlib only — see _JWT_SECRET_FALLBACK)
# ---------------------------------------------------------------------


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def mint_expired_token(employee_id: int = 1) -> str:
    """A minimal, hand-signed HS256 JWT with exp in the past."""
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64url(json.dumps({"sub": str(employee_id), "iat": 0, "exp": 1}).encode())
    signing_input = f"{header}.{payload}".encode()
    signature = hmac.new(_JWT_SECRET_FALLBACK.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{payload}.{_b64url(signature)}"


def tamper_token(token: str) -> str:
    """Reverses the signature segment. Flipping the last character isn't
    reliable — base64url's last character encodes only a few meaningful
    bits (padding fills the rest), so a naive substitution there can
    decode to the exact same signature bytes and produce a token that
    still verifies (this bit us once in tests/test_auth.py). Reversing
    guarantees different bytes.
    """
    header, payload, signature = token.split(".")
    return f"{header}.{payload}.{signature[::-1]}"


# ---------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------


class SmokeTest:
    def __init__(self, target: str) -> None:
        self.target = target
        self.base_url = resolve_base_url(target)
        self.prefix = "/api/employee-directory"
        self.results: list[tuple[str, bool, str]] = []
        self.raw_responses: list[tuple[str, str]] = []  # for the leakage scan
        self.state: dict = {}

    def api(self, path: str) -> str:
        return f"{self.base_url}{self.prefix}{path}"

    def record_response(self, label: str, raw: str) -> None:
        self.raw_responses.append((label, raw))

    def run(self, label: str, fn) -> None:
        try:
            detail = fn() or ""
            self.results.append((label, True, detail))
            suffix = f" ({detail})" if detail else ""
            print(f"PASS  {label}{suffix}")
        except AssertionError as err:
            self.results.append((label, False, str(err)))
            print(f"FAIL  {label} - {_mask(str(err))}")
        except Exception as err:  # noqa: BLE001 - a smoke test must not crash on one bad check
            self.results.append((label, False, f"{type(err).__name__}: {err}"))
            print(f"FAIL  {label} - {type(err).__name__}: {_mask(str(err))}")

    def summary(self) -> bool:
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\n{passed}/{total} passed")
        if passed != total:
            print("\nFailed checks:")
            for label, ok, detail in self.results:
                if not ok:
                    print(f"  - {label}: {_mask(detail)}")
        return passed == total


# ---------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------


def check_health(t: SmokeTest) -> None:
    status, headers, raw = http_request("GET", t.api("/health"))
    t.record_response("health", raw)
    assert status == 200, f"expected 200, got {status}: {raw}"
    assert json.loads(raw) == {"status": "ok"}, f"unexpected body: {raw}"


def check_path_prefix_both_shapes(t: SmokeTest) -> None:
    """The local-vs-AWS path divergence, tested directly against the raw
    Lambda (bypassing the proxy/CloudFront, which handle the prefix
    differently from each other): CloudFront forwards the full prefixed
    path unstripped, the local proxy strips it before forwarding. Both
    shapes must resolve the same way at the Lambda itself.
    """
    lambda_url = resolve_lambda_url(t.target)
    unprefixed_status, _, unprefixed_raw = http_request("GET", f"{lambda_url}/health")
    prefixed_status, _, prefixed_raw = http_request("GET", f"{lambda_url}{t.prefix}/health")
    t.record_response("path_prefix_unprefixed", unprefixed_raw)
    t.record_response("path_prefix_prefixed", prefixed_raw)
    assert unprefixed_status == 200, f"unprefixed path: expected 200, got {unprefixed_status}"
    assert prefixed_status == 200, f"prefixed path: expected 200, got {prefixed_status}"
    assert json.loads(unprefixed_raw) == json.loads(prefixed_raw), "both shapes must return the same body"


def check_work_locations_list(t: SmokeTest) -> str:
    status, _, raw = http_request("GET", t.api("/work-locations"))
    t.record_response("work_locations_list", raw)
    assert status == 200, f"expected 200, got {status}: {raw}"
    locations = json.loads(raw)
    remote = next((loc for loc in locations if loc["name"] == "Remote"), None)
    assert remote is not None, "no location named 'Remote' in the list"
    t.state["work_locations"] = locations
    t.state["remote"] = remote
    return f"{len(locations)} location(s)"


def check_remote_null_fields(t: SmokeTest) -> None:
    remote = t.state.get("remote")
    assert remote is not None, "check 3 did not produce a 'Remote' row"
    assert remote.get("name") == "Remote"
    for field in ("address_line_1", "city", "state", "zip"):
        assert field in remote, f"'{field}' missing from response entirely, not just null"
        assert remote[field] is None, f"'{field}' expected null, got {remote[field]!r}"


def check_work_location_get_by_id(t: SmokeTest) -> None:
    remote = t.state.get("remote")
    assert remote is not None, "check 3 did not produce a 'Remote' row"
    status, _, raw = http_request("GET", t.api(f"/work-locations/{remote['id']}"))
    t.record_response("work_location_get_by_id", raw)
    assert status == 200, f"expected 200, got {status}: {raw}"


def check_work_location_410(t: SmokeTest) -> None:
    status, headers, raw = http_request("GET", t.api("/work-locations/999999"))
    t.record_response("work_location_410", raw)
    t.state["check6"] = {"status": status, "content_type": headers.get("content-type", ""), "raw": raw}
    assert status == 410, f"expected 410, got {status}: {raw}"
    assert "application/json" in headers.get("content-type", ""), f"unexpected content-type: {headers}"
    assert "detail" in json.loads(raw), f"no 'detail' key in body: {raw}"


def check_work_location_422(t: SmokeTest) -> None:
    status, _, raw = http_request("GET", t.api("/work-locations/abc"))
    t.record_response("work_location_422", raw)
    assert status == 422, f"expected 422, got {status}: {raw}"


def check_expertise_list(t: SmokeTest) -> str:
    status, _, raw = http_request("GET", t.api("/expertise"))
    t.record_response("expertise_list", raw)
    assert status == 200, f"expected 200, got {status}: {raw}"
    rows = json.loads(raw)
    assert len(rows) == 4, f"expected 4 expertise rows, got {len(rows)}: {raw}"
    return f"{len(rows)} row(s)"


def check_public_endpoint_ignores_garbage_auth_header(t: SmokeTest) -> None:
    """A public endpoint must not require or choke on an Authorization
    header it has no use for — proving slice 2's auth machinery didn't
    accidentally leak a global auth requirement onto pre-existing routes.
    """
    status, _, raw = http_request(
        "GET", t.api("/work-locations"), headers={"Authorization": "Bearer garbage-not-a-real-token"}
    )
    t.record_response("public_with_garbage_auth", raw)
    assert status == 200, f"expected 200 even with a garbage auth header, got {status}: {raw}"


def check_login_success(t: SmokeTest) -> None:
    status, _, raw = http_request("POST", t.api("/login"), body={"email": _CEO_EMAIL, "password": _CEO_PASSWORD})
    t.record_response("login_success", raw)
    assert status == 200, f"expected 200, got {status}: {raw}"
    body = json.loads(raw)
    assert "access_token" in body, f"no access_token in response: {raw}"
    t.state["token"] = body["access_token"]
    _SECRETS_TO_MASK.append(body["access_token"])


def check_login_wrong_password(t: SmokeTest) -> None:
    status, _, raw = http_request("POST", t.api("/login"), body={"email": _CEO_EMAIL, "password": "wrong-password"})
    t.record_response("login_wrong_password", raw)
    t.state["wrong_password_body"] = raw
    assert status == 401, f"expected 401, got {status}: {raw}"


def check_login_unknown_email_identical(t: SmokeTest) -> None:
    wrong_password_body = t.state.get("wrong_password_body")
    assert wrong_password_body is not None, "check 11 (wrong password) did not run first"
    status, _, raw = http_request(
        "POST", t.api("/login"), body={"email": "nobody@example.com", "password": "wrong-password"}
    )
    t.record_response("login_unknown_email", raw)
    assert status == 401, f"expected 401, got {status}: {raw}"
    assert raw == wrong_password_body, "unknown-email body differs from wrong-password body — that difference alone reveals which emails exist"


def check_login_deactivated(t: SmokeTest) -> None:
    status, _, raw = http_request(
        "POST", t.api("/login"), body={"email": _DEACTIVATED_EMAIL, "password": _DEACTIVATED_PASSWORD}
    )
    t.record_response("login_deactivated", raw)
    assert status == 401, f"expected 401, got {status}: {raw}"


def check_login_timing(t: SmokeTest) -> str:
    """Asserted, not eyeballed: this defence silently breaks if the
    dummy-hash path is ever refactored away, and a broken version would
    still return 401 either way, indistinguishable by status code alone.

    RELATIVE tolerance, not absolute: a real login here costs one
    bcrypt.checkpw(), and how long that actually takes varies enormously
    by environment — infra/lambda.tf's memory_size=128 gives the Lambda
    very little CPU (AWS scales CPU with memory), and bcrypt is
    deliberately CPU-heavy. Cost factor 12 measured ~250ms locally but
    ~4.3-4.8s on AWS (confirmed via CloudWatch: every sample was a warm
    invocation, no Init Duration — it was really bcrypt, not a cold
    start). infra/ is off-limits (confirmed with the workshop), so the
    cost factor was reduced to 10 instead (see README and
    auth_service._BCRYPT_ROUNDS) rather than asking for more memory. A
    fixed millisecond tolerance calibrated for one baseline/cost factor
    is meaningless at another. A genuine regression (dummy-hash path
    removed) shows up as the SAME order of
    magnitude as the baseline itself (an unknown email skipping bcrypt
    entirely, ~100% relative difference) — easily caught by a relative
    threshold regardless of how slow or fast bcrypt is in this environment.
    """
    samples = 5
    tolerance_fraction = 0.30  # 30% of the average

    def timed_login(email: str) -> float:
        start = time.perf_counter()
        http_request("POST", t.api("/login"), body={"email": email, "password": "wrong-password"})
        return (time.perf_counter() - start) * 1000

    real_times = [timed_login(_CEO_EMAIL) for _ in range(samples)]
    unknown_times = [timed_login("nobody-at-all@example.com") for _ in range(samples)]
    real_avg = sum(real_times) / samples
    unknown_avg = sum(unknown_times) / samples
    diff = abs(real_avg - unknown_avg)
    baseline = max(real_avg, unknown_avg)
    relative_diff = diff / baseline if baseline else 0

    assert relative_diff < tolerance_fraction, (
        f"timing difference {diff:.1f}ms is {relative_diff:.0%} of the baseline, "
        f"exceeds {tolerance_fraction:.0%} tolerance "
        f"(real email avg {real_avg:.1f}ms, unknown email avg {unknown_avg:.1f}ms) "
        f"— the dummy-hash timing defence may be broken"
    )
    return f"diff {diff:.1f}ms ({relative_diff:.0%} of baseline), tolerance {tolerance_fraction:.0%}"


def check_me_no_header(t: SmokeTest) -> None:
    status, _, raw = http_request("GET", t.api("/me"))
    t.record_response("me_no_header", raw)
    assert status == 401, f"expected 401, got {status}: {raw}"


def check_me_malformed_headers(t: SmokeTest) -> str:
    variants = ["Basic xyz", "Bearer", "Bearer "]
    for variant in variants:
        status, _, raw = http_request("GET", t.api("/me"), headers={"Authorization": variant})
        t.record_response(f"me_malformed_{variant!r}", raw)
        assert status == 401, f"Authorization: {variant!r} expected 401, got {status}: {raw}"
    return f"{len(variants)} variants"


def check_me_valid_token(t: SmokeTest) -> str:
    token = t.state.get("token")
    assert token is not None, "check 10 (login) did not run first"
    status, _, raw = http_request("GET", t.api("/me"), headers={"Authorization": f"Bearer {token}"})
    t.record_response("me_valid_token", raw)
    t.state["me_valid_status"] = status
    assert status == 200, f"expected 200, got {status}: {raw}"
    body = json.loads(raw)
    assert body.get("email") == _CEO_EMAIL, f"unexpected identity: {raw}"
    assert body.get("role") == "CEO", f"unexpected role: {raw}"
    return f"{body.get('email')} ({body.get('role')})"


def check_proxy_header_regression(t: SmokeTest) -> None:
    """Explicitly labeled so it doesn't get deleted as "redundant with
    check 17" — bin/proxy-server.js once silently dropped the
    Authorization header entirely (see README), and check 17 succeeding
    is the only thing that proves that regression hasn't come back.
    """
    status = t.state.get("me_valid_status")
    assert status is not None, "check 17 (valid token) did not run first"
    assert status == 200, "Authorization header did not reach the Lambda — the proxy-header bug may be back"


def check_me_tampered_token(t: SmokeTest) -> None:
    token = t.state.get("token")
    assert token is not None, "check 10 (login) did not run first"
    tampered = tamper_token(token)
    status, _, raw = http_request("GET", t.api("/me"), headers={"Authorization": f"Bearer {tampered}"})
    t.record_response("me_tampered_token", raw)
    assert status == 401, f"expected 401, got {status}: {raw}"


def check_me_expired_token(t: SmokeTest) -> None:
    expired = mint_expired_token()
    status, _, raw = http_request("GET", t.api("/me"), headers={"Authorization": f"Bearer {expired}"})
    t.record_response("me_expired_token", raw)
    assert status == 401, f"expected 401, got {status}: {raw}"


def check_no_leakage(t: SmokeTest) -> str:
    forbidden = ["password_hash", "$2b$", _CEO_PASSWORD, _DEACTIVATED_PASSWORD]
    for label, raw in t.raw_responses:
        for needle in forbidden:
            assert needle not in raw, f"response '{label}' contains a forbidden substring"
    return f"scanned {len(t.raw_responses)} response(s)"


def check_spa_root(t: SmokeTest) -> None:
    status, headers, raw = http_request("GET", f"{t.base_url}/")
    assert status == 200, f"expected 200, got {status}"
    assert "text/html" in headers.get("content-type", ""), f"unexpected content-type: {headers}"
    assert len(raw) > 0, "empty body"


def check_410_survives_cloudfront(t: SmokeTest) -> None:
    check6 = t.state.get("check6")
    assert check6 is not None, "check 6 (410) did not run first"
    assert check6["status"] == 410, f"CloudFront rewrote the status: got {check6['status']}"
    assert "application/json" in check6["content_type"], (
        f"CloudFront rewrote the content-type to {check6['content_type']!r} "
        f"— this is exactly the custom_error_response rewrite the 410 choice exists to avoid"
    )
    assert "detail" in json.loads(check6["raw"]), "body lost its 'detail' key in transit"


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("local", "aws"):
        print(__doc__)
        return 2

    target = sys.argv[1]
    t = SmokeTest(target)
    print(f"Target: {target}  Base URL: {t.base_url}\n")

    print("-- Wiring --")
    t.run("1. GET /health -> 200", lambda: check_health(t))
    t.run("2. path prefix, both shapes, against the raw Lambda", lambda: check_path_prefix_both_shapes(t))

    print("\n-- Slice 1: public reads --")
    t.run("3. GET /work-locations -> 200, includes Remote", lambda: check_work_locations_list(t))
    t.run("4. Remote: name set, all 4 address fields null (present)", lambda: check_remote_null_fields(t))
    t.run("5. GET /work-locations/{real id} -> 200", lambda: check_work_location_get_by_id(t))
    t.run("6. GET /work-locations/999999 -> 410, JSON, real body", lambda: check_work_location_410(t))
    t.run("7. GET /work-locations/abc -> 422", lambda: check_work_location_422(t))
    t.run("8. GET /expertise -> 200, 4 rows", lambda: check_expertise_list(t))
    t.run("9. Public endpoint ignores a garbage Authorization header", lambda: check_public_endpoint_ignores_garbage_auth_header(t))

    print("\n-- Slice 2: auth --")
    t.run("10. POST /login correct credentials -> 200 + token", lambda: check_login_success(t))
    t.run("11. POST /login wrong password -> 401", lambda: check_login_wrong_password(t))
    t.run("12. POST /login unknown email -> 401, body IDENTICAL to #11", lambda: check_login_unknown_email_identical(t))
    t.run("13. POST /login deactivated account -> 401", lambda: check_login_deactivated(t))
    t.run("14. TIMING: unknown-email vs wrong-password, asserted", lambda: check_login_timing(t))
    t.run("15. GET /me no Authorization header -> 401", lambda: check_me_no_header(t))
    t.run("16. GET /me malformed headers -> 401", lambda: check_me_malformed_headers(t))
    t.run("17. GET /me valid token -> 200, correct identity", lambda: check_me_valid_token(t))
    t.run("18. GET /me tampered token -> 401", lambda: check_me_tampered_token(t))
    t.run("19. GET /me expired token -> 401", lambda: check_me_expired_token(t))

    print("\n-- Leakage --")
    t.run("20. No password_hash / $2b$ / plaintext password in any response", lambda: check_no_leakage(t))

    print("\n-- Regression: bugs we already found --")
    t.run("21. Authorization header reaches the Lambda (proxy-header bug)", lambda: check_proxy_header_regression(t))

    if target == "aws":
        print("\n-- AWS only --")
        t.run("22. SPA loads at root, returns HTML", lambda: check_spa_root(t))
        t.run("23. 410 (check 6) survives CloudFront intact", lambda: check_410_survives_cloudfront(t))

    ok = t.summary()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

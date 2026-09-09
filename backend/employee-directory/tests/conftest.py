"""Local test defaults for the POSTGRES_*/IS_LOCAL env vars Terraform
normally injects (see infra/locals.tf). Only fills in values that aren't
already set, so it never overrides real configuration — it exists purely
so `pytest` works out of the box against the local Postgres instance
every participant already has running (see docs/validation.md).
"""

import os

os.environ.setdefault("IS_LOCAL", "true")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("POSTGRES_NAME", "postgres")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASS", "postgres123")


def make_function_url_event(raw_path: str) -> dict:
    """Builds a fake Lambda Function URL event (payload format 2.0) for a
    given raw path, so tests can invoke function.handler() directly with
    the exact shape AWS sends — CloudFront forwards the full,
    "/api/employee-directory"-prefixed path unstripped; the local proxy
    strips it before the Lambda ever sees the request. Shared here so
    every test that needs to prove both shapes resolve the same way
    doesn't hand-build this event from scratch.
    """
    return {
        "version": "2.0",
        "rawPath": raw_path,
        "rawQueryString": "",
        "headers": {"host": "example.lambda-url.us-east-2.on.aws"},
        "requestContext": {
            "http": {
                "method": "GET",
                "path": raw_path,
                "protocol": "HTTP/1.1",
                "sourceIp": "127.0.0.1",
                "userAgent": "pytest",
            },
            "domainName": "example.lambda-url.us-east-2.on.aws",
            "requestId": "test-request-id",
            "time": "01/Jan/2026:00:00:00 +0000",
            "timeEpoch": 1735689600,
        },
        "isBase64Encoded": False,
    }

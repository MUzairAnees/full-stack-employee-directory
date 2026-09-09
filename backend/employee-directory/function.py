"""Lambda entry point.

Adapts the FastAPI app to run behind an AWS Lambda Function URL via Mangum.

`api_gateway_base_path` strips the "/api/employee-directory" prefix when it
is present in the incoming path (as it is on AWS, where CloudFront forwards
the full unmodified path) and is a no-op when it is absent (as it is
locally, where bin/proxy-server.js already strips it before forwarding).
Either way the FastAPI app only ever sees routes like "/health".
"""

import logging

from mangum import Mangum

# The Lambda runtime pre-attaches a root handler whose level filters out
# INFO — force=True replaces it so app.db_init's migration log lines (and
# anything else at INFO) actually reach CloudWatch instead of being
# silently dropped.
logging.basicConfig(level=logging.INFO, force=True)

from app.main import app  # noqa: E402

handler = Mangum(app, lifespan="off", api_gateway_base_path="/api/employee-directory")

"""Lambda entry point.

Adapts the FastAPI app to run behind an AWS Lambda Function URL via Mangum.

`api_gateway_base_path` strips the "/api/employee-directory" prefix when it
is present in the incoming path (as it is on AWS, where CloudFront forwards
the full unmodified path) and is a no-op when it is absent (as it is
locally, where bin/proxy-server.js already strips it before forwarding).
Either way the FastAPI app only ever sees routes like "/health".
"""

from mangum import Mangum

from app.main import app

handler = Mangum(app, lifespan="off", api_gateway_base_path="/api/employee-directory")

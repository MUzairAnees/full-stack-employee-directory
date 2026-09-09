"""FastAPI application entry point for the employee directory service."""

from fastapi import FastAPI

app = FastAPI(title="Employee Directory")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Returns:
        dict[str, str]: A static status payload confirming the service is up.
    """
    return {"status": "ok"}

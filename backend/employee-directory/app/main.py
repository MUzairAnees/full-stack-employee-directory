"""FastAPI application entry point for the employee directory service."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.controllers import auth, departments, employees, expertise, projects, skills, teams, work_locations
from app.exceptions import DependentsExistError, DuplicateError, InvalidReferenceError, NotFoundError

app = FastAPI(title="Employee Directory")

app.include_router(auth.router)
app.include_router(work_locations.router)
app.include_router(expertise.router)
app.include_router(departments.router)
app.include_router(employees.router)
app.include_router(teams.router)
app.include_router(skills.router)
app.include_router(projects.router)


@app.exception_handler(NotFoundError)
async def not_found_error_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    """Maps every domain NotFoundError to 410 Gone, in exactly one place.

    410, not 404: per workshop guidance, this platform's CloudFront
    distribution reserves 404 for its SPA deep-link fallback (see README).
    410 isn't semantically perfect for "never existed" — that's what 404
    means — but it's what the platform leaves available, and every
    controller's "get by id" raises the same NotFoundError and lands here
    rather than each repeating its own status code.

    This does not affect FastAPI's own 404 for unmatched routes — that's
    a framework response we don't raise and don't control; see
    frontend/src/services/api.js's apiFetch for how that case is handled.
    """
    return JSONResponse(status_code=410, content={"detail": str(exc)})


@app.exception_handler(DuplicateError)
async def duplicate_error_handler(request: Request, exc: DuplicateError) -> JSONResponse:
    """Maps a uniqueness-constraint violation to 409, in one place —
    same pattern as NotFoundError above.
    """
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(DependentsExistError)
async def dependents_exist_error_handler(request: Request, exc: DependentsExistError) -> JSONResponse:
    """Maps a delete/deactivate blocked by active dependents or a system
    invariant (the CEO, the last active Admin) to 409, in one place.
    """
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(InvalidReferenceError)
async def invalid_reference_error_handler(request: Request, exc: InvalidReferenceError) -> JSONResponse:
    """Maps a foreign-key violation to 422, naming the field — employees
    have four FK columns, and a bare "invalid reference" wouldn't tell
    the caller which one they got wrong.
    """
    return JSONResponse(status_code=422, content={"detail": str(exc), "field": exc.field})


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check.

    Returns:
        dict[str, str]: A static status payload confirming the service is up.
    """
    return {"status": "ok"}

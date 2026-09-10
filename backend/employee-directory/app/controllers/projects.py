"""Routes for /projects — the shared lookup list. Per-employee attach/
complete/detach lives under /employees/{id}/projects
(app/controllers/employees.py), since those are employee sub-resources,
same split as skills.
"""

from fastapi import APIRouter, Depends

from app.dependencies import current_user, require_role
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.project import ProjectCreate, ProjectOut, ProjectUpdate
from app.services import project_service as service

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get(
    "",
    response_model=list[ProjectOut],
    responses={401: {"description": "Not authenticated."}},
)
def list_projects(_employee: Employee = Depends(current_user)) -> list[ProjectOut]:
    """Any authenticated employee can list the full projects lookup."""
    return service.list_projects()


@router.get(
    "/{project_id}",
    response_model=ProjectOut,
    responses={
        401: {"description": "Not authenticated."},
        410: {"description": "No project with this id."},
    },
)
def get_project(project_id: int, _employee: Employee = Depends(current_user)) -> ProjectOut:
    """Any authenticated employee can look up a project by id."""
    return service.get_project(project_id)


@router.post(
    "",
    response_model=ProjectOut,
    status_code=201,
    responses={
        201: {"description": "Created."},
        401: {"description": "Not authenticated."},
        409: {"description": "A project with this name (any case) already exists."},
        422: {"description": "Name is empty/whitespace-only or over the max length."},
    },
)
def create_project(body: ProjectCreate, _employee: Employee = Depends(current_user)) -> ProjectOut:
    """Open to any authenticated user — NOT Admin-gated, unlike
    PUT below. Explicit create: 409s on a name collision rather than
    reusing the existing row (that's what get-or-create via
    POST /employees/{id}/projects is for) — see
    project_repository.create_project for why that distinction is
    load-bearing for PUT's Admin gate below.
    """
    return service.create_project(body.name, body.description)


@router.put(
    "/{project_id}",
    response_model=ProjectOut,
    responses={
        401: {"description": "Not authenticated."},
        403: {"description": "Caller isn't Admin."},
        409: {"description": "The new name (any case) collides with another project."},
        410: {"description": "No project with this id."},
        422: {"description": "Name is empty/whitespace-only or over the max length."},
    },
)
def update_project(
    project_id: int, body: ProjectUpdate, _employee: Employee = Depends(require_role(Role.ADMIN))
) -> ProjectOut:
    """Admin only. Renames and/or redescribes an existing project —
    gated here because POST above 409s on collision rather than
    reusing/overwriting; without that, this gate would be decorative
    (anyone could rewrite a shared description by re-POSTing the name).
    """
    return service.update_project(project_id, body)

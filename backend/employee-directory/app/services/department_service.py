"""Business logic for departments."""

from app.models.department import Department
from app.repositories import department_repository as repo


def list_departments(*, include_inactive: bool = False) -> list[Department]:
    return repo.list_departments(include_inactive=include_inactive)


def get_department(department_id: int) -> Department:
    return repo.get_department(department_id)


def create_department(name: str) -> Department:
    return repo.create_department(name)


def update_department(department_id: int, name: str | None, is_active: bool | None) -> Department:
    return repo.update_department(department_id, name, is_active)


def delete_department(department_id: int) -> Department:
    return repo.soft_delete_department(department_id)

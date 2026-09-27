from uuid import UUID

from sqlalchemy.orm import Session

from app.domain import Project, ProjectStatus, WorkType
from app.infrastructure.models import ProjectRecord, WorkTypeRecord


class SqlProjectRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, project: Project) -> Project:
        self._session.add(
            ProjectRecord(
                id=str(project.id),
                title=project.title,
                description=project.description,
                status=project.status.value,
            )
        )
        self._session.flush()
        return project

    def get(self, project_id: UUID) -> Project | None:
        record = self._session.get(ProjectRecord, str(project_id))
        if record is None:
            return None
        return Project(
            id=UUID(record.id),
            title=record.title,
            description=record.description,
            status=ProjectStatus(record.status),
        )


class SqlWorkTypeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, work_type: WorkType) -> WorkType:
        self._session.add(
            WorkTypeRecord(
                id=str(work_type.id),
                name=work_type.name,
                description=work_type.description,
            )
        )
        self._session.flush()
        return work_type

    def get(self, work_type_id: UUID) -> WorkType | None:
        record = self._session.get(WorkTypeRecord, str(work_type_id))
        if record is None:
            return None
        return WorkType(
            id=UUID(record.id),
            name=record.name,
            description=record.description,
        )

from uuid import UUID

from sqlalchemy import select
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

    def list_all(self) -> list[Project]:
        records = self._session.scalars(
            select(ProjectRecord).order_by(ProjectRecord.title, ProjectRecord.id)
        ).all()
        return [
            Project(id=UUID(record.id), title=record.title,
                    description=record.description, status=ProjectStatus(record.status))
            for record in records
        ]


class SqlWorkTypeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _domain(row: WorkTypeRecord) -> WorkType:
        return WorkType(id=UUID(row.id), name=row.name, description=row.description,
                        scope_id=UUID(row.scope_id), version=row.version)

    def add(self, work_type: WorkType) -> WorkType:
        self._session.add(WorkTypeRecord(
            id=str(work_type.id), name=work_type.name,
            description=work_type.description, scope_id=str(work_type.scope_id),
            version=work_type.version,
        ))
        self._session.flush()
        return work_type

    def get(self, work_type_id: UUID) -> WorkType | None:
        row = self._session.get(WorkTypeRecord, str(work_type_id))
        return self._domain(row) if row is not None else None

    def list_all(self) -> list[WorkType]:
        rows = self._session.scalars(select(WorkTypeRecord).order_by(
            WorkTypeRecord.name, WorkTypeRecord.id)).all()
        return [self._domain(row) for row in rows]

    def list_owner(self, owner: str) -> list[WorkType]:
        from app.infrastructure.models import ScheduleScopeRecord
        rows = self._session.scalars(select(WorkTypeRecord).join(
            ScheduleScopeRecord, WorkTypeRecord.scope_id == ScheduleScopeRecord.id,
        ).where(ScheduleScopeRecord.owner_id == owner).order_by(
            WorkTypeRecord.name, WorkTypeRecord.id)).all()
        return [self._domain(row) for row in rows]

    def rename(self, work_type_id: UUID, expected_version: int,
               name: str, description: str | None) -> WorkType:
        from sqlalchemy import update
        from app.domain.recurring_availability import RuleConflict
        stmt = update(WorkTypeRecord).where(
            WorkTypeRecord.id == str(work_type_id),
            WorkTypeRecord.version == expected_version,
        ).values(name=name, description=description, version=expected_version + 1)
        if self._session.execute(stmt).rowcount != 1:
            raise RuleConflict("work type version changed")
        self._session.flush()
        return self.get(work_type_id)

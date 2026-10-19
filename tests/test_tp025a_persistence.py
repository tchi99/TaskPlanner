"""TP-025A stored revisions and exceptions stay owner-scoped and append-only."""
from dataclasses import replace
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session

from app.domain.eligibility import (
    EligibilityAction, EligibilityConflict, EligibilityException,
    EligibilityRevision, EligibilitySeries,
)
from app.infrastructure.db import Base
from app.infrastructure.eligibility_repository import SqlEligibilityRepository
from app.infrastructure.models import (
    EligibilityRevisionRecord, EligibilityExceptionRevisionRecord,
    ScheduleScopeRecord, WorkTypeRecord,
)


def test_repository_cas_revisions_and_exception_audit():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    owner, scope, work_type, sid = "owner", uuid4(), uuid4(), uuid4()
    with Session(engine) as session:
        session.add(ScheduleScopeRecord(
            id=str(scope), owner_id=owner, name="Travail", state="ACTIVE",
            version=1))
        session.add(WorkTypeRecord(id=str(work_type), name="Focus", description=None,
                                    scope_id=str(scope), version=1))
        session.flush()
        repo = SqlEligibilityRepository(session)
        rev = EligibilityRevision(
            sid, 1, date(2027, 1, 4), None, "America/Toronto",
            (1, 3), "09:00", "12:00")
        value = EligibilitySeries(sid, owner, scope, work_type, 1, (rev,))
        repo.add(value)
        assert repo.get(sid, "stranger") is None
        assert repo.list_owner("stranger") == []
        next_rev = replace(rev, number=2, effective_from=date(2027, 1, 11),
                           priority_rank=1)
        repo.append_revision(owner, next_rev, expected_version=1)
        assert repo.get(sid, owner).version == 2
        assert [r.priority_rank for r in repo.get(sid, owner).revisions] == [
            None, 1]
        with pytest.raises(EligibilityConflict):
            repo.append_revision(owner, next_rev, expected_version=1)
        exc_id = uuid4()
        exception = EligibilityException(
            exc_id, owner, sid, date(2027, 1, 12), 1,
            EligibilityAction.REMOVE, "America/Toronto")
        repo.add_exception(exception)
        changed = replace(
            exception, version=2, action=EligibilityAction.MOVE,
            starts_at=datetime(2027, 1, 12, 15, tzinfo=timezone.utc),
            ends_at=datetime(2027, 1, 12, 17, tzinfo=timezone.utc),
        )
        repo.append_exception(changed, expected_version=1)
        assert repo.get_exception(exc_id, owner) == changed
        assert repo.get_exception(exc_id, "stranger") is None
        with pytest.raises(EligibilityConflict):
            repo.append_exception(changed, expected_version=1)
        assert session.scalar(select(func.count()).select_from(
            EligibilityRevisionRecord)) == 2
        assert session.scalar(select(func.count()).select_from(
            EligibilityExceptionRevisionRecord)) == 2
        session.commit()
    engine.dispose()

"""TP-022B: immutable snapshots of civil availability exceptions."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.recurring_availability import AvailabilityMode, RuleKind


class ExceptionAction(StrEnum):
    CANCEL = "CANCEL"
    REPLACE = "REPLACE"
    ADD = "ADD"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class AvailabilityException:
    id: UUID
    owner_id: str
    version: int
    action: ExceptionAction
    rule_id: UUID | None = None
    original_local_date: date | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    timezone_name: str = "UTC"
    kind: RuleKind | None = None
    work_type_id: UUID | None = None
    mode: AvailabilityMode | None = None
    enabled: bool = True
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.owner_id or len(self.owner_id) > 128 or self.version < 1:
            raise ValueError("invalid exception identity or version")
        if self.reason is not None and (not self.reason.strip() or len(self.reason) > 500):
            raise ValueError("reason must contain 1 to 500 characters")
        try:
            zone = ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, TypeError, ValueError) as exc:
            raise ValueError("unknown IANA timezone") from exc
        targeted = self.action in (ExceptionAction.CANCEL, ExceptionAction.REPLACE)
        if targeted != (self.rule_id is not None and self.original_local_date is not None):
            raise ValueError("CANCEL/REPLACE require an original occurrence; ADD/UNAVAILABLE must not target a rule")
        if self.action is ExceptionAction.CANCEL:
            if any(value is not None for value in
                   (self.starts_at, self.ends_at, self.kind, self.work_type_id, self.mode)):
                raise ValueError("CANCEL has no replacement interval or category")
        else:
            if self.starts_at is None or self.ends_at is None:
                raise ValueError("exception requires start and end")
            for value in (self.starts_at, self.ends_at):
                if value.tzinfo is None or value.utcoffset() is None:
                    raise ValueError("exception instants must include UTC offsets")
                if value.second or value.microsecond:
                    raise ValueError("exception instants must align to whole minutes")
                local = value.astimezone(zone)
                if local.replace(tzinfo=None) != value.replace(tzinfo=None) or local.utcoffset() != value.utcoffset():
                    raise ValueError("local time/offset is invalid for the IANA timezone (DST)")
            if not timedelta(0) < self.ends_at.astimezone(timezone.utc) - self.starts_at.astimezone(timezone.utc) <= timedelta(days=93):
                raise ValueError("exception must have positive duration of at most 93 days")
            if self.action is ExceptionAction.UNAVAILABLE:
                if any(value is not None for value in (self.kind, self.work_type_id, self.mode)):
                    raise ValueError("UNAVAILABLE is independent of work type")
            elif self.kind is RuleKind.GENERAL:
                if self.work_type_id is not None or self.mode is not None:
                    raise ValueError("GENERAL exception has no work type or mode")
            elif self.kind is RuleKind.CATEGORIZED:
                if self.work_type_id is None or self.mode is None:
                    raise ValueError("CATEGORIZED exception requires work type and mode")
            else:
                raise ValueError("ADD/REPLACE require GENERAL or CATEGORIZED kind")

    def active_interval(self) -> tuple[datetime, datetime] | None:
        if not self.enabled or self.starts_at is None or self.ends_at is None:
            return None
        return (self.starts_at.astimezone(timezone.utc), self.ends_at.astimezone(timezone.utc))

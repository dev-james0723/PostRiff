"""One Indianapolis schedule and exact, timezone-aware data cutoffs."""
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TZ_NAME = "America/Indiana/Indianapolis"
TZ = ZoneInfo(TZ_NAME)


@dataclass(frozen=True)
class Period:
    workday: str
    kind: str
    start: datetime
    cutoff: datetime

    @property
    def key(self):
        return f"agent-team:v1:{self.workday}:{self.kind}"

    def as_dict(self):
        return {"workday": self.workday, "kind": self.kind, "timezone": TZ_NAME,
                "start": self.start.isoformat(), "cutoff": self.cutoff.isoformat(),
                "key": self.key, "actualSeconds": int((self.cutoff-self.start).total_seconds())}


def aware(value):
    value = datetime.fromisoformat(str(value).replace("Z", "+00:00")) if not isinstance(value, datetime) else value
    if value.tzinfo is None:
        raise ValueError("timestamp_requires_timezone")
    return value.astimezone(timezone.utc)


def period(workday, kind):
    d = date.fromisoformat(workday)
    if kind not in ("half_day", "whole_day"):
        raise ValueError("invalid_report_kind")
    start = datetime.combine(d, time(1), TZ).astimezone(timezone.utc)
    end = datetime.combine(d if kind == "half_day" else d+timedelta(days=1),
                           time(17 if kind == "half_day" else 1), TZ).astimezone(timezone.utc)
    return Period(workday, kind, start, end)


def latest_due(now):
    """Return the latest cutoff; persistence decides whether already generated/delivered."""
    n = aware(now).astimezone(TZ)
    if n.hour >= 17:
        return period(n.date().isoformat(), "half_day")
    if n.hour >= 1:
        return period((n.date()-timedelta(days=1)).isoformat(), "whole_day")
    return period((n.date()-timedelta(days=1)).isoformat(), "half_day")


def next_due(now):
    n = aware(now).astimezone(TZ)
    if n.hour < 1:
        return period((n.date()-timedelta(days=1)).isoformat(), "whole_day")
    if n.hour < 17:
        return period(n.date().isoformat(), "half_day")
    return period(n.date().isoformat(), "whole_day")

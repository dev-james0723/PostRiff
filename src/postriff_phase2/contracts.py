"""Provider and persistence boundaries shared by local and hosted candidates."""
import hashlib
import json
from typing import Protocol
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from postriff_alpha.domain import AlphaError

PLANS = {"studio": {"price": 19, "features": ["drafts", "export", "scheduling"]},
         "assist": {"price": 39, "features": ["drafts", "export", "scheduling", "assisted-writing"]}}
LIMITS = {"LinkedIn": {"version": "local-conservative-2026-09-14", "characters": 3000, "operation": "member_post"},
          "Instagram": {"version": "local-conservative-2026-09-14", "characters": 2200, "operation": "professional_image"},
          # Threads text limit per the connector audit (500 chars, 250 posts/24h); hosted OAuth connector.
          "Threads": {"version": "hosted-2026-09-16", "characters": 500, "operation": "text_post"}}
SCENARIOS = ("success", "denied", "expired", "accepted", "delayed", "failed", "rate_limited", "timeout", "duplicate", "uncertain", "malformed", "capability_loss")

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()

class WorkspaceRepository(Protocol):
    """All commands require membership and a compare-and-swap revision."""
    def get(self, workspace_id: str, token: str) -> dict: ...
    def mutate(self, workspace_id: str, token: str, expected_revision: int, action: str, payload: dict) -> dict: ...

class ImageAdapter(Protocol):
    def previews(self, brief: dict, count: int) -> list[bytes]: ...

class SocialAdapter(Protocol):
    def submit(self, manifest: dict, scenario: str) -> dict: ...
    def reconcile(self, manifest: dict, scenario: str, checks: int) -> dict: ...

def tzdb_version():
    """Which time-zone database resolved the instant; recorded so a later rule change is detectable."""
    try:
        import importlib.metadata
        return "tzdata " + importlib.metadata.version("tzdata")
    except Exception:
        import zoneinfo
        return "system:" + ",".join(zoneinfo.TZPATH)[:120]


def resolve_time(local, zone, fold, now):
    try:
        naive = datetime.fromisoformat(local)
        tz = ZoneInfo(zone)
        if naive.tzinfo is not None:
            raise ValueError()
        choices = [naive.replace(tzinfo=tz, fold=n) for n in (0, 1)]
        valid = [x for x in choices if x.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == naive]
        if not valid:
            raise AlphaError("This local time does not exist because clocks change. Choose another time.")
        ambiguous = len({x.utcoffset() for x in valid}) > 1
        if ambiguous and (type(fold) is not int or fold not in (0, 1)):
            raise AlphaError("This time occurs twice. Choose the first or second occurrence.")
        instant = choices[fold if ambiguous else 0].timestamp()
        if instant <= now:
            raise AlphaError("Choose a future time.")
        return {"local": local, "timeZone": zone, "fold": fold if ambiguous else 0, "utc": datetime.fromtimestamp(instant, timezone.utc).isoformat(), "timestamp": instant, "tzdb": tzdb_version()}
    except (ValueError, TypeError, ZoneInfoNotFoundError) as e:
        raise AlphaError("Use a valid local date, time and IANA time zone.") from e

class FixtureSocial:
    """Deterministic official-provider contract simulator; zero network access."""
    def submit(self, manifest, scenario):
        reference = "synthetic-" + manifest["idempotencyKey"][:16]
        if scenario in ("timeout", "uncertain", "malformed"):
            return {"state": "uncertain", "confirmed": "No conclusive response", "reference": reference}
        if scenario in ("denied", "expired", "capability_loss"):
            return {"state": "held", "confirmed": "Fixture permission unavailable", "reference": reference}
        if scenario == "rate_limited":
            return {"state": "scheduled", "confirmed": "Fixture rejected before acceptance; retry after 60 seconds", "reference": reference}
        if scenario == "failed":
            return {"state": "failed", "confirmed": "Fixture rejected before acceptance", "reference": reference}
        return {"state": "provider_accepted", "confirmed": "Synthetic provider accepted request; publication not confirmed", "reference": reference}

    def reconcile(self, manifest, scenario, checks):
        reference = "synthetic-" + manifest["idempotencyKey"][:16]
        if scenario in ("uncertain", "malformed"):
            return {"state": "uncertain", "confirmed": "Fixture lookup inconclusive; manual review required"}
        if scenario == "accepted" or (scenario == "delayed" and checks < 2):
            return {"state": "provider_accepted", "confirmed": "Synthetic processing; not yet published", "reference": reference}
        return {"state": "published" if checks < 2 else "verified", "confirmed": "Synthetic publication lookup matched the approved payload", "reference": reference, "verification": "fixture_lookup"}

class FixtureImages:
    def previews(self, brief, count):
        from postriff_alpha.visuals import watercolor
        if not 1 <= count <= 3:
            raise AlphaError("Choose one to three previews.")
        return [watercolor(n).encode() for n in range(count)]

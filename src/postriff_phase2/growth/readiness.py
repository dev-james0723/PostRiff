"""Growth Studio readiness: one honest answer per tab, computed on the server.

Built only with ``feature_readiness`` (``blocker``/``resolve``/``owner_step``), so
the payload, precedence and "an outage never says reconnect" rules are the shared
contract (docs/releases/growth-trends-20261008/CONTRACTS.md §1).

Computing readiness reads this workspace's own rows and the environment. It never
calls a provider or a model and never writes. ``canRun`` only decides which controls
render; every action still checks role, consent, rights, budget and revision itself.

Sections:
- ``studio``: the page shell (flags and schema).
- ``results``: verified publications, their native readings and reviews.
- ``audience``: comments on the workspace's own Threads/Instagram posts.
- ``patterns``: personal calibration, which needs ``MINIMUM_POSTS`` comparable posts.
- ``measurement``: whether native readings are collected for this workspace.

Growth reason codes added by lane B (beyond CONTRACTS.md §1): ``measurement_off``
(the global POSTRIFF_METRIC_READS switch is off) and ``no_comments`` (comment sources
exist but no eligible comment has arrived yet).
"""
from __future__ import annotations

import time

from postriff_alpha.domain import AlphaError

from .. import feature_enrollment, feature_readiness as fr
from . import metric_schedule

SECTIONS = ("studio", "results", "audience", "patterns", "measurement")
MEASUREMENT_FEATURE = "growth_measurement"
MINIMUM_POSTS = 50
NATIVE_PLATFORMS = {"Threads": "threads", "Instagram": "instagram"}
CONNECT = "/app/channels"
RESULTS_HREF = "/app/growth?view=results"
AUDIENCE_HREF = "/app/growth?view=audience"
DAILY_RUNS = {"postmortem": 10, "audience": 2}

# Tables each section reads. 037/038 are additive and may be missing until applied.
RUN_TABLES = ("pr_post_doctor_runs", "pr_growth_budgets")
RESULT_TABLES = (*RUN_TABLES, "pr_predictions", "pr_postmortems", "pr_creator_calibrations")
AUDIENCE_TABLES = (*RUN_TABLES, "pr_audience_clusters", "pr_comment_judgments")
GENOME_TABLES = (*RUN_TABLES, "pr_post_history", "pr_genome_versions", "pr_share_cards")
MEASUREMENT_TABLES = ("pr_metric_reads", "pr_metric_observations", "pr_owned_posts", "pr_growth_purges")
ALL_TABLES = tuple(dict.fromkeys((*RESULT_TABLES, *AUDIENCE_TABLES, *GENOME_TABLES, *MEASUREMENT_TABLES)))


def present_tables(cur, tables=ALL_TABLES):
    """The subset of ``tables`` that exists (one catalog query, no write)."""
    cur.execute("SELECT name FROM unnest(%s::text[]) AS name WHERE to_regclass('public.' || name) IS NOT NULL", (list(tables),))
    return {row[0] for row in cur.fetchall()}


def require_schema(cur, tables):
    """Structured 503 instead of a relation error while additive migrations are pending."""
    missing = set(tables) - present_tables(cur, tables)
    if missing:
        raise AlphaError("Growth Studio is still being set up here. Your drafts and analytics are unaffected; try again later.",
                         503, code="growth_schema_unavailable")


def _connect(facts):
    if facts["canManageConnections"]:
        return {"next_kind": "connect", "href": CONNECT}
    return {"next_kind": "contact_owner", "href": None}


def _owner(kind, href, facts):
    return fr.owner_step(kind, href, role=facts["role"])


def _flag_blocker(facts, sub, code):
    if not facts["flags"]["growth"]:
        return fr.blocker("feature_disabled", "growth_off", blocks_read=True)
    if not facts["flags"][sub]:
        return fr.blocker("feature_disabled", code, blocks_read=True)
    return None


def _schema_blocker(facts, tables):
    if set(tables) <= facts["tables"]:
        return None
    return fr.blocker("temporarily_unavailable", "growth_schema_unavailable", next_kind="wait", blocks_read=True)


def _run_blockers(facts, kind):
    """Who may start a paid run, and whether the spend limits allow one today."""
    out = []
    if not facts["canEdit"]:
        out.append(fr.blocker("setup_required", "role_edit_required", next_kind="contact_owner"))
    if not facts["capsConfigured"]:
        out.append(fr.blocker("temporarily_unavailable", "growth_budget_unconfigured", next_kind="wait"))
    elif facts["dailyUsed"].get(kind):
        out.append(fr.blocker("temporarily_unavailable", "growth_daily_limit", next_kind="wait"))
    return out


def _connection_blockers(facts, *, comments=False):
    if not facts["connections"]:
        return [fr.blocker("setup_required", "analytics_connection_required", **_connect(facts))]
    if comments and not facts["commentsDirect"]:
        return [fr.blocker("setup_required", "comments_permission_required", **_connect(facts))]
    if not comments and not facts["analyticsDirect"]:
        return [fr.blocker("setup_required", "analytics_permission_required", **_connect(facts))]
    return []


def _admission_blockers(facts):
    m = facts["measurement"]
    if not m["on"] or m["admitted"]:
        return []
    if (m.get("eligibility") or {}).get("eligible"):
        return [fr.blocker("setup_required", "measurement_enrollment_required", **_owner("consent", RESULTS_HREF, facts))]
    return [fr.blocker("not_entitled", "measurement_paused")]


def measurement(facts):
    m = facts["measurement"]
    if not m["on"]:
        return fr.resolve([fr.blocker("feature_disabled", "measurement_off")], last_successful_read_at=facts["lastReadAt"])
    blockers = []
    if (schema := _schema_blocker(facts, MEASUREMENT_TABLES)):
        blockers.append(schema)
    blockers += _connection_blockers(facts) + _admission_blockers(facts)
    if not facts["verifiedPublications"] and not facts["historyPosts"]:
        # Admitted collection is ready; there is simply nothing published to read yet.
        blockers.append(fr.blocker("insufficient_data", "no_verified_publications", blocks_run=False))
    return fr.resolve(blockers, last_successful_read_at=facts["lastReadAt"])


def results(facts):
    if (off := _flag_blocker(facts, "postmortem", "postmortem_off")):
        return fr.resolve([off], last_successful_read_at=facts["lastReadAt"])
    if (schema := _schema_blocker(facts, RESULT_TABLES)):
        return fr.resolve([schema], last_successful_read_at=facts["lastReadAt"])
    blockers = _connection_blockers(facts) + _admission_blockers(facts)
    if not facts["verifiedPublications"] and not facts["historyPosts"]:
        blockers.append(fr.blocker("insufficient_data", "no_verified_publications"))
    if not facts["consent"]["summary"]:
        blockers.append(fr.blocker("setup_required", "growth_consent_required", **_owner("consent", RESULTS_HREF, facts)))
    blockers += _run_blockers(facts, "postmortem")
    return fr.resolve(blockers, last_successful_read_at=facts["lastReadAt"])


def audience(facts):
    if (off := _flag_blocker(facts, "audience", "audience_off")):
        return fr.resolve([off])
    if (schema := _schema_blocker(facts, AUDIENCE_TABLES)):
        return fr.resolve([schema])
    blockers = _connection_blockers(facts, comments=True)
    if not blockers:
        if not facts["ownedCommentPosts"]:
            blockers.append(fr.blocker("insufficient_data", "no_verified_publications"))
        elif not facts["eligibleComments"]:
            blockers.append(fr.blocker("insufficient_data", "no_comments"))
    if not (facts["consent"]["audience"] and facts["consent"]["summary"]):
        blockers.append(fr.blocker("setup_required", "growth_consent_required", **_owner("consent", AUDIENCE_HREF, facts)))
    blockers += _run_blockers(facts, "audience")
    return fr.resolve(blockers)


def patterns(facts):
    if (off := _flag_blocker(facts, "postmortem", "postmortem_off")):
        return fr.resolve([off], last_successful_read_at=facts["lastReadAt"])
    if (schema := _schema_blocker(facts, RESULT_TABLES)):
        return fr.resolve([schema], last_successful_read_at=facts["lastReadAt"])
    blockers = []
    if facts["largestCohort"] < MINIMUM_POSTS:
        blockers.append(fr.blocker("insufficient_data", "sample_below_minimum"))
    # Proposing, approving and restoring a calibration are owner decisions.
    return fr.resolve(blockers, can_run=facts["role"] == "owner", last_successful_read_at=facts["lastReadAt"])


def studio(facts):
    flags = facts["flags"]
    if not flags["growth"] or not (flags["postmortem"] or flags["audience"]):
        return fr.resolve([fr.blocker("feature_disabled", "growth_off", blocks_read=True)], last_successful_read_at=facts["lastReadAt"])
    needed = (RESULT_TABLES if flags["postmortem"] else ()) + (AUDIENCE_TABLES if flags["audience"] else ())
    if (schema := _schema_blocker(facts, needed)):
        return fr.resolve([schema], last_successful_read_at=facts["lastReadAt"])
    return fr.resolve([], last_successful_read_at=facts["lastReadAt"])


def compute(facts):
    """Facts -> {section: validated readiness payload}."""
    built = {"studio": studio(facts), "results": results(facts), "audience": audience(facts),
             "patterns": patterns(facts), "measurement": measurement(facts)}
    return {name: fr.validate(value) for name, value in built.items()}


# --- facts (reads only) -------------------------------------------------------------------------------------------

def _caps_configured(growth):
    try:
        growth.cap("POSTRIFF_GROWTH_DAILY_USD_CAP")
        growth.cap("POSTRIFF_WORKSPACE_GROWTH_DAILY_USD_CAP")
    except AlphaError:
        return False
    return True


def measurement_admission(growth, cur, workspace_id):
    """(on, admitted, legacy, eligibility) for native readings. Same admission as MetricScheduler."""
    env = growth.env
    reader = getattr(growth.hosted, "metric_reads", None)
    on = metric_schedule.enabled(env) and reader is not None
    legacy = str(workspace_id) in metric_schedule.allowed_workspaces(env)
    enrolled = feature_enrollment.admitted(cur, workspace_id, MEASUREMENT_FEATURE, env)
    admitted = legacy or enrolled
    eligibility = None if admitted else feature_enrollment.eligibility(cur, workspace_id, MEASUREMENT_FEATURE, env)
    return {"on": on, "admitted": admitted, "legacy": legacy, "enrolled": enrolled, "eligibility": eligibility}


def verified_publications(state):
    revoked = {c.get("id") for c in (state.get("phase2") or {}).get("channels", []) if c.get("revoked")}
    return [j for j in (state.get("phase2") or {}).get("jobs", [])
            if j.get("state") == "verified" and j.get("verification") and j.get("providerReference")
            and (j.get("manifest") or {}).get("platform") in NATIVE_PLATFORMS
            and (j.get("manifest") or {}).get("channelId") not in revoked]


def gather(growth, cur, workspace_id, state, membership):
    """Every fact readiness needs, from this workspace's own rows. No provider, model or write."""
    from .closed_loop import SUMMARY_ROUTE
    env = growth.env
    flags = {"growth": env.get("POSTRIFF_GROWTH") == "1", "postmortem": growth.enabled("postmortem"),
             "audience": growth.enabled("audience"), "genome": growth.enabled("genome")}
    tables = present_tables(cur)
    channels = {c.get("id") for c in (state.get("phase2") or {}).get("channels", [])
                if not c.get("revoked") and c.get("platform") in NATIVE_PLATFORMS}
    cur.execute("SELECT connection_id,capability FROM public.pr_channel_capabilities WHERE workspace_id=%s "
                "AND capability IN ('analytics','comments_read') AND level='Direct'", (workspace_id,))
    direct = {}
    for connection_id, capability in cur.fetchall():
        direct.setdefault(capability, set()).add(connection_id)
    analytics = channels & direct.get("analytics", set())
    comments = channels & direct.get("comments_read", set())
    history = 0
    if set(MEASUREMENT_TABLES) <= tables:
        cur.execute("""SELECT count(*) FROM public.pr_owned_posts p WHERE p.workspace_id=%s AND p.source='history_import'
                         AND EXISTS (SELECT 1 FROM public.pr_channel_capabilities c WHERE c.workspace_id=p.workspace_id
                                     AND c.connection_id=p.connection_id AND c.capability='analytics' AND c.level='Direct')
                         AND NOT EXISTS (SELECT 1 FROM public.pr_growth_purges g WHERE g.workspace_id=p.workspace_id
                                         AND g.connection_id=p.connection_id)""", (workspace_id,))
        history = int(cur.fetchone()[0] or 0)
    consent = state.get("growthConsent") or {}
    used = {}
    if "pr_growth_budgets" in tables:
        day = time.strftime("%Y-%m-%d", time.gmtime(growth.clock()))
        scopes = [f"{workspace_id}:{kind}" for kind in DAILY_RUNS]
        cur.execute("SELECT scope,calls FROM public.pr_growth_budgets WHERE scope=ANY(%s) AND day=%s", (scopes, day))
        for scope, calls in cur.fetchall():
            kind = scope.rsplit(":", 1)[-1]
            used[kind] = int(calls or 0) >= DAILY_RUNS.get(kind, 0)
    owned_comment_posts = eligible_comments = 0
    if flags["audience"] and set(AUDIENCE_TABLES) <= tables:
        sources = growth.closed_loop.comment_sources(cur, workspace_id, state)
        owned_comment_posts = len(sources["ownedDirect"])
        eligible_comments = len(growth.closed_loop._comments(cur, workspace_id, state, 30)) if owned_comment_posts else 0
    cohort = 0
    if flags["postmortem"] and set(RESULT_TABLES) <= tables:
        cur.execute("SELECT count(*) FROM public.pr_predictions WHERE workspace_id=%s", (workspace_id,))
        cohort = int(cur.fetchone()[0] or 0)
        if cohort >= MINIMUM_POSTS:   # an upper bound is enough below the minimum; compute the real cohort above it
            cohort = growth.closed_loop.largest_cohort(cur, workspace_id, state)
    last = None
    if "pr_metric_observations" in tables:
        cur.execute("SELECT max(observed_at) FROM public.pr_metric_observations WHERE workspace_id=%s AND availability='available'", (workspace_id,))
        last = cur.fetchone()[0]
    return {"flags": flags, "tables": tables, "role": membership.role, "canEdit": membership.allows("edit"),
            "canManageConnections": membership.allows("manage_connections"),
            "connections": len(channels), "analyticsDirect": len(analytics), "commentsDirect": len(comments),
            "measurement": measurement_admission(growth, cur, workspace_id),
            "verifiedPublications": len(verified_publications(state)), "historyPosts": history,
            "ownedCommentPosts": owned_comment_posts, "eligibleComments": eligible_comments,
            "consent": {"summary": SUMMARY_ROUTE in (consent.get("routes") or []), "audience": consent.get("audience") is True},
            "capsConfigured": _caps_configured(growth), "dailyUsed": used, "largestCohort": cohort, "lastReadAt": last}

"""The `data` shape of every read binding (rafii-genui/1): top-level keys and, for lists, the keys of each row.

This is a contract with lane E (journey components safe-parse these keys) and is checked against the handlers' real output
in tests (unit fixtures and the PostgreSQL scenarios). A key is added, never renamed or removed, without telling A.
`data` is null for `denied`/`unavailable` results.
"""
from __future__ import annotations

_DRAFT_ROW = ("draftId ref platform language account channelId revision characters limit overLimit needsReview hasProposedUpdate committed committedJobState "
              "setAside sourceCount warningsCount unknownsCount writerModel voice fromAutomation createdAt excerpt href")
_JOB_VIEW = "jobId state title meaning steps platform account publishAt timeZone attempts demo fromAutomation verified providerReference lastEvent"
_CAMPAIGN_VIEW = "campaignId goal audience status missingFacts facts automations platforms href"
_LIB_ROW = ("ref assetId store kind title mime extension bytes createdAt tags collections processing indexingStatus transcriptionStatus hasSource sourceId duplicateOf "
            "extractionProblem width height duration alt href previewKind previewRoute")
_SAMPLE_ROW = "sourceId ref title platform language label origin active selected revision characters excerpt useGrants grantRevision partialCoverage publishedAt retainedAt permalink revoked"
_AUTOMATION_ROW = "automationId ref name status schedule timeZone policy platforms nextRun nextPublish campaignId pausedReason version href"


def _s(keys: str, **lists: str) -> dict:
    return {"keys": keys.split(), "lists": {name: value.split() for name, value in lists.items()}}


SHAPES: dict[str, dict] = {
    # J01
    "drafts_list": _s("drafts offset missingIds", drafts=_DRAFT_ROW),
    "draft_read": _s(_DRAFT_ROW + " text openings selectedOpening unknowns warnings blockedByRetraction proposedUpdate scheduled editable editBlockedReason "
                     "voiceSourceCount revisionsCount", scheduled=_JOB_VIEW),
    "draft_evidence": _s("draftId edges sources voiceFit",
                         sources="sourceId ref available kind title active retracted approvedFacts facts origin host published fetchedAt"),
    "draft_revisions": _s("draftId current revisions offset", revisions="revision origin at characters text textTruncated"),
    "writers_list": _s("models selected workspaceDefault", models="id label qualified costClass route detail"),
    # J02
    "calendar_agenda": _s("range entries offset total statusCounts unknownStates days daysNote derived href",
                          entries="kind id ref state status title platform account channelId atUtc local offset timeZone jobZone jobLocal fromAutomation excerpt href",
                          days="date weekday count"),
    "queue_status": _s("statusCounts unknownStates draftsUnscheduled waitingApproval upcoming attention totals href",
                       waitingApproval="reviewId ref platform account local timeZone atUtc expired", upcoming=_JOB_VIEW + " ref atUtc", attention=_JOB_VIEW + " ref"),
    "job_detail": _s("kind ref"),
    "slot_check": _s("draftId jobId platform account channelId local timeZone atUtc valid problems collisions rule",
                     collisions="kind id ref local minutesApart status"),
    "open_proposals": _s("proposals conversationId applyWith", proposals="proposalId messageId type summary digest expiresAt requiredPermission status view"),
    # J03
    "library_search": _s("items offset storage capabilities legacyMedia", items=_LIB_ROW),
    "library_item": _s(_LIB_ROW + " excerpt chunkCount mediaConsent"),
    "library_lineage": _s("assetId store edges"),
    "library_collections": _s("collections", collections="collectionId name count"),
    "library_selection": _s("attachments references refused note", attachments="assetId role", references="kind id", refused="assetId reason"),
    # J04
    "voice_sources": _s("samples offset eligibility", samples=_SAMPLE_ROW),
    "voice_profile_state": _s("approved proposed revisions derived note href"),
    "voice_preferences": _s("pending recent recentTotal learned versions settings stats rule",
                            learned="id type ruleKey polarity scope statement applyWhen evidenceState evidenceSummary source status since"),
    "voice_consent": _s("cloudMemory samples learning media webResearch owner rule href"),
    "voice_learning_status": _s("enabled eventsWaiting pendingProposals newestProposalAt extractor lastRun lastRunNote rule"),
    # J05
    "campaigns_list": _s("campaigns offset", campaigns=_CAMPAIGN_VIEW + " ref version itemCount createdAt updatedAt"),
    "campaign_detail": _s(_CAMPAIGN_VIEW + " drafts draftCount posts lastWeek upcomingRuns derived ref version accountIds itemCount progress note"),
    "campaign_items": _s("campaignId version items offset max", items="itemId kind addedAt needsReview addedByYou"),
    "campaign_timeline": _s("campaignId timeZone startUtc endUtc events truncated", events="kind atUtc local status"),
    "task_progress": _s("task summary rule"),
    # J06
    "analytics_posts": _s("posts offset timeZone startUtc endUtc families rules definitionVersion undated verifiedPostsInWindow postsWithReadings",
                          posts="ref jobId provider platform connectionId providerPostId language publishedAt publishedLocal contentOrigin metrics rates cohort freshness"),
    "analytics_compare": _s("metric basis comparisons rules startUtc endUtc timeZone undated", comparisons="cohort metric interpretation jobIds"),
    "analytics_series": _s("metric bucket timeZone series definitionVersion unit rule undated", series="provider platform connectionId points"),
    "analytics_coverage": _s("state connections unmatchedReadings usesPlatformFallback rule",
                             connections="connectionId platform account level direct providerOffersAnalytics verifiedPosts readPosts readings lastObservedAt evidence enableHref"),
    "post_feedback": _s("jobId readings minimumBaselinePosts causal"),
    # J07
    "research_state": _s("allowed web enabledOnDeployment hosted decidedAt processors canTurnOn guide reason"),
    "research_results": _s("pages recorded searches note", pages="index title host url urlUnsafe published publishedLabel fetchedAt facts untrusted"),
    "research_sources": _s("sources offset", sources="sourceId ref title host url published publishedLabel fetchedAt status active retracted facts approvedFacts"),
    # J08
    "automations_list": _s("automations offset statusCounts", automations=_AUTOMATION_ROW),
    "automation_detail": _s("taskId name status scheduleText policy plan platforms needs contentLabel voiceMode ref timeZone nextRun nextPublish upcoming version "
                            "campaignId pausedReason history href", upcoming="atUtc local offset"),
    "automation_history": _s("automationId runs offset", runs="runId ref status attention scheduledUtc scheduledLocal timeZone completedUtc seen cost items"),
    "connections_status": _s("accounts publishingLive attention recovery rule",
                             accounts="connectionId platform account connectionState readiness demo revoked levels canPublish publishCode publishReason ref needsReconnect"),
    "recovery_guides": _s("guides pages", guides="guideId title summary href page canOpen reason"),
    # J09 (founder scope): the founder tools' own result keys
    "founder_metrics": _s("mode receiptId dataState rows coverage executionState warnings interval note"),
    "founder_costs": _s("mode receiptId dataState rows coverage"),
    "founder_attention": _s("mode items"),
    "founder_sources": _s("mode sources"),
    "founder_incident": _s("incident"),
    "founder_search": _s("mode collection rows"),
    "founder_entity": _s("collection record links"),
}

# Bindings whose `data` is the existing tool's own record (site-agent `job.get`, founder tools): only the keys listed are
# guaranteed; others may appear.
OPEN_SHAPES = {"job_detail", "founder_metrics", "founder_costs", "founder_attention", "founder_sources", "founder_incident", "founder_search", "founder_entity"}

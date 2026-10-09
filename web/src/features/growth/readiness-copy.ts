import type { AudienceReason } from '@/lib/growth/types';

// Growth Studio's own reason copy for the shared readiness notice (CONTRACTS.md §1: each feature keeps its reason
// copy next to its UI). Rules: an outage or a missing spending limit never tells anyone to reconnect; admission and
// enrollment are owner decisions, never a connection problem; missing data stays missing.
type Copy = { title: string; detail: string };

export const GROWTH_REASON_COPY: Record<string, Copy> = {
  growth_off: {
    title: 'Growth Studio is switched off on this service.',
    detail: 'Your drafts, publishing and existing analytics still work. Nothing you do here will change that.'
  },
  postmortem_off: {
    title: 'Results are switched off on this service.',
    detail: 'Your drafts and existing analytics still work. Audience and other Growth tabs may still be available.'
  },
  audience_off: {
    title: 'Audience insights are switched off on this service.',
    detail: 'Your inbox still works as usual. Results and Patterns may still be available.'
  },
  genome_off: {
    title: 'Saving lessons to your Genome is switched off here.',
    detail: 'Reviews and readings still work; a lesson stays an observation.'
  },
  growth_schema_unavailable: {
    title: 'Growth Studio is still being set up here.',
    detail: 'Nothing is wrong with your account or connections. Your drafts and analytics are unaffected; check back shortly.'
  },
  analytics_connection_required: {
    title: 'Native post analytics are unavailable.',
    detail: 'Connect an owned Threads or Instagram account with analytics permission so Rafii can read your published posts.'
  },
  analytics_permission_required: {
    title: 'This account has not allowed post analytics.',
    detail: 'Your Threads or Instagram account is connected, but without native analytics permission. Allow analytics in Accounts to start readings.'
  },
  comments_permission_required: {
    title: 'This account has not allowed comment reading.',
    detail: 'Comments on your own posts can only be read through an account that allows it. Allow comment reading in Accounts.'
  },
  measurement_enrollment_required: {
    title: 'Turn on post readings for this workspace.',
    detail: 'Rafii can read your own posts’ native metrics at publish, one hour, one day and one week. No AI, no cost, nothing is posted.'
  },
  measurement_paused: {
    title: 'Post readings are paused for this workspace.',
    detail: 'New readings are not being collected here right now. Readings already taken stay visible; missing windows stay missing.'
  },
  measurement_off: {
    title: 'Post readings are switched off on this service.',
    detail: 'No new native readings are being collected anywhere right now. Readings already taken stay visible.'
  },
  no_verified_publications: {
    title: 'Your first field note is still ahead.',
    detail: 'After a post is published through Rafii and verified, or your own history is imported, its readings appear here.'
  },
  no_comments: {
    title: 'No comments to listen to yet.',
    detail: 'Comments on your own Threads and Instagram posts appear here as they arrive, for up to 30 days after publishing.'
  },
  sample_below_minimum: {
    title: 'Patterns need more comparable posts.',
    detail: 'A personal calibration needs fifty comparable publications with a pre-publish check and an official one-day reading. Until then, nothing is personalized.'
  },
  growth_consent_required: {
    title: 'AI reviews need the owner’s permission.',
    detail: 'Reading results works now. Reviewing them with AI needs the workspace owner to allow the models first.'
  },
  role_edit_required: {
    title: 'You can read everything here.',
    detail: 'Running a review or an analysis needs editor access in this workspace.'
  },
  growth_budget_unconfigured: {
    title: 'AI reviews are paused.',
    detail: 'Readings and results still work. AI reviews and audience analysis wait until a daily spending limit is set for this service.'
  },
  growth_daily_limit: {
    title: 'Today’s AI allowance is used.',
    detail: 'Readings still work. AI reviews resume tomorrow.'
  }
};

export const AUDIENCE_REASON_COPY: Record<AudienceReason, Copy> = {
  no_connection: {
    title: 'Connect an account to hear your audience.',
    detail: 'Audience insights read comments on your own Threads and Instagram posts.'
  },
  comments_permission_required: GROWTH_REASON_COPY.comments_permission_required,
  no_owned_posts: {
    title: 'No posts to listen to yet.',
    detail: 'Comments are read only on posts published through Rafii or on your own imported history.'
  },
  no_comments: GROWTH_REASON_COPY.no_comments,
  growth_consent_required: {
    title: 'Comment analysis needs the owner’s permission.',
    detail: 'The workspace owner can allow comment analysis in AI permissions. Author handles are never sent.'
  }
};

export const MEASUREMENT_REASON_COPY: Record<string, string> = {
  enrollment_open: 'Post readings are available for this workspace. Turning them on is free and never posts anything.',
  already_enrolled: 'Post readings are on for this workspace.',
  reviewed_cohort: 'Post readings are on for this workspace as part of early access.',
  self_serve_paused: 'New workspaces cannot turn on post readings right now. Nothing is lost; you can try again later.',
  cohort_full: 'The early-access group for post readings is full right now. You can try again later.',
  workspace_not_eligible: 'Post readings are not available for this workspace.',
  enrollment_unavailable: 'Post readings are still being set up here. Check back shortly.'
};

type ErrorLike = { status?: number; code?: string } | null | undefined;

/**
 * Which request key to send next after a paid request ended with `error`.
 * - A run that finished without a result (growth_request_failed), a key reused for other input, or an input that
 *   changed: start a fresh key so the person's next, explicit confirmation is a new attempt.
 * - An uncertain outcome (growth_request_unknown), a run still in progress, a network error or any refusal made
 *   before a run started: keep the key, so a double click or a refresh can never pay twice.
 */
export function requestKeyAfterError(current: string | null, error: unknown): string | null {
  const e = (error ?? null) as ErrorLike;
  const code = e && typeof e === 'object' ? e.code : undefined;
  if (code === 'growth_request_unknown' || code === 'growth_request_pending') return current;
  if (code === 'growth_request_failed' || code === 'growth_key_conflict' || code === 'growth_input_changed') return null;
  return current;
}

export function requestErrorMessage(error: unknown, fallback: string) {
  const code = error && typeof error === 'object' ? (error as ErrorLike)?.code : undefined;
  if (code === 'growth_request_unknown') return 'The outcome of this request is uncertain. Nothing was sent again, and nothing will be retried automatically.';
  if (code === 'growth_request_failed') return 'This request did not finish and nothing was used. You can try again.';
  if (code === 'growth_request_pending') return 'This request is still running. Wait a moment before checking again.';
  return error instanceof Error && error.message ? error.message : fallback;
}

/** A measured zero is shown as 0; a value that was not read is an em dash, never zero. */
export function metricValue(value: number | null | undefined) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString() : '—';
}

/** "23 minutes", "5 hours", "3 days": the age a lifetime reading was taken at. */
export function ageLabel(seconds: number | null | undefined) {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds) || seconds < 0) return null;
  const minutes = Math.max(1, Math.round(seconds / 60));
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  const hours = Math.round(seconds / 3600);
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'}`;
  const days = Math.round(seconds / 86400);
  return `${days} day${days === 1 ? '' : 's'}`;
}

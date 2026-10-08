/**
 * Journey component specs (lane E): name, description and positional Zod props for every Rafii journey component.
 *
 * No React here, and only erasable TypeScript, so the OpenUI asset generator can build the library JSON schema and the
 * per-journey prompts from exactly the objects `library.tsx` attaches renderers to (the renderers live in
 * `components/journeys/`). Positional order is the Zod key order: required props first, optional last.
 *
 * Conventions the server validator relies on:
 *   - `data` is a reference to a `Query(...)` statement; the component reads the UiQueryResultV1 envelope it resolves to.
 *   - A write-capable component names its server action ids as literals in `actionId` (one) or `actions` (several). The
 *     ids must be in the turn's manifest; the component only asks the action bridge, which shows the native confirmation.
 *   - Selection and filter props are `$binding`s, so picking, filtering and switching periods never call a model.
 *
 * The founder library (J09) is separate: `FOUNDER_JOURNEY_SPECS` never enters the consumer library or its prompts.
 */
import { markReactive } from '@openuidev/lang-core';
import { z } from 'zod';

/** `reactive()` without importing the React runtime: the same marker react-lang's `reactive` sets. */
function reactive<T extends z.ZodType>(schema: T): T {
  markReactive(schema);
  return schema;
}

export interface JourneyComponentSpec {
  name: string;
  description: string;
  props: z.ZodObject;
}

const data = (binding: string) => z.any().describe(`Reference to a Query("${binding}", ...) statement.`);
const title = () => z.string().max(120).optional().describe('Short heading in the person’s language.');
// Describe before marking: zod's describe() returns a new schema, and the reactive marker must sit on the final object.
const bound = <T extends z.ZodType>(schema: T, description: string) => reactive(schema.describe(description) as T);
const selectionList = (description = 'Bind to a $selected\u2026 variable: picked refs in displayed order.') =>
  bound(z.array(z.string().max(160)).max(20).optional(), description);
const selectionOne = (description = 'Bind to a $selected\u2026 variable holding one ref.') => bound(z.string().max(160).optional(), description);

export const PERIODS = {
  calendar: ['this_week', 'next_week', 'this_month', 'next_month'],
  analytics: ['last_7_days', 'last_30_days', 'last_90_days', 'this_month', 'last_month'],
  plan: ['next_7_days', 'next_30_days', 'this_month', 'next_month'],
  founder: ['last_7_days', 'last_30_days', 'last_90_days', 'this_month', 'last_month', 'last_365_days'],
} as const;

export const ANALYTICS_METRICS = ['views', 'reach', 'likes', 'comments', 'replies', 'reposts', 'quotes', 'shares', 'saved'] as const;

/** Shown in every library: model-written explanation kept visually apart from stored facts. */
export const JOURNEY_COMMON_SPECS: JourneyComponentSpec[] = [
  {
    name: 'Commentary',
    description: 'Your short explanation, shown apart from stored records and labelled as Rafii’s note. Never put numbers, dates or titles here that a query did not return.',
    props: z.object({ text: z.string().min(1).max(600) }),
  },
];

export const CONSUMER_JOURNEY_SPECS: JourneyComponentSpec[] = [
  // J01 — drafts
  {
    name: 'DraftList',
    description: 'Drafts from a drafts_list query: platform, language, length against the platform limit, review and scheduling state. Bind status to the query\u2019s $status; picking rows only selects them.',
    props: z.object({
      data: data('drafts_list'),
      selected: selectionList(),
      status: bound(z.enum(['all', 'unscheduled', 'scheduled', 'needs_review']).optional(), 'Bind to $status.'),
      title: title(),
    }),
  },
  {
    name: 'DraftCompare',
    description: 'Side-by-side comparison of 2-4 drafts from a drafts_compare query (pass draftRefs: $selectedDrafts).',
    props: z.object({ data: data('drafts_compare'), title: title() }),
  },
  {
    name: 'PlatformPreviewCard',
    description: 'One draft from a draft_read query as it will read on its platform, with limit, open questions and warnings.',
    props: z.object({ data: data('draft_read') }),
  },
  {
    name: 'DraftEvidence',
    description: 'Sources, lineage and voice findings behind one draft from a draft_evidence query.',
    props: z.object({ data: data('draft_evidence') }),
  },
  {
    name: 'DraftEditor',
    description: 'Edit the text of one unscheduled draft (draft_read query). Saving asks for confirmation; scheduled drafts cannot be edited here.',
    props: z.object({ data: data('draft_read'), actionId: z.enum(['draft_edit']) }),
  },
  // J02 — calendar
  {
    name: 'CalendarAgenda',
    description: 'Agenda of scheduled, waiting and published posts from a calendar_agenda query, with times in their zone and close-together warnings. Bind period to the query’s $period and selected to $selectedEntry.',
    props: z.object({
      data: data('calendar_agenda'),
      period: bound(z.enum(PERIODS.calendar).optional(), 'Bind to $period.'),
      selected: selectionOne(),
      title: title(),
    }),
  },
  {
    name: 'QueueStatus',
    description: 'Publishing queue counts and the items needing attention from a queue_status query. Unknown states are counted separately.',
    props: z.object({ data: data('queue_status') }),
  },
  {
    name: 'SlotCheck',
    description: 'Whether a chosen local time is valid and which nearby posts on the same account it collides with (schedule_slot_check query).',
    props: z.object({ data: data('schedule_slot_check') }),
  },
  {
    name: 'RescheduleForm',
    description: 'Pick a local date, time and zone for the selected draft or post and prepare a schedule proposal. Nothing is scheduled until the person applies it in review.',
    props: z.object({
      actionId: z.enum(['schedule_prepare']),
      target: selectionOne('Bind to $selectedEntry (a draft or post ref).'),
      when: bound(z.string().max(16).optional(), 'Bind to $when (YYYY-MM-DDTHH:MM, chosen by the person).'),
      zone: bound(z.string().max(64).optional(), 'Bind to $zone.'),
      check: z.any().optional().describe('Optional reference to the schedule_slot_check Query for the same $when.'),
    }),
  },
  // J03 — library
  {
    name: 'LibraryBrowser',
    description: 'Searchable Library results from a library_search query with real previews. Bind query to $q and kind to $kind for local filtering; picking files only selects them.',
    props: z.object({
      data: data('library_search'),
      selected: selectionList(),
      query: bound(z.string().max(120).optional(), 'Bind to $q.'),
      kind: bound(z.enum(['all', 'image', 'video', 'audio', 'document', 'file']).optional(), 'Bind to $kind.'),
      title: title(),
    }),
  },
  {
    name: 'LibraryAssetCard',
    description: 'One Library file from a library_item query: preview, type, processing state and whether it is already a draft source.',
    props: z.object({ data: data('library_item'), actionId: z.enum(['library_use_as_source']).optional() }),
  },
  {
    name: 'LibraryLineage',
    description: 'Where a Library file came from and what was made from it (library_lineage query).',
    props: z.object({ data: data('library_lineage') }),
  },
  // J04 — voice
  {
    name: 'VoiceSourcePicker',
    description: 'Writing samples from a voice_sources query with eligibility and cloud permission per sample. Picking samples only selects them for analysis.',
    props: z.object({
      data: data('voice_sources'),
      selected: selectionList(),
      actions: z.array(z.enum(['voice_sample_select', 'voice_profile_analyze'])).max(2).optional(),
    }),
  },
  {
    name: 'VoiceProfileReview',
    description: 'The approved voice in effect next to the proposed profile, each dimension with its evidence level (voice_profile query).',
    props: z.object({ data: data('voice_profile'), actions: z.array(z.enum(['voice_profile_approve'])).max(1).optional() }),
  },
  {
    name: 'VoicePreferenceList',
    description: 'Learned preferences in effect and pending proposals with their evidence (voice_preferences query).',
    props: z.object({ data: data('voice_preferences'), actions: z.array(z.enum(['voice_preference_decide'])).max(1).optional() }),
  },
  {
    name: 'VoiceLearningStatus',
    description: 'Whether learning is on, cloud consent, and the derived state of pending learning (voice_learning_status query).',
    props: z.object({ data: data('voice_learning_status') }),
  },
  // J05 — campaigns
  {
    name: 'CampaignPlanTable',
    description: 'A campaign’s goal, missing facts, linked content and automations from a campaign_detail query. Picking rows only selects them.',
    props: z.object({
      data: data('campaign_detail'),
      selected: selectionList(),
      actions: z.array(z.enum(['campaign_link'])).max(1).optional(),
      link: bound(z.array(z.string().max(160)).max(20).optional(), 'Optional: bind to $selectedDrafts to offer linking them.'),
    }),
  },
  {
    name: 'CampaignTimeline',
    description: 'Upcoming runs, scheduled posts and linked items of a campaign over a period (campaign_timeline query), each time with its zone.',
    props: z.object({ data: data('campaign_timeline'), title: title() }),
  },
  {
    name: 'CampaignProgress',
    description: 'Steps of the current multi-step task from a task_progress query: done, open, blocked and failed, with reasons.',
    props: z.object({ data: data('task_progress') }),
  },
  {
    name: 'CampaignBriefForm',
    description: 'Goal and audience form that creates a campaign after confirmation.',
    props: z.object({ actionId: z.enum(['campaign_create']) }),
  },
  // J06 — analytics
  {
    name: 'MetricTable',
    description: 'Post metrics from an analytics_posts query: stored readings with unit, as-of time and Unavailable for missing values. Bind period/platform to the query’s variables.',
    props: z.object({
      data: data('analytics_posts'),
      metrics: z.array(z.enum(ANALYTICS_METRICS)).min(1).max(6).optional(),
      period: bound(z.enum(PERIODS.analytics).optional(), 'Bind to $period.'),
      platform: bound(z.string().max(40).optional(), 'Bind to $platform.'),
      selected: selectionList(),
    }),
  },
  {
    name: 'MetricChart',
    description: 'Line or bar chart of one metric over time from an analytics_series query. Buckets without readings are gaps, never zero.',
    props: z.object({ data: data('analytics_series'), kind: z.enum(['line', 'bar']).optional(), title: title() }),
  },
  {
    name: 'ComparisonSummary',
    description: 'Like-for-like comparison from an analytics_compare query with sample size, minimum and the rule used. Never claims a cause.',
    props: z.object({ data: data('analytics_compare') }),
  },
  {
    name: 'CoverageNote',
    description: 'Which accounts report analytics, what is missing and why (analytics_coverage query).',
    props: z.object({ data: data('analytics_coverage') }),
  },
  // J07 — research
  {
    name: 'ResearchStatus',
    description: 'Whether web research is on for this workspace and who can turn it on (research_state query).',
    props: z.object({ data: data('research_state') }),
  },
  {
    name: 'ResearchBrief',
    description: 'Sources found for the request with their facts and dates (research_results query). Picking sources only selects them.',
    props: z.object({
      data: data('research_results'),
      selected: selectionList(),
      actions: z.array(z.enum(['research_save_sources'])).max(1).optional(),
      title: title(),
    }),
  },
  {
    name: 'CitationList',
    description: 'Numbered citations with host, publication date (or no date) and fetch time (research_results query).',
    props: z.object({ data: data('research_results') }),
  },
  {
    name: 'ComparisonMatrix',
    description: 'Sources side by side: host, date and the facts each states (research_results query). Selection narrows the columns.',
    props: z.object({ data: data('research_results'), selected: selectionList() }),
  },
  // J08 — automations
  {
    name: 'AutomationSchedule',
    description: 'Automations from an automations_list query with status, schedule, policy and next run in its time zone. Picking one only selects it.',
    props: z.object({ data: data('automations_list'), selected: selectionOne() }),
  },
  {
    name: 'RunHistory',
    description: 'Recent runs of one automation from an automation_runs query: stage, item states and reasons.',
    props: z.object({ data: data('automation_runs') }),
  },
  {
    name: 'ConnectionRecoveryGuide',
    description: 'Connected accounts that need attention from a connections_status query, each with the in-app way to fix it.',
    props: z.object({ data: data('connections_status') }),
  },
  {
    name: 'AutomationChangeForm',
    description: 'Describe a change to the selected automation and prepare it as a proposal for review.',
    props: z.object({ actionId: z.enum(['automation_change_prepare']), automation: selectionOne('Bind to $selectedAutomation.') }),
  },
];

export const FOUNDER_JOURNEY_SPECS: JourneyComponentSpec[] = [
  {
    name: 'FounderRevenueSummary',
    description: 'Revenue metrics from a founder_metric_query: values per currency with period, coverage and receipts. Unavailable metrics stay unavailable.',
    props: z.object({ data: data('founder_metric_query'), selected: selectionOne(), title: title() }),
  },
  {
    name: 'FounderCostBreakdown',
    description: 'AI cost by one dimension from a founder_cost_breakdown query, with unknown cost kept separate.',
    props: z.object({ data: data('founder_cost_breakdown'), title: title() }),
  },
  {
    name: 'FounderReliabilityPanel',
    description: 'Error rate, latency, queue and connection health, and open incidents from a founder_reliability query.',
    props: z.object({ data: data('founder_reliability') }),
  },
  {
    name: 'FounderSupportQueue',
    description: 'Support tickets by status and age from a founder_support_queue query, identities masked.',
    props: z.object({ data: data('founder_support_queue') }),
  },
];

/** Every component that offers an action, with the ids it may name (used by tests and the validator policy). */
export function actionIdsOf(spec: JourneyComponentSpec): string[] {
  const shape = spec.props.shape as Record<string, z.ZodType>;
  const ids: string[] = [];
  const collect = (schema: z.ZodType | undefined) => {
    if (!schema) return;
    const def = (schema as unknown as { def?: { type?: string; innerType?: z.ZodType; element?: z.ZodType; entries?: Record<string, string> } }).def;
    if (!def) return;
    if (def.type === 'optional' && def.innerType) return collect(def.innerType);
    if (def.type === 'array' && def.element) return collect(def.element);
    if (def.type === 'enum' && def.entries) ids.push(...Object.values(def.entries));
  };
  collect(shape.actionId);
  collect(shape.actions);
  return ids;
}

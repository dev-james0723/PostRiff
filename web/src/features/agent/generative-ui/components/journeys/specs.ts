/**
 * Journey component specs (lane E): name, description and positional props of every Rafii journey component, and the
 * per-journey component groups. This is lane C's extension seam (`component-specs.ts` → `JourneySpecModule`); C's
 * `library-registry.ts` merges these with the primitives into the consumer and founder libraries, prompts and hashes.
 *
 * React-free, erasable TypeScript only (the asset generator and the trusted validator load it). Renderers live in
 * `renderers.tsx` (consumer) and `founder-renderers.tsx` (founder, separate chunk).
 *
 * Conventions the validator and the components rely on:
 *   - `data` is a direct reference to a top-level `Query("<binding>", …)` statement (rule `query`). The component shows
 *     only what that result holds and names the binding it expects in its description.
 *   - Write-capable components name exactly one server action id as a literal (`actionId`, rule `action-id`). The
 *     component asks the action bridge; the server builds the confirmation; nothing runs without a confirmed click.
 *   - Selections, filters and form fields are `$binding`s: picking, typing and switching never call a model.
 *   - Selection `$variables` hold the record ids the binding's own arguments take (draft ids, job ids, …), in the order
 *     the person picked them.
 */
import { z } from 'zod';
import { bindable, queryRef, type JourneySpecModule, type RafiiComponentSpec, type RafiiGroupSpec } from '../../component-specs';

const query = { data: 'query' } as const;
const queryAndAction = { data: 'query', actionId: 'action-id' } as const;
const title = () => z.string().optional();
const selectionList = () => bindable(z.array(z.string()).optional());
const selectionOne = () => bindable(z.string().optional());

// --- common ------------------------------------------------------------------------------------------------------------
const Commentary: RafiiComponentSpec = {
  name: 'Commentary',
  description:
    'Your own short explanation, shown apart from the records and labelled as Rafii’s note. Never put figures, dates, titles or statuses in it: those come from bound components.',
  props: z.object({ text: z.string() }),
};

// --- J01 drafts --------------------------------------------------------------------------------------------------------
const DraftList: RafiiComponentSpec = {
  name: 'DraftList',
  description:
    'Drafts from a drafts_list Query: platform, language, length against the platform limit, review and queue state. Bind selected to a $variable (draft ids, in the order picked). Picking only selects.',
  props: z.object({ data: queryRef, selected: selectionList(), title: title() }),
  rules: query,
};
const DraftCompare: RafiiComponentSpec = {
  name: 'DraftCompare',
  description:
    'Two to four drafts side by side from a drafts_list Query whose ids argument is the selection $variable, in the order picked.',
  props: z.object({ data: queryRef, title: title() }),
  rules: query,
};
const DraftDetail: RafiiComponentSpec = {
  name: 'DraftDetail',
  description:
    'One draft from a draft_read Query as it will read on its platform: full text, length against the limit, open questions, warnings, a waiting rewrite and its queue state.',
  props: z.object({ data: queryRef }),
  rules: query,
};
const DraftEvidence: RafiiComponentSpec = {
  name: 'DraftEvidence',
  description: 'Where one draft came from (draft_evidence Query): its sources with approved facts, linked records and the voice check.',
  props: z.object({ data: queryRef }),
  rules: query,
};
const DraftEditor: RafiiComponentSpec = {
  name: 'DraftEditor',
  description:
    'Edit the text of one unscheduled draft from a draft_read Query. name is the form field name. Saving shows Rafii’s confirmation; drafts already in the queue cannot be edited here.',
  props: z.object({ data: queryRef, actionId: z.enum(['draft_edit']), name: z.string() }),
  rules: queryAndAction,
  fieldNameProp: 'name',
};

// --- J02 calendar ------------------------------------------------------------------------------------------------------
const CalendarAgenda: RafiiComponentSpec = {
  name: 'CalendarAgenda',
  description:
    'Scheduled, waiting and planned posts from a calendar_agenda Query, by day, each time in its zone, with rule-labelled close-together notes. Bind selected to a $variable to pick a waiting post (job id).',
  props: z.object({ data: queryRef, selected: selectionOne(), title: title() }),
  rules: query,
};
const QueueStatus: RafiiComponentSpec = {
  name: 'QueueStatus',
  description: 'The publishing queue now (queue_status Query): waiting for approval, approved and waiting for their time, needing attention.',
  props: z.object({ data: queryRef }),
  rules: query,
};
const SlotCheck: RafiiComponentSpec = {
  name: 'SlotCheck',
  description: 'Whether a chosen local time works and which posts on the same account are less than 2 hours away (slot_check Query). Read only.',
  props: z.object({ data: queryRef }),
  rules: query,
};
const RescheduleForm: RafiiComponentSpec = {
  name: 'RescheduleForm',
  description:
    'Pick a local date and time for a waiting post (jobId) or a draft (draftId) and prepare a schedule proposal. when is a $variable "YYYY-MM-DDTHH:MM", zone a $variable with the IANA zone. Nothing is scheduled until the person applies the proposal on its card.',
  props: z.object({
    actionId: z.enum(['schedule_prepare']),
    target: z.enum(['job', 'draft']),
    targetId: selectionOne(),
    when: bindable(z.string().optional()),
    zone: bindable(z.string().optional()),
  }),
  rules: { actionId: 'action-id' },
};
const ProposalList: RafiiComponentSpec = {
  name: 'ProposalList',
  description: 'Proposals in this conversation still waiting for the person (open_proposals Query). They are applied only on their own card.',
  props: z.object({ data: queryRef }),
  rules: query,
};

export const CONSUMER_JOURNEY_SPECS: readonly RafiiComponentSpec[] = [
  Commentary,
  DraftList,
  DraftCompare,
  DraftDetail,
  DraftEvidence,
  DraftEditor,
  CalendarAgenda,
  QueueStatus,
  SlotCheck,
  RescheduleForm,
  ProposalList,
];

export const CONSUMER_JOURNEY_GROUPS: readonly RafiiGroupSpec[] = [
  {
    id: 'journey_common',
    name: 'Rafii’s note',
    components: ['Commentary'],
    notes: ['Commentary is your explanation only. Records, figures and statuses always come from bound components.'],
  },
  {
    id: 'drafts',
    name: 'Drafts',
    components: ['DraftList', 'DraftCompare', 'DraftDetail', 'DraftEvidence', 'DraftEditor'],
    notes: [
      'To compare picked drafts: picks = Query("drafts_list", {ids: $selectedDrafts}, null) and DraftCompare(picks).',
      'Selecting a draft is not approval. For a rewrite or another platform, offer Button("…", Action([@ToAssistant("…")])) so the person asks in the conversation.',
    ],
  },
  {
    id: 'calendar',
    name: 'Calendar and queue',
    components: ['CalendarAgenda', 'QueueStatus', 'SlotCheck', 'RescheduleForm', 'ProposalList'],
    notes: [
      'Pass the person’s time zone to calendar_agenda and slot_check. Dates are YYYY-MM-DD; local times YYYY-MM-DDTHH:MM.',
      'RescheduleForm only prepares a proposal. Applying it happens on the proposal’s own card, never in this view.',
    ],
  },
];

/** Founder (J09) components: a separate library; names never repeat consumer names (registryProblems checks it). */
export const FOUNDER_JOURNEY_SPECS: readonly RafiiComponentSpec[] = [];
export const FOUNDER_JOURNEY_GROUPS: readonly RafiiGroupSpec[] = [];

/** Journey → E's group ids appended after C's core groups, in prompt order. */
export const JOURNEY_GROUPS: JourneySpecModule['journeys'] = {
  J01: ['journey_common', 'drafts'],
  J02: ['journey_common', 'calendar'],
};

export const JOURNEY_SPEC_MODULE: JourneySpecModule = {
  consumer: { specs: CONSUMER_JOURNEY_SPECS, groups: CONSUMER_JOURNEY_GROUPS },
  founder: { specs: FOUNDER_JOURNEY_SPECS, groups: FOUNDER_JOURNEY_GROUPS },
  journeys: JOURNEY_GROUPS,
};

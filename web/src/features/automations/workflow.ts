/**
 * Plain words for a Raffi workflow (orchestration §1–§2): the publishing policy, when each stage happens, what research
 * looks for and what a run found. Pure and display-only; the server decides and enforces every one of these.
 */
import type { AutomationResearch, AutomationWhen, AutomationWorkflow, RecurringOccurrence, RunItem, RunResearch } from '@/lib/api/types';
import { runLabel, timeLabel } from './schedule';

export const POLICY_TEXT: Record<'auto' | 'review' | 'drafts' | 'unset', { label: string; detail: string }> = {
  auto: {
    label: 'Publishes automatically',
    detail: 'Posts that pass every safety check publish at their time. Others wait for your approval, with the reason.'
  },
  review: {
    label: 'Waits for your approval',
    detail: 'Nothing publishes until someone approves that exact draft.'
  },
  drafts: { label: 'Drafts only', detail: 'Nothing is published. Schedule the drafts you like yourself.' },
  unset: { label: 'Not chosen yet', detail: 'Tell Rafii in chat: publish automatically, wait for approval, or drafts only.' }
};

export function policyText(policy: string | null | undefined): { label: string; detail: string } {
  return policy === 'auto' || policy === 'review' || policy === 'drafts' ? POLICY_TEXT[policy] : POLICY_TEXT.unset;
}

/** Mirrors `workflow.describe_when`, with the viewer's clock format: "the day before at 9:00 AM", "Saturday at 6:00 PM". */
export function whenText(when: AutomationWhen | null | undefined, locale?: string): string {
  if (!when) return '';
  if ('at' in when) return when.at === 'anchor' ? 'at the scheduled time' : 'as soon as the drafts are written';
  if ('asap' in when) return 'right away';
  if ('weekday' in when) return `${when.weekday} at ${timeLabel(when.localTime, locale)}`;
  if ('dayOffset' in when) {
    const days = when.dayOffset;
    const at = timeLabel(when.localTime, locale);
    if (days === 0) return `the same day at ${at}`;
    if (days === -1) return `the day before at ${at}`;
    if (days === 1) return `the day after at ${at}`;
    return `${Math.abs(days)} days ${days < 0 ? 'before' : 'after'} at ${at}`;
  }
  const minutes = when.minutesOffset ?? 0;
  const whole = Math.abs(minutes) >= 60 && Math.abs(minutes) % 60 === 0;
  const hours = Math.abs(minutes) / 60;
  const span = whole ? `${hours} hour${hours === 1 ? '' : 's'}` : `${Math.abs(minutes)} minutes`;
  return `${span} ${minutes < 0 ? 'before' : 'after'}`;
}

export const STAGE_WORDS: Record<string, string> = { generate: 'Drafts', review: 'Ready for review', publish: 'Publishes' };

/** The workflow's stages as rules ("Drafts: the day before at 9:00 AM"); review only for policies that have one. */
export function stageRules(workflow: AutomationWorkflow, locale?: string): { step: 'generate' | 'review' | 'publish'; label: string; when: string }[] {
  const { generate, review, publish } = workflow.stages ?? { generate: { at: 'anchor' }, review: null, publish: null };
  const out: { step: 'generate' | 'review' | 'publish'; label: string; when: string }[] = [{ step: 'generate', label: STAGE_WORDS.generate, when: whenText(generate ?? { at: 'anchor' }, locale) }];
  if (review && workflow.policy !== 'auto' && workflow.policy !== 'drafts') out.push({ step: 'review', label: STAGE_WORDS.review, when: whenText(review, locale) });
  if (publish && workflow.policy !== 'drafts') out.push({ step: 'publish', label: STAGE_WORDS.publish, when: whenText(publish, locale) });
  return out;
}

/** One run's stage instants in the schedule's zone ("Wed 1 Oct, 9:00 AM"). */
export function runPlan(run: Pick<RecurringOccurrence, 'stages'>, timeZone: string, locale?: string): { step: 'generate' | 'review' | 'publish'; label: string; when: string }[] {
  const stages = run.stages;
  if (!stages) return [];
  const at = (seconds: number | null | undefined) => (typeof seconds === 'number' && Number.isFinite(seconds) ? runLabel(seconds * 1000, timeZone, locale) : null);
  const rows: { step: 'generate' | 'review' | 'publish'; label: string; when: string | null }[] = [
    { step: 'generate', label: STAGE_WORDS.generate, when: at(stages.generateAt) },
    { step: 'review', label: STAGE_WORDS.review, when: at(stages.reviewAt) },
    { step: 'publish', label: STAGE_WORDS.publish, when: at(stages.publishAt) }
  ];
  return rows.filter((row): row is { step: 'generate' | 'review' | 'publish'; label: string; when: string } => row.when !== null);
}

const hostOf = (url: string) => {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
};

/** What research looks for, in one line: "Looks for new research on sleep · from nature.com, bbc.co.uk · last 7 days". */
export function researchRule(research: AutomationResearch | null | undefined): string | null {
  if (!research) return null;
  const about = research.about || research.query;
  const from = research.domains?.length ? `from ${research.domains.slice(0, 4).join(', ')}${research.domains.length > 4 ? ` and ${research.domains.length - 4} more` : ''}` : research.publications ? `from ${research.publications}` : 'from reputable publishers';
  const recent = `last ${research.recencyDays ?? 7} day${(research.recencyDays ?? 7) === 1 ? '' : 's'}`;
  const nothing = research.onNothing === 'draft_without' ? 'drafts without a source when nothing is good enough' : 'skips the run when nothing is good enough';
  const links = research.urls?.length ? ` · reads ${research.urls.length} link${research.urls.length === 1 ? '' : 's'} you gave first` : '';
  const quote = research.quote ? ` · finds a quote${research.quote.about ? ` about ${research.quote.about}` : ''} and checks who said it` : '';
  return `Looks for ${about || 'something new'} ${from} · ${recent} · ${nothing}${links}${quote}`;
}

const DECISION_WORDS: Record<string, string> = {
  nothing_worth: 'Nothing found was good enough, so no source was used.',
  unavailable: 'Research was unavailable for this run.',
  skipped_by_rule: 'Research was skipped by the automation’s rules.'
};

/** What a run's research found: the chosen source (title, host, link) or why none was used. */
export function researchOutcome(research: RunResearch | null | undefined): { kind: 'chosen'; title: string; host: string; url: string } | { kind: 'none'; text: string } | null {
  if (!research) return null;
  const chosen = research.chosen;
  if (chosen?.url) return { kind: 'chosen', title: chosen.title || hostOf(chosen.url), host: chosen.host || hostOf(chosen.url), url: chosen.url };
  return { kind: 'none', text: research.reason || DECISION_WORDS[research.decision] || 'No source was used.' };
}

/** Only http(s) links are rendered as links. */
export const safeUrl = (url: string | undefined | null): string | null => (url && /^https?:\/\//i.test(url) ? url : null);

/** "LinkedIn · Studio page · English" style name for an item. */
export function itemName(item: Pick<RunItem, 'platform' | 'account'>): string {
  return item.account && item.account !== item.platform ? `${item.platform} · ${item.account}` : item.platform;
}

/**
 * Pure panel logic (no imports; tested by `site-agent.test.cjs`): page suggestions, the activity rows a turn
 * really ran, and which messages are the panel's own answers.
 */

export interface ActivityEvent {
  type: string;
  stage?: string;
  tool?: string;
  label?: string;
  status?: string;
  passages?: number;
  sufficient?: boolean;
  intent?: string;
}

export interface ActivityRow {
  key: string;
  label: string;
  status: 'done' | 'failed' | 'blocked' | 'running';
}

const SUGGESTIONS: Record<string, { read: string[]; edit?: string[] }> = {
  home: { read: ['What should I pay attention to this week?', 'What can Rafii do for me?'], edit: ['Write a LinkedIn post about what I learned this week'] },
  agent: { read: ['What did we decide in this conversation?', 'What can Rafii do for me?'] },
  overview: { read: ['What should I pay attention to this week?', 'What is waiting for my approval?'] },
  queue: { read: ["Why didn't my last post publish?", 'What is waiting for my approval?', 'What does held mean?'] },
  calendar: { read: ['What is scheduled this week?', 'Do I have gaps next week?', 'What is this page?'] },
  channels: { read: ['Which accounts can publish right now?', 'What does Assisted mean?', 'How do I reconnect an account?'] },
  automations: { read: ['What will my automations do this week?', "Why wasn't the last automation post published?"], edit: ['Pause my weekly automation for two weeks'] },
  memory: { read: ['What do you remember about my brand?', 'Can the cloud model read my memory?'] },
  brand: { read: ['What is our brand voice?', 'Who is our target audience?'] },
  billing: { read: ['How many writing batches are left?', 'Why did drafting stop?'] },
  models: { read: ['Which writer is Rafii using?', 'Why is a model unavailable?'] },
  ideas: { read: ['How do sources work?', 'Can a cloud model read my sources?'] },
  inbox: { read: ['Which accounts feed this inbox?', 'Can Rafii reply for me?'] },
  analytics: { read: ['Why do some accounts have no numbers?', 'What does Unavailable mean?'] },
  library: { read: ['Which images can I upload?', 'What counts as a used image?'] },
  workspace: { read: ['What can each role do?', 'How do I invite someone?'] },
  account: { read: ['How do I turn on two-step sign-in?', 'How do I export my data?'] },
  help: { read: ['What can Rafii do for me?', 'How do approvals work?'] }
};

/** Up to three questions that fit the page; drafting suggestions only for people who can edit. */
export function suggestionsFor(family: string | null, canEdit: boolean): string[] {
  const entry = SUGGESTIONS[family ?? 'home'] ?? SUGGESTIONS.home;
  return [...(canEdit ? (entry.edit ?? []) : []), ...entry.read].slice(0, 3);
}

/** The steps a turn actually took, in order, from its events: no invented rows. */
export function activityRows(events: ActivityEvent[] | undefined, composing: boolean): ActivityRow[] {
  const rows: ActivityRow[] = [];
  const list = events ?? [];
  for (let index = 0; index < list.length; index++) {
    const event = list[index];
    if (event.type !== 'progress.updated') continue;
    if (event.stage === 'tool' && event.label) {
      const status = event.status === 'verified' || event.status === 'unverified' ? 'done' : event.status === 'blocked' ? 'blocked' : 'failed';
      rows.push({ key: `${index}-${event.tool}`, label: event.label, status });
    }
  }
  if (composing) rows.push({ key: 'composing', label: 'Writing the answer', status: 'running' });
  return rows;
}

/** A message the panel answered (a `siteAgent` body), as opposed to a draft run, an automation reply or a plain note. */
export function isSiteAgentBody(body: unknown): boolean {
  return typeof body === 'object' && body !== null && typeof (body as { siteAgent?: unknown }).siteAgent === 'object' && (body as { siteAgent?: unknown }).siteAgent !== null;
}

/** Shorten a conversation title for the panel header. */
export function shortTitle(title: string | null | undefined, max = 48): string {
  const text = (title ?? '').replace(/\s+/g, ' ').trim();
  return text.length > max ? text.slice(0, max - 1).trimEnd() + '…' : text;
}

/**
 * Pure helpers for relationship follow-ups: copy (English and Traditional Chinese, chosen from the person's language
 * preference like dates and numbers), state and reminder wording, due-time inputs and reply routes. No runtime
 * imports, so `node --test web/tests/relationships.test.mjs` loads it directly.
 */
import type {
  DueInput,
  FollowUpStatus,
  OpenRelationshipState,
  Relationship,
  RelationshipFilters,
  RelationshipState,
  ReplyRoute
} from './relationships-types';

/** List filters → a query string (only known keys, empty values left out). */
export function relationshipQuery(filters: RelationshipFilters = {}): string {
  const params = new URLSearchParams();
  for (const key of ['state', 'due', 'owner', 'thread', 'cursor', 'limit'] as const) {
    const value = filters[key];
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  }
  const text = params.toString();
  return text ? `?${text}` : '';
}

export type FollowUpLocale = 'en' | 'zh-Hant';

/** Traditional Chinese for zh-Hant/HK/TW/MO and Cantonese; everything else (including zh-Hans) reads English. */
export function followUpLocale(locale: string | null | undefined): FollowUpLocale {
  const tag = (locale ?? '').toLowerCase();
  if (tag.startsWith('yue') || tag.startsWith('zh-hant') || ['zh-hk', 'zh-tw', 'zh-mo'].includes(tag)) return 'zh-Hant';
  return 'en';
}

const EN = {
  section: 'Follow up',
  tab: 'Follow-ups',
  pick: 'Pick a follow-up.',
  track: 'Track as a follow-up',
  trackHint: 'Keep a name, what they want, the next step and when to follow up. Reminders never contact anyone.',
  remindersNote: 'Reminders never contact anyone. A reply still needs your exact approval.',
  name: 'Name',
  interest: 'What they want',
  nextAction: 'Next step',
  due: 'Follow up on',
  timeZone: 'Time zone',
  noDue: 'No follow-up time',
  owner: 'Owner',
  unassigned: 'Unassigned',
  formerMember: 'Former member',
  state: 'Stage',
  save: 'Save',
  saving: 'Saving…',
  cancel: 'Cancel',
  edit: 'Edit',
  create: 'Start follow-up',
  newFollowUp: 'New follow-up',
  creating: 'Starting…',
  clearDue: 'Clear time',
  snooze: 'Snooze',
  snoozeHour: '1 hour',
  snoozeTomorrow: 'Tomorrow morning',
  snoozeWeek: 'Next week',
  unsnooze: 'Unsnooze',
  close: 'Close',
  reopen: 'Reopen',
  notRelevant: 'Not relevant',
  undo: 'Undo',
  notes: 'Notes',
  addNote: 'Add note',
  notePlaceholder: 'A short private note',
  removeNote: 'Remove note',
  reply: 'Reply',
  history: 'History',
  loading: 'Loading follow-up…',
  loadMore: 'Load more',
  empty: 'No follow-ups yet.',
  emptyHint: 'Open a comment and choose “Track as a follow-up”, or start one here.',
  nothingDue: 'Nothing is due right now.',
  reload: 'Reload',
  conflict: 'This follow-up changed since you opened it. Reload it and try again.',
  failed: "That didn't save. Nothing changed.",
  repeatedTime: 'That time happens twice on that day because the clocks change. Which one?',
  firstOccurrence: 'First (earlier)',
  secondOccurrence: 'Second (later)',
  wonTitle: 'Mark as won',
  wonHint: 'Won is linked to a result you reported yourself. Rafii never decides that someone bought.',
  wonPick: 'Which result came from this follow-up?',
  wonNone: 'You have not reported a result yet. Record it here; it is also listed in Growth → Results.',
  wonLoading: 'Loading your results…',
  wonMore: 'Show more results',
  wonRecordAndSelect: 'Record and select',
  wonUnavailable: 'Business results are not switched on for this workspace, so a follow-up cannot be marked won yet.',
  confirm: 'Confirm',
  suggested: (state: string) => `Suggested: mark as “${state}”`,
  apply: 'Apply',
  dismiss: 'Dismiss',
  linkedConversations: 'Linked conversations',
  link: 'Link this conversation',
  unlink: 'Unlink',
  assisted: (platform: string) => `Open on ${platform} · assisted`,
  assistedHint: (platform: string) => `Rafii can't reply on ${platform}. Reply there; nothing is sent from Rafii.`,
  directHint: 'Replies use the Inbox composer below and need your exact approval.',
  dueNow: 'Follow-up due',
  dueSince: (when: string) => `Due since ${when}`,
  scheduled: (when: string) => `Follow up ${when}`,
  snoozedUntil: (when: string) => `Snoozed until ${when}`,
  dismissed: 'Reminder dismissed for this time',
  inactive: 'No reminders while closed',
  snoozedToast: 'Follow-up snoozed.',
  closedToast: 'Follow-up closed.',
  dismissedToast: 'Reminder dismissed.',
  provenance: {
    user_declared: 'You reported this result.',
    first_party_reported: 'Reported by your connected source.',
    provider_native: 'Platform-reported result.',
    unknown: 'Result recorded.'
  } as Record<string, string>,
  reasons: {
    reply_sent: 'a reply was sent',
    new_message: 'they wrote again',
    due_passed: 'the follow-up time passed'
  } as Record<string, string>,
  states: {
    new: 'New',
    replied: 'Replied',
    waiting: 'Waiting on them',
    follow_up_due: 'Follow-up due',
    won: 'Won',
    closed: 'Closed'
  } as Record<RelationshipState, string>
};

export type FollowUpCopy = typeof EN;

const ZH: FollowUpCopy = {
  section: '跟進',
  tab: '跟進事項',
  pick: '請選擇一個跟進事項。',
  track: '加入跟進',
  trackHint: '記下名稱、對方的需要、下一步和跟進時間。提醒不會聯絡任何人。',
  remindersNote: '提醒不會聯絡任何人。回覆仍需你確認完全相同的內容。',
  name: '名稱',
  interest: '對方的需要',
  nextAction: '下一步',
  due: '跟進時間',
  timeZone: '時區',
  noDue: '未設定跟進時間',
  owner: '負責人',
  unassigned: '未指派',
  formerMember: '已離開的成員',
  state: '階段',
  save: '儲存',
  saving: '儲存中…',
  cancel: '取消',
  edit: '編輯',
  create: '開始跟進',
  newFollowUp: '新增跟進事項',
  creating: '建立中…',
  clearDue: '清除時間',
  snooze: '暫緩提醒',
  snoozeHour: '1 小時',
  snoozeTomorrow: '明天早上',
  snoozeWeek: '下星期',
  unsnooze: '取消暫緩',
  close: '結束',
  reopen: '重新開啟',
  notRelevant: '不相關',
  undo: '復原',
  notes: '備註',
  addNote: '新增備註',
  notePlaceholder: '簡短的私人備註',
  removeNote: '刪除備註',
  reply: '回覆',
  history: '紀錄',
  loading: '正在載入跟進事項…',
  loadMore: '載入更多',
  empty: '還沒有跟進事項。',
  emptyHint: '打開一則留言並選擇「加入跟進」，或在這裡新增。',
  nothingDue: '目前沒有需要跟進的事項。',
  reload: '重新載入',
  conflict: '這個跟進事項在你打開後已被修改。請重新載入再試。',
  failed: '未能儲存，內容沒有改變。',
  repeatedTime: '因為時鐘調整，這個時間在當天會出現兩次。請選擇：',
  firstOccurrence: '第一次（較早）',
  secondOccurrence: '第二次（較晚）',
  wonTitle: '標記為已成交',
  wonHint: '已成交會連結到你自己記錄的成果；Rafii 不會自行判斷有人購買。',
  wonPick: '這次跟進帶來了哪一項成果？',
  wonNone: '你還沒有記錄任何成果。可以在這裡記錄，也會列在「成長 → 成果」。',
  wonLoading: '正在載入你的成果…',
  wonMore: '顯示更多成果',
  wonRecordAndSelect: '記錄並選取',
  wonUnavailable: '此工作區尚未開啟業務成果，因此暫時無法將跟進標記為已成交。',
  confirm: '確認',
  suggested: (state: string) => `建議：標記為「${state}」`,
  apply: '套用',
  dismiss: '略過',
  linkedConversations: '相關對話',
  link: '連結這則對話',
  unlink: '取消連結',
  assisted: (platform: string) => `在 ${platform} 開啟 · 協助`,
  assistedHint: (platform: string) => `Rafii 無法在 ${platform} 回覆。請在該平台回覆；Rafii 不會發出任何內容。`,
  directHint: '回覆會使用下方的收件匣編輯器，並需要你確認完全相同的內容。',
  dueNow: '需要跟進',
  dueSince: (when: string) => `自 ${when} 起需要跟進`,
  scheduled: (when: string) => `於 ${when} 跟進`,
  snoozedUntil: (when: string) => `暫緩至 ${when}`,
  dismissed: '這次提醒已略過',
  inactive: '已結束，不會再提醒',
  snoozedToast: '已暫緩提醒。',
  closedToast: '跟進事項已結束。',
  dismissedToast: '已略過提醒。',
  provenance: {
    user_declared: '這是你記錄的結果。',
    first_party_reported: '由你已連結的來源回報。',
    provider_native: '平台回報的結果。',
    unknown: '已記錄結果。'
  },
  reasons: {
    reply_sent: '已發出回覆',
    new_message: '對方再次留言',
    due_passed: '已過跟進時間'
  },
  states: {
    new: '新建立',
    replied: '已回覆',
    waiting: '等待對方',
    follow_up_due: '需要跟進',
    won: '已成交',
    closed: '已結束'
  }
};

export function followUpCopy(locale: string | null | undefined): FollowUpCopy {
  return followUpLocale(locale) === 'zh-Hant' ? ZH : EN;
}

export const OPEN_STATES: readonly OpenRelationshipState[] = ['new', 'replied', 'waiting', 'follow_up_due'];

/** States a person can move to from here (never the current one). Leaving won/closed is a reopen. */
export function nextStates(state: RelationshipState): RelationshipState[] {
  if (state === 'won' || state === 'closed') return [];
  return (['new', 'replied', 'waiting', 'follow_up_due', 'won', 'closed'] as RelationshipState[]).filter((target) => target !== state);
}

export type BadgeTone = 'neutral' | 'info' | 'success' | 'warning' | 'danger' | 'loading';

export function stateTone(state: RelationshipState): BadgeTone {
  if (state === 'follow_up_due') return 'warning';
  if (state === 'won') return 'success';
  if (state === 'replied' || state === 'waiting') return 'info';
  return 'neutral';
}

/** One line for the reminder, in words. `when(epoch, zone?)` formats an instant (in `zone` when given). */
export function followUpLine(
  relationship: Pick<Relationship, 'followUp' | 'due' | 'snoozedUntil'>,
  copy: FollowUpCopy,
  when: (epoch: number, zone?: string) => string
): string {
  const status: FollowUpStatus = relationship.followUp.status;
  if (status === 'none') return copy.noDue;
  if (status === 'inactive') return copy.inactive;
  if (status === 'snoozed') return copy.snoozedUntil(when(relationship.followUp.until ?? relationship.snoozedUntil ?? 0));
  if (status === 'dismissed') return copy.dismissed;
  if (status === 'due') return copy.dueSince(when(relationship.followUp.since ?? relationship.due?.at ?? 0));
  return copy.scheduled(relationship.due ? `${when(relationship.due.at, relationship.due.timeZone)} (${relationship.due.timeZone})` : '');
}

/** The browser's own zone, a valid IANA name or UTC. */
export function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/** Zones to offer: the record's, the person's, the browser's, then a short common list; unique, in that order. */
export function zoneChoices(...preferred: (string | null | undefined)[]): string[] {
  const common = ['UTC', 'America/New_York', 'America/Chicago', 'America/Denver', 'America/Los_Angeles', 'Europe/London', 'Europe/Paris', 'Asia/Hong_Kong', 'Asia/Taipei', 'Asia/Tokyo', 'Australia/Sydney'];
  const out: string[] = [];
  for (const zone of [...preferred, ...common]) {
    if (zone && /^[A-Za-z_]+(?:\/[A-Za-z0-9_+-]+){0,2}$/.test(zone) && !out.includes(zone)) out.push(zone);
  }
  return out;
}

const LOCAL = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/;

/** A `<input type="datetime-local">` value → the API's due input; empty clears the due time. */
export function dueInput(local: string, timeZone: string, fold?: 0 | 1): DueInput | null {
  const value = local.trim().slice(0, 16);
  if (!value) return null;
  if (!LOCAL.test(value)) throw new Error('Choose a date and time.');
  return fold === undefined ? { local: value, timeZone } : { local: value, timeZone, fold };
}

/** Snooze choices relative to now, in the given zone: an hour, tomorrow 09:00, and the same time next week. */
export function snoozeChoices(now: number, timeZone: string, copy: FollowUpCopy): { label: string; until: number }[] {
  const tomorrowNine = wallTime(now + 86_400, timeZone, 9, 0);
  return [
    { label: copy.snoozeHour, until: now + 3_600 },
    { label: copy.snoozeTomorrow, until: tomorrowNine > now ? tomorrowNine : now + 86_400 },
    { label: copy.snoozeWeek, until: now + 7 * 86_400 }
  ];
}

/** The instant of hh:mm on the calendar day `epoch` falls on in `timeZone`, honouring that day's UTC offset. */
export function wallTime(epoch: number, timeZone: string, hour: number, minute: number): number {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(epoch * 1000))
    .reduce<Record<string, string>>((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  const guess = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), hour, minute) / 1000;
  // Correct the guess by the zone's offset at that moment (twice, for a nearby offset change).
  let at = guess;
  for (let i = 0; i < 2; i++) at = guess - zoneOffset(at, timeZone);
  return at;
}

function zoneOffset(epoch: number, timeZone: string): number {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })
    .formatToParts(new Date(epoch * 1000))
    .reduce<Record<string, string>>((acc, part) => ({ ...acc, [part.type]: part.value }), {});
  const asUtc = Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day), Number(parts.hour), Number(parts.minute), Number(parts.second)) / 1000;
  return asUtc - Math.floor(epoch);
}

export function platformName(provider: string | null | undefined): string {
  if (!provider) return 'the platform';
  const known: Record<string, string> = { threads: 'Threads', instagram: 'Instagram', facebook: 'Facebook', linkedin: 'LinkedIn', x: 'X', whatsapp: 'WhatsApp', tiktok: 'TikTok', youtube: 'YouTube' };
  return known[provider] ?? provider.charAt(0).toUpperCase() + provider.slice(1);
}

/** How a reply can happen, in words. Assisted routes are never presented as a direct, successful reply. */
export function replyRouteView(route: ReplyRoute | null | undefined, copy: FollowUpCopy) {
  const platform = platformName(route?.provider);
  if (route?.kind === 'direct') return { kind: 'direct' as const, label: copy.reply, hint: copy.directHint, href: null };
  const href = route?.href && /^https:\/\//.test(route.href) ? route.href : null;
  return { kind: 'assisted' as const, label: copy.assisted(platform), hint: copy.assistedHint(platform), href };
}

/**
 * Ids from a link back to their uuid form. Stored notification links carry `u` + 32 hex digits (a form the phone-number
 * redaction can't touch); hyphenated uuids pass through unchanged.
 */
export function canonicalId(value: string | null | undefined): string | null {
  if (!value) return null;
  const compact = /^u?([0-9a-f]{32})$/i.exec(value);
  if (!compact) return value;
  const hex = compact[1].toLowerCase();
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** The Inbox deep link for a follow-up (and its conversation when it has one). */
export function followUpHref(relationshipId: string, threadId?: string | null): string {
  const params = new URLSearchParams({ filter: 'follow_ups', relationship: relationshipId });
  if (threadId) params.set('thread', threadId);
  return `/app/inbox?${params.toString()}`;
}

export function isConflict(code: string | undefined): boolean {
  return code === 'revision_conflict' || code === 'idempotency_conflict' || code === 'suggestion_changed';
}

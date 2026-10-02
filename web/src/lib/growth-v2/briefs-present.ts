/**
 * Plain-language presentation of the opportunity brief, in English and Traditional Chinese. Pure functions (no React,
 * no network), so `node --test web/tests/growth-v2-loop.test.mjs` checks them directly.
 *
 * Honesty rules the wording keeps: stored results are labelled stored (never "today's research"), unknown times say
 * unknown, an empty brief says so without inventing an opportunity, and nothing claims to be published or scheduled.
 */
import type { BriefActionKind, BriefCurrent, BriefEffort, BriefHandledItem, BriefItem, BriefReasonAction, BriefSource, SourceCoverage } from './briefs-types';

export type LoopLocale = 'en' | 'zh-Hant';

/** Traditional Chinese only for zh-Hant, zh-TW, zh-HK, zh-MO and Cantonese (D-022, the same rule as results and
 *  follow-ups); every other tag reads English, plain `zh`, zh-Hans and zh-CN included. */
export function loopLocale(locale: string | null | undefined): LoopLocale {
  const value = String(locale ?? '').toLowerCase().replaceAll('_', '-');
  return /^(zh-hant|zh-tw|zh-hk|zh-mo|yue)(-|$)/.test(value) ? 'zh-Hant' : 'en';
}

const EN = {
  title: 'Opportunity brief',
  description: 'Up to three opportunities from sources Rafii already stored, matched to your goals and your own material. Nothing is drafted, scheduled or published until you choose.',
  loading: 'Loading your brief…',
  error: 'The brief could not be loaded.',
  retry: 'Try again',
  emptyTitle: 'No opportunity this week',
  emptyAvailable: 'Nothing in your stored sources is fresh and relevant enough to suggest. That is a valid result, not an error.',
  emptyUnavailable: 'No source is available for a brief yet. Turn on listening or Radar, or follow a trend, and stored results will appear here.',
  stored: 'Stored result',
  storedNote: 'Stored results only — not today’s research. Absence from a source is not absence everywhere.',
  published: 'Published',
  retrieved: 'Retrieved',
  unknownTime: 'unknown',
  why: 'Why it may matter',
  angle: 'A possible angle',
  coverage: 'Coverage',
  evidence: 'Evidence',
  gapEvidence: 'Observed gap evidence',
  effort: { quick: 'Quick', medium: 'Medium', deep: 'Deep' } as Record<BriefEffort, string>,
  source: { trends: 'Trend intelligence', listening: 'Listening', radar: 'Radar scan' } as Record<BriefSource, string>,
  kind: { question: 'Audience question', signal: 'Signal', whitespace: 'Observed gap' } as Record<BriefItem['kind'], string>,
  availability: { available: 'available', partial: 'partial', unavailable: 'unavailable', unknown: 'unknown' } as Record<string, string>,
  completeness: { complete_within_scope: 'complete within its scope', partial: 'partial', incomplete: 'incomplete', unknown: 'unknown' } as Record<string, string>,
  sourceState: { available: 'stored results', empty: 'nothing stored', unavailable: 'unavailable', stale: 'stored results are stale' } as Record<SourceCoverage['state'], string>,
  saveIdea: 'Save as an idea',
  accept: 'Accept…',
  acceptConfirm: 'Accept with this angle and account',
  chooseAngle: 'Angle',
  chooseAccount: 'Account',
  dismiss: 'Dismiss',
  notRelevant: 'Not relevant',
  restore: 'Restore',
  cancel: 'Cancel',
  confirm: 'Confirm',
  reason: 'Reason',
  saved: 'Saved as an idea',
  accepted: 'Accepted',
  dismissed: 'Dismissed',
  markedNotRelevant: 'Marked not relevant',
  openIdea: 'Open the idea',
  working: 'Saving…',
  savedToast: 'Saved as an idea. Nothing was drafted or published.',
  doneToast: 'Recorded.',
  unverified: 'The change could not be confirmed. Refresh before trying again.',
  changed: 'The brief changed since you opened it. Review the current version.',
  viewOnly: 'You can read this brief; an editor acts on it.',
  handled: 'Already handled',
  handledNote: 'What you decided this week, and anything you marked not relevant recently. Restore brings an item back.',
  reasons: {
    not_now: 'Not now', already_covered: 'Already covered', too_much_effort: 'Too much effort', other: 'Other reason',
    wrong_topic: 'Wrong topic', wrong_audience: 'Wrong audience', wrong_platform: 'Wrong platform', low_quality_source: 'Low-quality source'
  } as Record<string, string>,
  items: (n: number) => (n === 1 ? '1 opportunity' : `${n} opportunities`),
  relevance: {
    material: (label: string) => `Builds on your own material “${label}”.`,
    goal: (label: string) => `Matches your goal “${label}”.`,
    brand: (label: string) => `Matches your brand subject “${label}”.`,
    interest: (label: string) => `Matches what you asked Rafii to watch: “${label}”.`,
    fit: () => 'A stored workspace-fit assessment rates its audience relevance as supported.'
  } as Record<string, (label: string) => string>,
  scopeNote: {
    watchlist: 'Public web results from what you asked Rafii to watch, with your research permission. Social platforms appear only through a connected account.',
    radar_scan: 'From a Radar scan you ran. Source coverage and cause are not established.',
    workspace: 'Stored trend results in your workspace’s authorized scope.'
  } as Record<string, string>,
  angleOption: (n: number) => `Angle ${n}`,
  angleFull: 'Chosen angle',
  accountsLoading: 'Loading your accounts…',
  accountsError: 'Your accounts could not be loaded.',
  noAccounts: 'No connected account can take this opportunity yet.',
  connectAccount: 'Connect an account',
  movedToHandled: 'Moved to “Already handled”.',
  restored: 'Back in this week’s brief.',
  errors: {
    revision_conflict: 'The brief changed since you opened it. Review the current version.',
    already_acted: 'This opportunity was already acted on.',
    restore_first: 'Restore this item before acting on it again.',
    nothing_to_restore: 'Only a dismissed or not-relevant item can be restored.',
    unsupported_action: 'This item supports a different action.',
    reason_required: 'Choose a reason.',
    source_unavailable: 'This opportunity is no longer open.',
    idempotency_conflict: 'That request was already used for a different action. Try again.',
    not_found: 'This item is no longer in your brief. Refresh to see the current one.',
    forbidden: 'You don’t have permission to act on this brief.',
    choose_angle: 'Choose an angle and an account for this opportunity.',
    generic: 'That did not work. Try again.'
  } as Record<string, string>
};

type Copy = typeof EN;

const ZH: Copy = {
  title: '機會簡報',
  description: '從 Rafii 已儲存的資料來源中，按你的目標與素材挑選最多三個機會。在你選擇之前，不會撰寫、排程或發佈任何內容。',
  loading: '正在載入簡報…',
  error: '無法載入簡報。',
  retry: '再試一次',
  emptyTitle: '本週沒有建議的機會',
  emptyAvailable: '已儲存的資料來源中，暫時沒有足夠新近又相關的內容可以建議。這是有效結果，並非錯誤。',
  emptyUnavailable: '目前沒有可用於簡報的資料來源。開啟聆聽或 Radar，或追蹤一個趨勢後，已儲存的結果會顯示在這裡。',
  stored: '已儲存結果',
  storedNote: '只使用已儲存的結果，並非今天的新研究；某來源沒有出現，不代表其他地方也沒有。',
  published: '發佈於',
  retrieved: '取得於',
  unknownTime: '不明',
  why: '為何可能相關',
  angle: '可行角度',
  coverage: '涵蓋範圍',
  evidence: '證據',
  gapEvidence: '觀察到的缺口證據',
  effort: { quick: '快速', medium: '中等', deep: '深入' },
  source: { trends: '趨勢情報', listening: '社群聆聽', radar: 'Radar 掃描' },
  kind: { question: '受眾提問', signal: '訊號', whitespace: '觀察到的缺口' },
  availability: { available: '可用', partial: '部分', unavailable: '不可用', unknown: '不明' },
  completeness: { complete_within_scope: '在範圍內完整', partial: '部分', incomplete: '不完整', unknown: '不明' },
  sourceState: { available: '已儲存結果', empty: '沒有儲存結果', unavailable: '不可用', stale: '已儲存結果已過時' },
  saveIdea: '儲存為點子',
  accept: '採納…',
  acceptConfirm: '以此角度及帳戶採納',
  chooseAngle: '角度',
  chooseAccount: '帳戶',
  dismiss: '略過',
  notRelevant: '不相關',
  restore: '還原',
  cancel: '取消',
  confirm: '確認',
  reason: '原因',
  saved: '已儲存為點子',
  accepted: '已採納',
  dismissed: '已略過',
  markedNotRelevant: '已標示為不相關',
  openIdea: '開啟點子',
  working: '正在儲存…',
  savedToast: '已儲存為點子，沒有撰寫或發佈任何內容。',
  doneToast: '已記錄。',
  unverified: '未能確認這項變更。請重新整理後再試。',
  changed: '簡報在你開啟後已更新，請查看最新版本。',
  viewOnly: '你可以閱讀這份簡報；由編輯者處理。',
  handled: '已處理',
  handledNote: '你本週作出的決定，以及最近標示為不相關的項目。按「還原」可讓項目重新出現。',
  reasons: {
    not_now: '暫時不需要', already_covered: '已經談過', too_much_effort: '太費工夫', other: '其他原因',
    wrong_topic: '主題不對', wrong_audience: '受眾不對', wrong_platform: '平台不對', low_quality_source: '來源質素不佳'
  },
  items: (n: number) => `${n} 個機會`,
  relevance: {
    material: (label: string) => `建基於你自己的素材「${label}」。`,
    goal: (label: string) => `配合你的目標「${label}」。`,
    brand: (label: string) => `配合你的品牌主題「${label}」。`,
    interest: (label: string) => `配合你請 Rafii 留意的主題：「${label}」。`,
    fit: () => '已儲存的工作區配合度評估認為它與你的受眾相關。'
  },
  scopeNote: {
    watchlist: '來自你請 Rafii 留意的公開網絡結果，並已取得你的研究許可；社群平台只會透過已連接的帳戶出現。',
    radar_scan: '來自你執行過的 Radar 掃描；來源涵蓋範圍及因果關係未經確立。',
    workspace: '工作區授權範圍內已儲存的趨勢結果。'
  },
  angleOption: (n: number) => `角度 ${n}`,
  angleFull: '已選角度',
  accountsLoading: '正在載入你的帳戶…',
  accountsError: '無法載入你的帳戶。',
  noAccounts: '暫時沒有已連接的帳戶可以處理這個機會。',
  connectAccount: '連接帳戶',
  movedToHandled: '已移到「已處理」。',
  restored: '已放回本週簡報。',
  errors: {
    revision_conflict: '簡報在你開啟後已更新，請查看最新版本。',
    already_acted: '這個機會已經處理過。',
    restore_first: '請先還原這個項目，再處理它。',
    nothing_to_restore: '只有已略過或標示為不相關的項目可以還原。',
    unsupported_action: '這個項目支援另一種處理方式。',
    reason_required: '請選擇原因。',
    source_unavailable: '這個機會已不再開放。',
    idempotency_conflict: '這個請求已用於另一項操作，請再試一次。',
    not_found: '這個項目已不在你的簡報中。請重新整理查看最新版本。',
    forbidden: '你沒有權限處理這份簡報。',
    choose_angle: '請為這個機會選擇角度及帳戶。',
    generic: '操作未能完成，請再試一次。'
  }
};

export function briefCopy(locale: string | null | undefined): Copy {
  return loopLocale(locale) === 'zh-Hant' ? ZH : EN;
}

/** At most three items, in server order: the cap holds even if a response were malformed. */
export function visibleItems(brief: Pick<BriefCurrent, 'edition'>): BriefItem[] {
  return (brief.edition?.items ?? []).slice(0, 3);
}

/** "Published 6 Oct · Retrieved 7 Oct"; an unknown time says unknown instead of being left out. */
export function timeLine(item: Pick<BriefItem, 'publishedAt' | 'retrievedAt'>, copy: Copy, format: (epoch: number) => string): string {
  const part = (label: string, value: number | null) => `${label} ${value == null ? copy.unknownTime : format(value)}`;
  return `${part(copy.published, item.publishedAt)} · ${part(copy.retrieved, item.retrievedAt)}`;
}

export function coverageLine(item: Pick<BriefItem, 'coverage'>, copy: Copy): string {
  const availability = copy.availability[item.coverage?.availability ?? 'unknown'] ?? item.coverage?.availability ?? copy.availability.unknown;
  const completeness = item.coverage?.completeness ? copy.completeness[item.coverage.completeness] ?? item.coverage.completeness : null;
  return completeness ? `${availability} · ${completeness}` : availability;
}

/** Why the item is relevant, in the person's language, from the first match the server found (its text as a fallback). */
export function relevanceText(item: Pick<BriefItem, 'relevance'>, copy: Copy): string {
  const first = item.relevance?.matches?.[0];
  const template = first ? copy.relevance[first.kind] : undefined;
  return template ? template(first?.label ?? '') : item.relevance?.reason ?? '';
}

/** What the coverage covers, in the person's language (the source's own note as a fallback). */
export function coverageNote(item: Pick<BriefItem, 'coverage'>, copy: Copy): string | null {
  return copy.scopeNote[item.coverage?.scope ?? ''] ?? item.coverage?.note ?? null;
}

/** Only https links are shown as links; anything else stays a label. */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const parsed = new URL(url);
    return parsed.protocol === 'https:' && !parsed.username && !parsed.password ? parsed.toString() : null;
  } catch {
    return null;
  }
}

export function reasonCodes(brief: Pick<BriefCurrent, 'reasons'>, action: BriefReasonAction): string[] {
  return brief.reasons?.[action] ?? [];
}

/** What the item's state is, from its latest decision: open (actions available), done (accepted / saved), or set aside (restorable). */
export function itemStatus(item: Pick<BriefItem, 'decision'>): 'open' | 'done' | 'set_aside' {
  const action = item.decision?.action as BriefActionKind | undefined;
  if (action === 'accept' || action === 'save_idea') return 'done';
  if (action === 'dismiss' || action === 'not_relevant') return 'set_aside';
  return 'open';
}

export function decisionLabel(item: Pick<BriefItem, 'decision'>, copy: Copy): string | null {
  const decision = item.decision;
  if (!decision || decision.action === 'restore') return null;
  const base = { accept: copy.accepted, save_idea: copy.saved, dismiss: copy.dismissed, not_relevant: copy.markedNotRelevant }[decision.action];
  return decision.reasonCode ? `${base} · ${copy.reasons[decision.reasonCode] ?? decision.reasonCode}` : base;
}

export function outcomeSourceId(item: Pick<BriefItem, 'decision'>): string | null {
  return item.decision?.outcomeRefs?.find((ref) => ref.type === 'source')?.id ?? null;
}

/** The action body the server expects for the version the person saw: a stored edition by id, else its material digest.
 *  `stored` maps a material digest to the edition an earlier action stored for it, so a second card acting on the same
 *  (now stored) version names that edition instead of a digest the server would otherwise have to recompose. */
export function actionTarget(edition: Pick<BriefCurrent['edition'], 'id' | 'materialDigest'>, stored?: ReadonlyMap<string, string>): { editionId?: string; materialDigest?: string } {
  const id = edition.id ?? stored?.get(edition.materialDigest) ?? null;
  return id ? { editionId: id } : { materialDigest: edition.materialDigest };
}

/** Already-handled items, bounded, newest decision first (the server orders them; the cap holds even if it did not). */
export function handledItems(brief: Pick<BriefCurrent, 'edition'>): BriefHandledItem[] {
  return (brief.edition?.handled ?? []).slice(0, 10);
}

/** The accept form's angle choices, each with words: the server's text for every angle when it sends it, the item's
 *  own angle for the first, and "Angle n" otherwise (never a raw id). At most three, in the server's order. */
export function angleOptions(item: Pick<BriefItem, 'action' | 'angle'>, copy: Copy): { id: string; text: string }[] {
  const ids = (item.action?.angleIds ?? []).filter((id): id is string => typeof id === 'string' && id.length > 0).slice(0, 3);
  const texts = new Map<string, string>();
  for (const angle of item.action?.angles ?? []) {
    if (angle && typeof angle.id === 'string' && typeof angle.text === 'string') texts.set(angle.id, angle.text.replace(/\s+/g, ' ').trim());
  }
  return ids.map((id, index) => {
    const own = index === 0 || item.angle?.id === id ? (item.angle?.text ?? '').replace(/\s+/g, ' ').trim() : '';
    return { id, text: texts.get(id) || own || copy.angleOption(index + 1) };
  });
}

/** A native option can't wrap: long angle text is shortened in the list and shown in full under it. */
export function optionLabel(text: string, max = 90): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > max ? `${clean.slice(0, max - 1).trimEnd()}…` : clean;
}

/** A failed brief action in the person's language: known codes and statuses have their own words; anything else is
 *  the generic line in Traditional Chinese (never the server's English) or the server's own sentence in English. */
export function briefFailure(error: { code?: string; status?: number; message?: string } | null | undefined, copy: Copy, locale: LoopLocale): string {
  const code = error?.code;
  if (code && copy.errors[code]) return copy.errors[code];
  if (error?.status === 404) return copy.errors.not_found;
  if (error?.status === 403) return copy.errors.forbidden;
  if (error?.status === 409) return copy.errors.revision_conflict;
  if (error?.status === 400 && /angle|account/i.test(error?.message ?? '')) return copy.errors.choose_angle;
  return locale === 'en' && error?.message ? error.message : copy.errors.generic;
}

/** Stable element ids for focus targets: the brief panel itself (focusable, tabIndex -1), each item's heading in the
 *  open or handled list, and the "Already handled" summary. */
export function briefElementId(part: 'open' | 'handled' | 'handled-summary' | 'panel', itemId = ''): string {
  if (part === 'panel') return 'opportunity-brief';
  if (part === 'handled-summary') return 'opportunity-brief-handled';
  return `brief-${part}-${itemId.replace(/[^A-Za-z0-9_-]/g, '')}`;
}

/** Where keyboard focus goes after an action, once the brief shows the new state. A restored item is focused where it
 *  now is. An item that left the open list (accepted, saved, dismissed, not relevant) hands focus to the item now at
 *  its position, else the one before it, else the "Already handled" summary that now holds it, else the brief panel. */
export function focusAfterAction(done: { itemId: string; index: number; action: BriefActionKind }, open: Pick<BriefItem, 'id'>[], handled: Pick<BriefItem, 'id'>[]): string {
  if (open.some((item) => item.id === done.itemId)) return briefElementId('open', done.itemId);
  const next = open[Math.min(Math.max(done.index, 0), open.length - 1)];
  if (done.action !== 'restore' && next) return briefElementId('open', next.id);
  if (handled.length) return briefElementId('handled-summary');
  return next ? briefElementId('open', next.id) : briefElementId('panel');
}

export type BriefRefreshScope = 'snapshot' | 'trendPool' | 'listening' | 'radar';

/** What else a brief action changes beyond the brief itself: saving or accepting makes an idea source (the workspace
 *  snapshot) and settles the item where it came from (the trend pools, listening, Radar). Dismiss, not relevant and
 *  restore only touch the brief. */
export function briefRefreshScopes(action: BriefActionKind, hasOutcome: boolean): BriefRefreshScope[] {
  return action === 'accept' || action === 'save_idea' || hasOutcome ? ['snapshot', 'trendPool', 'listening', 'radar'] : [];
}

/** True when the page was opened from a brief link (`/app/weekly?brief=1#opportunity-brief`): the brief scrolls into
 *  view once it has loaded (the browser's own jump happens before the brief exists). */
export function wantsBrief(search: string, hash: string): boolean {
  return hash === '#opportunity-brief' || new URLSearchParams(search).get('brief') === '1';
}

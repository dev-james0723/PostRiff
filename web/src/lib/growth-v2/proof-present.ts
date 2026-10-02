/**
 * Plain-language presentation of Growth Loop proof revisions and next-week decisions (EN + zh-Hant). Pure functions,
 * checked by `node --test web/tests/growth-v2-loop.test.mjs`.
 *
 * Rules the wording keeps: unavailable is never shown as zero; assisted exports are never added to verified
 * publications; Time Back classes are listed separately (never one "measured" total); unknown provider cost is kept
 * apart from actual cost and never priced as zero; a decision is a planning input, not an approval.
 */
import type {
  AppliedDecision, CorrectionEntry, DecideResult, DecisionAction, DecisionScope, FigureName, NotAppliedDecision, ProofCounts, ProofDataState, ProofFigure, ProofList,
  ProofView, ProviderCost, StrategyDecision, StrategyList, TimeBackClass
} from './proof-types';

/** Same rule as the brief (D-022: Traditional Chinese only for zh-Hant, zh-TW, zh-HK, zh-MO and Cantonese; plain zh,
 *  zh-Hans and zh-CN read English). Kept import-free so node's test runner loads this file directly. */
export function proofLocale(locale: string | null | undefined): 'en' | 'zh-Hant' {
  const value = String(locale ?? '').toLowerCase().replaceAll('_', '-');
  return /^(zh-hant|zh-tw|zh-hk|zh-mo|yue)(-|$)/.test(value) ? 'zh-Hant' : 'en';
}

const EN = {
  title: 'Evidence by revision',
  intro: 'Each figure links to the records it counts. Late data creates a new revision; earlier revisions stay readable.',
  refresh: 'Recompute last week from stored records',
  refreshMonthly: 'Recompute last month',
  refreshing: 'Recomputing…',
  noChange: 'Nothing changed: the figures match the latest revision.',
  appended: (n: number) => `Revision ${n} recorded.`,
  inProgress: 'That period is still in progress, so no proof is shown for it yet.',
  empty: 'No proof revision yet. An owner can recompute last week from stored records.',
  revision: (n: number) => `Revision ${n}`,
  period: 'Period',
  timeZone: 'Time zone',
  asOf: 'As of',
  maturing: 'Late data can still arrive for this period.',
  mature: 'This period has matured.',
  unavailable: 'Unavailable',
  ownerOnly: 'Owners only',
  evidence: 'Evidence',
  truncated: 'more ids not shown',
  history: 'Revision history',
  correction: 'What changed',
  nextStep: 'Next week',
  noProposal: 'No proposal: there is no measured result or saved brief idea to build on yet.',
  proposalRule: 'Proposals come from measured experiments and ideas saved from your brief. Accepting one adds context to next week’s plan; it never changes your voice or approves anything.',
  status: { proposed: 'Proposed', accepted: 'Accepted', edited: 'Accepted with edits', rejected: 'Rejected', revoked: 'Revoked' } as Record<string, string>,
  action: { accept: 'Accept', edit: 'Edit', reject: 'Reject', revoke: 'Revoke' } as Record<DecisionAction, string>,
  editLabel: 'Next-week action',
  narrowAccount: 'Only for this account',
  anyAccount: 'Any account',
  save: 'Save',
  cancel: 'Cancel',
  appliesFrom: 'Applies from',
  scope: { goalId: 'Goal', channelId: 'Account', language: 'Language', contentType: 'Format' } as Record<keyof DecisionScope, string>,
  figure: {
    acceptedWork: 'Accepted or approved work', verifiedPublications: 'Verified publications', assistedExports: 'Assisted exports (separate)',
    unresolvedSlots: 'Unresolved planned posts', outcomes: 'Outcomes by source', timeBack: 'Time Back', providerCost: 'AI and data service cost'
  } as Record<FigureName, string>,
  reason: {
    initial: 'First revision', late_data: 'Late data changed the figures', definition_change: 'The definition changed',
    visual_pack_unavailable: 'Assisted exports are not available in this workspace yet', visual_pack_unreadable: 'Assisted exports could not be read',
    visual_pack_no_counts: 'No assisted-export counts were reported', results_unavailable: 'Result tracking is not available yet',
    results_unreadable: 'Results could not be read', weekly_not_set_up: 'No weekly plan is set up', time_back_unreadable: 'Time Back could not be read',
    usage_ledger_unreadable: 'Cost records could not be read', owner_only: 'Visible to owners',
    partial: 'Some records for this period are still incomplete', cost_unsettled: 'Some charges are not settled yet; their reserved estimate is listed apart',
    period_maturing: 'Late data can still arrive for this period',
    applies_from_later: 'applies from a later week', already_applied: 'already planned in an earlier week', source_unavailable: 'its saved idea was removed',
    account_unavailable: 'its account is disconnected', goal_not_active: 'its goal is not active', no_matching_slot: 'no planned post matches its scope',
    week_already_planned: 'this week was already planned when it was accepted', not_applied: 'it could not be applied'
  } as Record<string, string>,
  provenance: { provider_native: 'Platform-reported', first_party_reported: 'Your site or form', user_declared: 'You declared' } as Record<string, string>,
  confidence: { estimated: 'estimated', personalized: 'personalized', measured: 'measured' } as Record<string, string>,
  exports: (v: Record<string, number>) => `${v.exportReady ?? 0} ready · ${v.downloaded ?? 0} downloaded · ${v.userConfirmedUsed ?? 0} confirmed used`,
  minutes: (n: number) => `${n} min`,
  actualCost: (usd: string, n: number) => `${usd} actual (${n} ${n === 1 ? 'entry' : 'entries'})`,
  unknownCost: (n: number, usd: string) => `${n} unknown (${usd} reserved estimate, not actual)`,
  none: 'none',
  applied: 'Decisions applied to this week',
  appliedSlots: (n: number) => (n === 1 ? 'on 1 post' : `on ${n} posts`),
  notApplied: 'Not applied',
  revokedSince: 'Revoked after this week was planned; drafts written now no longer use it.',
  unverified: 'The decision could not be confirmed. Refresh before trying again.',
  conflict: 'This decision changed since you opened it. Review the current version.',
  frequencyLabel: 'Proof period',
  frequency: { weekly: 'Weekly', monthly: 'Monthly' } as Record<'weekly' | 'monthly', string>,
  loadMore: 'Show earlier proofs',
  loadingMore: 'Loading…',
  loadError: 'The proofs could not be loaded.',
  retry: 'Try again',
  recomputed: 'Recomputed just now',
  linked: 'The proof you opened',
  overall: { available: 'Every figure available', partial: 'Partial', unavailable: 'Unavailable', restricted: 'Owners only' } as Record<ProofDataState, string>,
  state: { available: '', partial: 'Partial', unavailable: 'Unavailable', restricted: 'Owners only' } as Record<ProofDataState, string>,
  stateWord: { available: 'available', partial: 'partial', unavailable: 'unavailable', restricted: 'owners only' } as Record<ProofDataState, string>,
  whyPartial: 'Why this proof is partial',
  evidenceLabel: {
    variantIds: 'Accepted drafts', jobIds: 'Verified Queue jobs', packIds: 'Carousels', resultIds: 'Results', slotIds: 'Planned posts', weekIds: 'Weekly plans',
    estimatedLedgerIds: 'Estimated Time Back entries', personalizedLedgerIds: 'Personalized Time Back entries', measuredLedgerIds: 'Measured Time Back entries',
    actualLedgerIds: 'Settled charges', unknownLedgerIds: 'Unsettled charges'
  } as Record<string, string>,
  openEvidence: { results: 'Open business results', 'visual-packs': 'Open carousels in Library' } as Record<string, string>,
  evidenceRecords: 'Records for this period',
  changed: 'changed',
  stateChange: (before: string, after: string) => `(${before} → ${after})`,
  definitionVersion: 'Definition',
  appliesFromWeek: (date: string) => `Applies to weekly plans from the week of ${date}.`,
  alreadyPlanned: (dates: string[]) => (dates.length === 1 ? `The week of ${dates[0]} was already planned, so it does not use this decision.`
                                                         : `The weeks of ${dates.join(', ')} were already planned, so they do not use this decision.`),
  notInEffect: 'Weekly plans from now on do not use it.',
  unknownDecision: 'A next-week decision',
  loadingDecisions: 'Loading the decisions…',
  decisionsError: 'The decisions’ wording could not be loaded.',
  channelsError: 'Your accounts could not be loaded.',
  errors: {
    revision_conflict: 'This decision changed since you opened it. Review the current version.',
    invalid_transition: 'This decision can no longer change that way. Refresh to see its current state.',
    scope_widened: 'An edit can narrow where a decision applies, not widen or change it.',
    too_many_active_decisions: 'At most 12 next-week decisions can be in effect. Revoke one first.',
    idempotency_conflict: 'That request was already used for a different decision. Try again.',
    source_unavailable: 'That period is older than the records a proof can use.',
    not_found: 'This item is no longer available. Refresh to see the current proofs.',
    forbidden: 'Only a workspace owner can do this.',
    generic: 'That did not work. Try again.'
  } as Record<string, string>
};

type Copy = typeof EN;

const ZH: Copy = {
  title: '各修訂版本的證據',
  intro: '每個數字都連結到它所計算的紀錄。遲來的資料會產生新的修訂版本；較早的版本仍可查看。',
  refresh: '根據已儲存紀錄重新計算上週',
  refreshMonthly: '重新計算上個月',
  refreshing: '正在重新計算…',
  noChange: '沒有變化：數字與最新修訂版本相同。',
  appended: (n: number) => `已記錄第 ${n} 版。`,
  inProgress: '該期間仍在進行中，暫時不顯示證明。',
  empty: '尚未有證明修訂版本。擁有者可以根據已儲存紀錄重新計算上週。',
  revision: (n: number) => `第 ${n} 版`,
  period: '期間',
  timeZone: '時區',
  asOf: '截至',
  maturing: '此期間仍可能有遲來的資料。',
  mature: '此期間的資料已穩定。',
  unavailable: '不可用',
  ownerOnly: '只限擁有者',
  evidence: '證據',
  truncated: '其餘 ID 未顯示',
  history: '修訂紀錄',
  correction: '變更內容',
  nextStep: '下週',
  noProposal: '暫無建議：目前沒有已量度的結果或從簡報儲存的點子可作依據。',
  proposalRule: '建議來自已量度的實驗及你從簡報儲存的點子。採納後只會為下週計劃加入背景資料，不會改變你的語氣，也不會批准任何內容。',
  status: { proposed: '已建議', accepted: '已採納', edited: '已修改後採納', rejected: '已拒絕', revoked: '已撤回' },
  action: { accept: '採納', edit: '修改', reject: '拒絕', revoke: '撤回' },
  editLabel: '下週行動',
  narrowAccount: '只用於此帳戶',
  anyAccount: '任何帳戶',
  save: '儲存',
  cancel: '取消',
  appliesFrom: '生效日期',
  scope: { goalId: '目標', channelId: '帳戶', language: '語言', contentType: '格式' },
  figure: {
    acceptedWork: '已採納或批准的內容', verifiedPublications: '已驗證的發佈', assistedExports: '輔助匯出（另計）',
    unresolvedSlots: '未處理的計劃貼文', outcomes: '按來源劃分的成果', timeBack: '節省的時間', providerCost: 'AI 及資料服務費用'
  },
  reason: {
    initial: '第一版', late_data: '遲來的資料改變了數字', definition_change: '定義已更新',
    visual_pack_unavailable: '此工作區暫未提供輔助匯出', visual_pack_unreadable: '無法讀取輔助匯出', visual_pack_no_counts: '沒有輔助匯出的數字',
    results_unavailable: '暫未提供成果追蹤', results_unreadable: '無法讀取成果', weekly_not_set_up: '尚未設定每週計劃',
    time_back_unreadable: '無法讀取節省的時間', usage_ledger_unreadable: '無法讀取費用紀錄', owner_only: '只限擁有者查看',
    partial: '此期間部分紀錄仍未齊全', cost_unsettled: '部分費用尚未結算；其預留估算另行列出',
    period_maturing: '此期間仍可能有遲來的資料',
    applies_from_later: '從較後的一週開始生效', already_applied: '已在較早的一週計劃中使用', source_unavailable: '其儲存的點子已被移除',
    account_unavailable: '其帳戶已中斷連接', goal_not_active: '其目標並未啟用', no_matching_slot: '沒有計劃貼文符合其範圍',
    week_already_planned: '採納時本週計劃已經完成', not_applied: '未能套用'
  },
  provenance: { provider_native: '平台回報', first_party_reported: '你的網站或表格', user_declared: '你自行申報' },
  confidence: { estimated: '估計', personalized: '個人化', measured: '實測' },
  exports: (v: Record<string, number>) => `${v.exportReady ?? 0} 個可匯出 · ${v.downloaded ?? 0} 個已下載 · ${v.userConfirmedUsed ?? 0} 個確認已使用`,
  minutes: (n: number) => `${n} 分鐘`,
  actualCost: (usd: string, n: number) => `實際 ${usd}（${n} 筆）`,
  unknownCost: (n: number, usd: string) => `${n} 筆不明（預留估算 ${usd}，並非實際）`,
  none: '無',
  applied: '本週套用的決定',
  appliedSlots: (n: number) => `用於 ${n} 篇貼文`,
  notApplied: '未套用',
  revokedSince: '本週計劃後已撤回；之後撰寫的草稿不會再使用。',
  unverified: '未能確認這個決定。請重新整理後再試。',
  conflict: '這個決定在你開啟後已更改，請查看最新版本。',
  frequencyLabel: '證明期間',
  frequency: { weekly: '每週', monthly: '每月' },
  loadMore: '顯示較早的證明',
  loadingMore: '正在載入…',
  loadError: '無法載入證明。',
  retry: '再試一次',
  recomputed: '剛剛重新計算',
  linked: '你開啟的證明',
  overall: { available: '所有數字均可用', partial: '部分', unavailable: '不可用', restricted: '只限擁有者' },
  state: { available: '', partial: '部分', unavailable: '不可用', restricted: '只限擁有者' },
  stateWord: { available: '可用', partial: '部分', unavailable: '不可用', restricted: '只限擁有者' },
  whyPartial: '為何此證明只有部分數據',
  evidenceLabel: {
    variantIds: '已採納的草稿', jobIds: '已驗證的發佈工作', packIds: '輪播圖組', resultIds: '成果', slotIds: '計劃貼文', weekIds: '每週計劃',
    estimatedLedgerIds: '估計的節省時間紀錄', personalizedLedgerIds: '個人化的節省時間紀錄', measuredLedgerIds: '實測的節省時間紀錄',
    actualLedgerIds: '已結算的費用', unknownLedgerIds: '未結算的費用'
  },
  openEvidence: { results: '開啟業務成果', 'visual-packs': '在素材庫開啟輪播圖組' },
  evidenceRecords: '此期間的紀錄',
  changed: '已變更',
  stateChange: (before: string, after: string) => `（${before} → ${after}）`,
  definitionVersion: '定義',
  appliesFromWeek: (date: string) => `由 ${date} 那一週起套用於每週計劃。`,
  alreadyPlanned: (dates: string[]) => `${dates.join('、')} ${dates.length === 1 ? '那一週' : '那幾週'}的計劃已經完成，所以不會使用這個決定。`,
  notInEffect: '之後的每週計劃不會使用它。',
  unknownDecision: '一個下週決定',
  loadingDecisions: '正在載入決定…',
  decisionsError: '無法載入決定的內容。',
  channelsError: '無法載入你的帳戶。',
  errors: {
    revision_conflict: '這個決定在你開啟後已更改，請查看最新版本。',
    invalid_transition: '這個決定已不能這樣更改。請重新整理查看目前狀態。',
    scope_widened: '修改只能收窄決定的適用範圍，不能擴大或更換。',
    too_many_active_decisions: '最多只可同時生效 12 個下週決定。請先撤回其中一個。',
    idempotency_conflict: '這個請求已用於另一個決定，請再試一次。',
    source_unavailable: '該期間早於證明可使用的紀錄。',
    not_found: '這個項目已不可用。請重新整理查看最新的證明。',
    forbidden: '只有工作區擁有者可以這樣做。',
    generic: '操作未能完成，請再試一次。'
  }
};

export function proofCopy(locale: string | null | undefined): Copy {
  return proofLocale(locale) === 'zh-Hant' ? ZH : EN;
}

/** The fixed sentences the server writes into a proof (figure definitions, limitations), in Traditional Chinese. Keyed
 *  by the exact English, so a sentence the server changes falls back to its own words instead of a stale translation. */
const ZH_SERVER_TEXT: Record<string, string> = {
  'Drafts accepted into a weekly plan or approved for Queue in this period; unused drafts and failed publishes are excluded.':
    '此期間採納到每週計劃或在佇列中批准的草稿；未使用的草稿及發佈失敗的貼文不計算在內。',
  'Posts the platform confirmed as published (read back through Queue) in this period. An export, a download or an accepted request is not a verified publication.':
    '此期間平台確認已發佈（經佇列讀回）的貼文。匯出、下載或已接受的請求都不算已驗證的發佈。',
  'Assisted exports (export ready, downloaded, confirmed used), counted apart from verified publications and never added to them.':
    '輔助匯出（可匯出、已下載、確認已使用），與已驗證的發佈分開計算，從不相加。',
  'Weekly-plan slots scheduled in this period that were neither accepted, handed to Queue nor skipped.':
    '此期間排定、但既未採納、未交到佇列、亦未略過的每週計劃貼文。',
  'Qualified results by provenance (provider-native, first-party reported, user declared); never one blended number, unavailable is not zero.':
    '按來源劃分的合資格成果（平台回報、第一方回報、你自行申報）；從不合併成單一數字，不可用不等於零。',
  'Time Back by its existing confidence classes; estimated, personalized and measured are never added into one measured figure.':
    '按現有可信度類別劃分的節省時間；估計、個人化及實測從不相加成一個實測數字。',
  'What AI and data services cost for this period: the actual amount where the charge is settled; charges whose amount is unknown are listed separately at their reserved estimate and never counted as zero. Owners only.':
    '此期間 AI 及資料服務的費用：已結算的按實際金額計算；金額不明的費用按預留估算另行列出，從不當作零。只限擁有者。',
  'AI and data service cost is visible to workspace owners.': 'AI 及資料服務費用只限工作區擁有者查看。',
  'Delivery is not growth: verified publications and accepted work say what was done, not what it caused.': '交付不等於增長：已驗證的發佈及已採納的內容說明做了甚麼，而非帶來了甚麼。',
  'Missing analytics never erase a verified delivery; unavailable figures stay unavailable, never zero.': '缺少分析數據不會抹去已驗證的交付；不可用的數字仍是不可用，從不當作零。',
  'Assisted exports are counted apart from verified publications and are never added to them.': '輔助匯出與已驗證的發佈分開計算，從不相加。',
  'Time Back classes (estimated, personalized, measured) are shown separately; they are not one measured figure.': '節省時間的類別（估計、個人化、實測）分開顯示，並非一個實測數字。'
};

/** A server-written definition or limitation in the reader's language: Traditional Chinese for the known fixed
 *  sentences (an outcomes definition keeps its association version), the server's own words otherwise. */
export function serverText(text: string, copy: Copy): string {
  if (copy !== ZH || !text) return text;
  const association = /^(.*) Association: (.+)\.$/.exec(text);
  if (association && ZH_SERVER_TEXT[association[1]]) return `${ZH_SERVER_TEXT[association[1]]}關聯定義：${association[2]}。`;
  return ZH_SERVER_TEXT[text] ?? text;
}

const RESULT_TYPES: Record<'en' | 'zh-Hant', Record<string, [string, string]>> = {
  en: { lead: ['lead', 'leads'], booking: ['booking', 'bookings'], newsletter_signup: ['newsletter sign-up', 'newsletter sign-ups'], sale: ['sale', 'sales'], click: ['click', 'clicks'] },
  'zh-Hant': { lead: ['潛在客戶', '潛在客戶'], booking: ['預約', '預約'], newsletter_signup: ['電子報訂閱', '電子報訂閱'], sale: ['銷售', '銷售'], click: ['點擊', '點擊'] }
};

function resultCount(type: string, n: number, copy: Copy): string {
  const zh = copy === ZH;
  const words = RESULT_TYPES[zh ? 'zh-Hant' : 'en'][type];
  const word = words ? words[n === 1 ? 0 : 1] : type.replaceAll('_', ' ');
  return zh ? `${word} ${n}` : `${n} ${word}`;
}

export const FIGURE_ORDER: FigureName[] = ['acceptedWork', 'verifiedPublications', 'assistedExports', 'unresolvedSlots', 'outcomes', 'timeBack', 'providerCost'];

export function usd(micro: number): string {
  const dollars = micro / 1_000_000;
  return `US$${dollars < 0.01 && dollars > 0 ? dollars.toFixed(4) : dollars.toFixed(2)}`;
}

function outcomeText(value: Record<string, unknown>, copy: Copy): string {
  return Object.entries(copy.provenance).map(([key, label]) => {
    const bucket = value?.[key] as { counts?: Record<string, number> } | null | undefined;
    if (!bucket) return `${label}: ${copy.unavailable}`;
    const counts = Object.entries(bucket.counts ?? {}).map(([type, n]) => resultCount(type, n, copy));
    return `${label}: ${counts.length ? counts.join(', ') : '0'}`;
  }).join(' · ');
}

/** One figure in words. Unavailable and owner-only figures say so; no figure is ever shown as a fabricated zero. */
export function figureText(name: FigureName, figure: ProofFigure | undefined, copy: Copy): string {
  if (!figure) return copy.unavailable;
  if (figure.dataState === 'restricted') return copy.ownerOnly;
  if (figure.value === null || figure.value === undefined || figure.dataState === 'unavailable') {
    const reason = figure.reason ? copy.reason[figure.reason] ?? figure.reason : null;
    return reason ? `${copy.unavailable} — ${reason}` : copy.unavailable;
  }
  if (name === 'assistedExports') return copy.exports(figure.value as Record<string, number>);
  if (name === 'outcomes') return outcomeText(figure.value as Record<string, unknown>, copy);
  if (name === 'timeBack') {
    const classes = figure.value as TimeBackClass[];
    return classes.length ? classes.map((c) => `${copy.minutes(Math.round(c.savedSeconds / 60))} ${copy.confidence[c.confidence] ?? c.confidence}`).join(' · ') : copy.none;
  }
  if (name === 'providerCost') {
    const cost = figure.value as ProviderCost;
    const parts = [copy.actualCost(usd(cost.actualUsdMicro), cost.actualEntries)];
    if (cost.unknownEntries) parts.push(copy.unknownCost(cost.unknownEntries, usd(cost.unknownReservedEstimateUsdMicro)));
    return parts.join(' · ');
  }
  return String(figure.value);
}

/** The ids each figure counts, grouped and labelled (in the person's language when `copy` is given), for the evidence
 *  disclosure. */
export function evidenceGroups(figure: ProofFigure | undefined, copy?: Copy): { label: string; ids: string[] }[] {
  return Object.entries(figure?.evidence ?? {}).filter(([, ids]) => ids.length)
    .map(([key, ids]) => ({ label: copy?.evidenceLabel[key] ?? key.replace(/([A-Z])/g, ' $1').toLowerCase().replace(/ ids$/, ' ids'), ids }));
}

const EVIDENCE_HREF: Record<string, string> = { results: '/app/analytics#business-results', 'visual-packs': '/app/library#visual-packs' };

/** Where a figure's scoped records live in the app (business results on Analytics, carousels in Library), for figures
 *  whose sibling feature names its records by a scoped query; null for anything unknown. */
export function evidenceLink(figure: Pick<ProofFigure, 'evidenceQuery'> | undefined, copy: Copy): { href: string; label: string } | null {
  const resource = figure?.evidenceQuery?.resource;
  const href = resource ? EVIDENCE_HREF[resource] : undefined;
  return resource && href ? { href, label: copy.openEvidence[resource] ?? copy.evidenceRecords } : null;
}

/** One figure's data state in words for its label ("Partial", "Unavailable", "Owners only"; nothing when complete) and
 *  why, from the figure's own reason, else the coverage entry's, else what partial means for that figure. */
export function figureState(name: FigureName, figure: ProofFigure | undefined, copy: Copy, coverageReason?: string | null): { state: ProofDataState; label: string; reason: string | null } {
  const state: ProofDataState = figure?.dataState ?? 'unavailable';
  const code = figure?.reason ?? coverageReason ?? (state === 'partial' ? (name === 'providerCost' ? 'cost_unsettled' : 'partial') : null);
  const reason = state === 'available' || !code ? null : copy.reason[code] ?? (state === 'partial' ? copy.reason.partial : null);
  return { state, label: copy.state[state] ?? state, reason };
}

/** Why a proof is partial, figure by figure, plus the maturity window: the reasons a reader needs before trusting a
 *  total. Empty when every figure is available and the period has matured. */
export function coverageReasons(counts: Pick<ProofCounts, 'figures' | 'coverage'>, mature: boolean, copy: Copy): string[] {
  const out: string[] = [];
  for (const name of FIGURE_ORDER) {
    const figure = counts.figures?.[name];
    const coverage = counts.coverage?.find((entry) => entry.figure === name);
    const state = figureState(name, figure, copy, coverage?.reason);
    if (state.state === 'partial' || state.state === 'unavailable') out.push(`${copy.figure[name]}: ${state.label}${state.reason ? ` — ${state.reason}` : ''}`);
  }
  if (!mature) out.push(copy.reason.period_maturing);
  return out;
}

/** A correction value in words, using the figure's own wording (exports, outcomes, Time Back, cost), never raw JSON. */
export function correctionValue(figure: string, value: unknown, copy: Copy): string {
  if (value === null || value === undefined) return copy.unavailable;
  if (typeof value !== 'object') return String(value);
  if ((value as { changed?: unknown }).changed === true) return copy.changed;
  if ((FIGURE_ORDER as string[]).includes(figure)) return figureText(figure as FigureName, { value, dataState: 'available', definition: '', evidence: {}, evidenceTruncated: false }, copy);
  return copy.changed;
}

export function correctionText(entry: CorrectionEntry, copy: Copy): string {
  const label = entry.figure === 'definitionVersion' ? copy.definitionVersion : copy.figure[entry.figure as FigureName] ?? entry.figure;
  if (entry.restricted) return `${label}: ${copy.ownerOnly}`;
  if (entry.evidenceOnly) return `${label}: ${copy.evidence}`;
  const word = (state: string) => copy.stateWord[state as ProofDataState] ?? state;
  const states = entry.dataStateBefore && entry.dataStateAfter ? ` ${copy.stateChange(word(entry.dataStateBefore), word(entry.dataStateAfter))}` : '';
  return `${label}: ${correctionValue(entry.figure, entry.before, copy)} → ${correctionValue(entry.figure, entry.after, copy)}${states}`;
}

/** A calendar date (YYYY-MM-DD, already in the workspace's zone) written in the reader's language, without shifting
 *  it through the viewer's own zone. Invalid input is returned as it came. */
export function calendarDate(iso: string, locale = 'en'): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const at = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  try {
    return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: 'UTC' }).format(at);
  } catch {
    return new Intl.DateTimeFormat('en', { dateStyle: 'medium', timeZone: 'UTC' }).format(at);
  }
}

/** When a decision starts to apply, as the workspace's own date: the server's `appliesFromDate`, else the stored
 *  instant read in the proof's zone (never the viewer's). */
export function appliesFromText(decision: Pick<StrategyDecision, 'appliesFrom' | 'appliesFromDate'>, timeZone: string | null | undefined, locale = 'en'): string | null {
  if (decision.appliesFromDate) return calendarDate(decision.appliesFromDate, locale);
  if (!decision.appliesFrom) return null;
  const at = decision.appliesFrom * 1000;
  for (const [tag, zone] of [[locale, timeZone || 'UTC'], ['en', timeZone || 'UTC'], ['en', 'UTC']]) {
    try {
      return new Intl.DateTimeFormat(tag, { dateStyle: 'medium', timeZone: zone }).format(at);
    } catch {
      /* an unusable language tag or zone: try the next pair */
    }
  }
  return null;
}

/** What deciding did to planning, in the reader's language, from the server's planning facts (not its English note):
 *  the first week that uses it and any week that was already planned without it. */
export function planningText(planning: DecideResult['planning'] | undefined, copy: Copy, locale = 'en'): string[] {
  if (!planning) return [];
  if (!planning.inEffect) return [copy.notInEffect];
  const out = planning.appliesFromDate ? [copy.appliesFromWeek(calendarDate(planning.appliesFromDate, locale))] : [];
  const planned = (planning.alreadyPlanned ?? []).filter((date) => typeof date === 'string' && date);
  if (planned.length) out.push(copy.alreadyPlanned(planned.map((date) => calendarDate(date, locale))));
  return out;
}

/** A failed proof or decision request in the reader's language: known codes and statuses have their own words;
 *  anything else is the generic line in Traditional Chinese (never the server's English) or the server's sentence. */
export function proofFailure(error: { code?: string; status?: number; message?: string } | null | undefined, copy: Copy, locale: 'en' | 'zh-Hant'): string {
  const code = error?.code;
  if (code && copy.errors[code]) return copy.errors[code];
  if (error?.status === 404) return copy.errors.not_found;
  if (error?.status === 403) return copy.errors.forbidden;
  if (error?.status === 409) return copy.errors.revision_conflict;
  return locale === 'en' && error?.message ? error.message : copy.errors.generic;
}

/** The proofs to show for one frequency: every loaded page in order, each proof once, with a just-recomputed or linked
 *  proof first when the pages don't contain it yet (so it is never invisible). */
export function mergeProofPages(pages: Pick<ProofList, 'proofs'>[] | undefined, pinned?: ProofView | null): ProofView[] {
  const seen = new Set<string>();
  const out: ProofView[] = [];
  for (const page of pages ?? []) {
    for (const proof of page.proofs ?? []) {
      if (seen.has(proof.proofId)) continue;
      seen.add(proof.proofId);
      out.push(proof);
    }
  }
  return pinned && !seen.has(pinned.proofId) ? [pinned, ...out] : out;
}

/**
 * The proof kept visible (opened from a link, or just recomputed) as the server has it now: its live read once that has
 * answered, the snapshot it was pinned with only until then. A decision, recompute or late data on it then shows its new
 * state instead of the copy taken when it was opened.
 */
export function livePinned<P extends { proofId: string }, W>(pinned: { proof: P; why: W } | null, live: P | null | undefined): { proof: P; why: W } | null {
  if (!pinned) return null;
  return live && live.proofId === pinned.proof.proofId ? { proof: live, why: pinned.why } : pinned;
}

/** A proof link (`/app/analytics?proof=gp_…`) names a proof id; anything else is ignored. */
export function linkedProofId(search: string): string | null {
  const id = new URLSearchParams(search).get('proof');
  return id && /^gp_[0-9a-f]{20}$/.test(id) ? id : null;
}

/** The decision buttons a member may use: owners only, and only the transitions the server allows for that status. */
export function decisionActions(decision: Pick<StrategyDecision, 'actions'>, owner: boolean): DecisionAction[] {
  return owner ? decision.actions.filter((a): a is DecisionAction => ['accept', 'edit', 'reject', 'revoke'].includes(a)) : [];
}

export function scopeText(scope: DecisionScope, copy: Copy, channelName: (id: string) => string = (id) => id): string[] {
  return (Object.keys(copy.scope) as (keyof DecisionScope)[]).filter((key) => scope?.[key] && key !== 'goalId').map((key) => `${copy.scope[key]}: ${key === 'channelId' ? channelName(String(scope[key])) : scope[key]}`);
}

/** What the week view shows: each applied decision with its current wording and whether it was revoked since planning,
 *  then each decision that could not apply, with its reason in words. Wording comes from the strategy list or what is
 *  in effect; a decision in neither is described, never shown as its raw id, and an unknown reason is said in words. */
export function appliedSummary(applied: AppliedDecision[] | undefined, notApplied: NotAppliedDecision[] | undefined, decisions: StrategyDecision[], copy: Copy,
                               inEffect: StrategyList['inEffect'] = []) {
  const byId = new Map<string, { statement: string; status?: string }>();
  for (const d of inEffect ?? []) byId.set(d.id, { statement: d.statement, status: 'accepted' });
  for (const d of decisions ?? []) byId.set(d.id, { statement: d.statement, status: d.status });
  const statement = (id: string) => byId.get(id)?.statement || copy.unknownDecision;
  return {
    applied: (applied ?? []).map((a) => ({ id: a.id, revision: a.revision, statement: statement(a.id), slots: (a.slotIds ?? []).length,
                                           revokedSince: byId.get(a.id)?.status === 'revoked' })),
    notApplied: (notApplied ?? []).map((n) => ({ id: n.id, revision: n.revision, statement: statement(n.id), reason: copy.reason[n.reason] ?? copy.reason.not_applied }))
  };
}

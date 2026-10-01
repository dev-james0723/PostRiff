/**
 * Plain-language presentation of Growth Loop proof revisions and next-week decisions (EN + zh-Hant). Pure functions,
 * checked by `node --test web/tests/growth-v2-loop.test.mjs`.
 *
 * Rules the wording keeps: unavailable is never shown as zero; assisted exports are never added to verified
 * publications; Time Back classes are listed separately (never one "measured" total); unknown provider cost is kept
 * apart from actual cost and never priced as zero; a decision is a planning input, not an approval.
 */
import type { AppliedDecision, CorrectionEntry, DecisionAction, DecisionScope, FigureName, NotAppliedDecision, ProofFigure, ProviderCost, StrategyDecision, TimeBackClass } from './proof-types';

/** Same rule as the brief (kept import-free so node's test runner loads this file directly). */
function loopLocale(locale: string | null | undefined): 'en' | 'zh-Hant' {
  const value = String(locale ?? '').toLowerCase();
  return value.startsWith('zh') || value.startsWith('yue') ? 'zh-Hant' : 'en';
}

// Result types as the Business results panel names them (features/growth/results/present.ts), never the raw codes.
const EN_RESULT_TYPES: Record<string, [string, string]> = {
  lead: ['lead', 'leads'], booking: ['booking', 'bookings'], newsletter_signup: ['newsletter sign-up', 'newsletter sign-ups'],
  sale: ['sale', 'sales'], click: ['click', 'clicks']
};
const ZH_RESULT_TYPES: Record<string, string> = { lead: '潛在客戶', booking: '預約', newsletter_signup: '電子報訂閱', sale: '銷售', click: '點擊' };

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
    applies_from_later: 'applies from a later week', already_applied: 'already planned in an earlier week', source_unavailable: 'its saved idea was removed',
    account_unavailable: 'its account is disconnected', goal_not_active: 'its goal is not active', no_matching_slot: 'no planned post matches its scope'
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
  /** A structured value the server only marks as changed (too large to keep in a correction note). */
  changed: 'changed',
  resultCount: (n: number, type: string) => {
    const words = EN_RESULT_TYPES[type];
    return words ? `${n} ${n === 1 ? words[0] : words[1]}` : `${n} ${type.replaceAll('_', ' ')}`;
  },
  /** The proof's fixed limitation sentences (proof/model.py LIMITATIONS) are sent in English and shown as sent. */
  limitations: {} as Record<string, string>
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
    applies_from_later: '從較後的一週開始生效', already_applied: '已在較早的一週計劃中使用', source_unavailable: '其儲存的點子已被移除',
    account_unavailable: '其帳戶已中斷連接', goal_not_active: '其目標並未啟用', no_matching_slot: '沒有計劃貼文符合其範圍'
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
  changed: '已變更',
  resultCount: (n: number, type: string) => `${ZH_RESULT_TYPES[type] ?? type.replaceAll('_', ' ')} ${n}`,
  limitations: {
    'Delivery is not growth: verified publications and accepted work say what was done, not what it caused.':
      '交付不等於增長：已驗證的發佈和已採納的內容只說明做了甚麼，不代表它帶來了甚麼。',
    'Missing analytics never erase a verified delivery; unavailable figures stay unavailable, never zero.':
      '缺少分析數據不會抹去已驗證的交付；不可用的數字會維持不可用，不會當作零。',
    'Assisted exports are counted apart from verified publications and are never added to them.':
      '輔助匯出與已驗證的發佈分開計算，永遠不會加在一起。',
    'Time Back classes (estimated, personalized, measured) are shown separately; they are not one measured figure.':
      '節省的時間按類別（估計、個人化、實測）分開顯示，不會合併成一個實測數字。'
  }
};

export function proofCopy(locale: string | null | undefined): Copy {
  return loopLocale(locale) === 'zh-Hant' ? ZH : EN;
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
    const counts = Object.entries(bucket.counts ?? {}).map(([type, n]) => copy.resultCount(n, type));
    return `${label}: ${counts.length ? counts.join(', ') : '0'}`;
  }).join(' · ');
}

/** A figure's value in words, never raw data: the figure view and the correction note both read it this way. */
function valueText(name: string, value: unknown, copy: Copy): string {
  if (value === null || value === undefined) return copy.unavailable;
  const record = typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  if (record && record.changed === true && Object.keys(record).length === 1) return copy.changed;
  if (name === 'assistedExports') return copy.exports(value as Record<string, number>);
  if (name === 'outcomes') return outcomeText(value as Record<string, unknown>, copy);
  if (name === 'timeBack') {
    const classes = value as TimeBackClass[];
    return classes.length ? classes.map((c) => `${copy.minutes(Math.round(c.savedSeconds / 60))} ${copy.confidence[c.confidence] ?? c.confidence}`).join(' · ') : copy.none;
  }
  if (name === 'providerCost') {
    const cost = value as ProviderCost;
    const parts = [copy.actualCost(usd(cost.actualUsdMicro), cost.actualEntries)];
    if (cost.unknownEntries) parts.push(copy.unknownCost(cost.unknownEntries, usd(cost.unknownReservedEstimateUsdMicro)));
    return parts.join(' · ');
  }
  return typeof value === 'object' ? copy.changed : String(value);
}

/** One figure in words. Unavailable and owner-only figures say so; no figure is ever shown as a fabricated zero. */
export function figureText(name: FigureName, figure: ProofFigure | undefined, copy: Copy): string {
  if (!figure) return copy.unavailable;
  if (figure.dataState === 'restricted') return copy.ownerOnly;
  if (figure.value === null || figure.value === undefined || figure.dataState === 'unavailable') {
    const reason = figure.reason ? copy.reason[figure.reason] ?? figure.reason : null;
    return reason ? `${copy.unavailable} — ${reason}` : copy.unavailable;
  }
  return valueText(name, figure.value, copy);
}

/** A limitation sentence in the person's language (the server sends the fixed ones in English; anything new as sent). */
export function limitationText(text: string, copy: Copy): string {
  return copy.limitations[text] ?? text;
}

/** The ids each figure counts, grouped and labelled, for the evidence disclosure. */
export function evidenceGroups(figure: ProofFigure | undefined): { label: string; ids: string[] }[] {
  return Object.entries(figure?.evidence ?? {}).filter(([, ids]) => ids.length).map(([key, ids]) => ({ label: key.replace(/([A-Z])/g, ' $1').toLowerCase().replace(/ ids$/, ' ids'), ids }));
}

export function correctionText(entry: CorrectionEntry, copy: Copy): string {
  const label = copy.figure[entry.figure as FigureName] ?? entry.figure;
  if (entry.restricted) return `${label}: ${copy.ownerOnly}`;
  if (entry.evidenceOnly) return `${label}: ${copy.evidence}`;
  // In words, like the figure itself: a provenance summary as raw JSON was unreadable and too wide for a phone.
  return `${label}: ${valueText(entry.figure, entry.before, copy)} → ${valueText(entry.figure, entry.after, copy)}`;
}

/** The decision buttons a member may use: owners only, and only the transitions the server allows for that status. */
export function decisionActions(decision: Pick<StrategyDecision, 'actions'>, owner: boolean): DecisionAction[] {
  return owner ? decision.actions.filter((a): a is DecisionAction => ['accept', 'edit', 'reject', 'revoke'].includes(a)) : [];
}

export function scopeText(scope: DecisionScope, copy: Copy, channelName: (id: string) => string = (id) => id): string[] {
  return (Object.keys(copy.scope) as (keyof DecisionScope)[]).filter((key) => scope?.[key] && key !== 'goalId').map((key) => `${copy.scope[key]}: ${key === 'channelId' ? channelName(String(scope[key])) : scope[key]}`);
}

/** What the week view shows: each applied decision with its current wording and whether it was revoked since planning,
 *  then each decision that could not apply, with its reason in words. */
export function appliedSummary(applied: AppliedDecision[] | undefined, notApplied: NotAppliedDecision[] | undefined, decisions: StrategyDecision[], copy: Copy) {
  const byId = new Map(decisions.map((d) => [d.id, d]));
  return {
    applied: (applied ?? []).map((a) => ({ id: a.id, revision: a.revision, statement: byId.get(a.id)?.statement ?? a.id, slots: a.slotIds.length,
                                           revokedSince: byId.get(a.id)?.status === 'revoked' })),
    notApplied: (notApplied ?? []).map((n) => ({ id: n.id, revision: n.revision, statement: byId.get(n.id)?.statement ?? n.id, reason: copy.reason[n.reason] ?? n.reason }))
  };
}

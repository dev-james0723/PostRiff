/**
 * The coverage receipt as the workspace reports it: five states and, per account, what was retrieved, what can be
 * used and what was left out. Every sentence is built from a number or flag the route returned. A total the platform
 * does not disclose is called unknown, and no sentence divides by it.
 */
import { EXCLUSION_ORDER, exclusionPhrase, languageName, pick } from './labels';
import type { Language, Triple } from './labels';
import type { CoverageAccount, CoverageStateId, ImportRoute, Stamp, VoiceCoverage, VoiceGroup, VoiceImport, VoiceImportsView, VoiceScope } from './types';

export type CoverageStatus = 'done' | 'partial' | 'pending' | 'none';
export const COVERAGE_STATES: CoverageStateId[] = ['connected', 'retrieved', 'processed', 'proposed', 'approved'];
/** Fewer eligible posts than this say nothing reliable about a voice. */
export const MIN_ELIGIBLE = 3;
const STATUS_WORDS: CoverageStatus[] = ['done', 'partial', 'pending', 'none'];
const ACTIVE = ['pending', 'receiving', 'running'];

const count = (value: unknown) => (typeof value === 'number' && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0);
const sum = (values: Record<string, number | undefined> | undefined) => Object.values(values ?? {}).reduce<number>((total, value) => total + count(value), 0);

/** Posts stored for an account whose author is not yet known: not usable and not left out. */
export function waitingForAuthor(account: CoverageAccount): number {
  return Math.max(0, count(account.retrieved) - count(account.eligible) - sum(account.excluded));
}

export interface CoverageTotals {
  accounts: number;
  retrieved: number;
  eligible: number;
  /** Eligible posts in accounts blended into the brand voice: what a brand proposal is built from. */
  brandEligible: number;
  excluded: number;
  waiting: number;
}

export function coverageTotals(coverage: VoiceCoverage | null | undefined): CoverageTotals {
  const accounts = coverage?.accounts ?? [];
  return {
    accounts: accounts.length,
    retrieved: accounts.reduce((total, account) => total + count(account.retrieved), 0),
    eligible: accounts.reduce((total, account) => total + count(account.eligible), 0),
    brandEligible: accounts.reduce((total, account) => total + (account.voiceScope === 'separate' ? 0 : count(account.eligible)), 0),
    excluded: accounts.reduce((total, account) => total + sum(account.excluded), 0),
    waiting: accounts.reduce((total, account) => total + waitingForAuthor(account), 0)
  };
}

/**
 * Connected, retrieved, processed, profile proposed, profile approved. The workspace states each one; a state it
 * leaves out is read from the account rows, and the two profile states are never assumed.
 */
export function coverageStates(coverage: VoiceCoverage | null | undefined): { id: CoverageStateId; status: CoverageStatus }[] {
  const accounts = coverage?.accounts ?? [];
  const retrieved = coverageTotals(coverage).retrieved;
  const complete = accounts.length > 0 && accounts.every((account) => account.moreRemaining === false);
  const fallback: Record<CoverageStateId, CoverageStatus> = {
    connected: accounts.length ? 'done' : 'none',
    retrieved: retrieved ? (complete ? 'done' : 'partial') : accounts.length ? 'pending' : 'none',
    processed: retrieved ? (complete ? 'done' : 'partial') : 'none',
    proposed: 'none',
    approved: 'none'
  };
  return COVERAGE_STATES.map((id) => {
    const stated = coverage?.states?.[id];
    return { id, status: STATUS_WORDS.includes(stated as CoverageStatus) ? (stated as CoverageStatus) : fallback[id] };
  });
}

function formatter(language: Language) {
  const numbers = new Intl.NumberFormat(language);
  const months = new Intl.DateTimeFormat(language, { year: 'numeric', month: 'short', timeZone: 'UTC' });
  return {
    n: (value: number) => numbers.format(value),
    /** English only: "1 post", "312 posts". */
    posts: (value: number) => `${numbers.format(value)} ${value === 1 ? 'post' : 'posts'}`,
    month: (value: Stamp | undefined) => {
      const ms = stampMs(value);
      return ms === null ? '' : months.format(ms);
    },
    t: (...value: Triple) => pick(language, value)
  };
}

/** Epoch milliseconds of an ISO string or of epoch seconds; `null` when there is no usable time. */
export function stampMs(value: Stamp | undefined): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value < 1e12 ? value * 1000 : value;
  if (typeof value !== 'string' || !value) return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? ms : null;
}

/** One account's receipt, a sentence per fact. */
export function accountLines(account: CoverageAccount, language: Language): string[] {
  const { n, posts, month, t } = formatter(language);
  const retrieved = count(account.retrieved);
  if (!retrieved) return [t('No posts retrieved yet.', '尚未取得任何貼文。', '尚未获取任何帖子。')];
  const lines = [
    account.totalKnown
      ? t(`${posts(retrieved)} retrieved; the source lists no more.`, `已取得 ${n(retrieved)} 篇貼文，來源沒有列出更多。`, `已获取 ${n(retrieved)} 篇帖子，来源没有列出更多。`)
      : t(`${posts(retrieved)} retrieved; the platform does not say how many exist.`, `已取得 ${n(retrieved)} 篇貼文；平台沒有說明總共有多少篇。`, `已获取 ${n(retrieved)} 篇帖子；平台没有说明总共有多少篇。`)
  ];
  if (account.moreRemaining === true) lines.push(t('More posts exist that were not read.', '還有貼文尚未讀取。', '还有帖子尚未读取。'));
  else if (account.moreRemaining === false && !account.totalKnown) lines.push(t('Rafii read to the end of what the platform returns.', 'Rafii 已讀到平台所提供內容的盡頭。', 'Rafii 已读到平台所提供内容的尽头。'));
  const from = month(account.observed?.oldest);
  const to = month(account.observed?.newest);
  if (from && to) lines.push(from === to ? t(`Posts from ${from}.`, `貼文日期：${from}。`, `帖子日期：${from}。`) : t(`Posts from ${from} to ${to}.`, `貼文日期由 ${from} 至 ${to}。`, `帖子日期由 ${from} 至 ${to}。`));
  lines.push(t(`${n(count(account.eligible))} can be used for the profile.`, `${n(count(account.eligible))} 篇可用於建立風格檔案。`, `${n(count(account.eligible))} 篇可用于建立风格档案。`));
  const waiting = waitingForAuthor(account);
  if (waiting) lines.push(t(waiting === 1 ? '1 post waits for you to say who wrote it.' : `${n(waiting)} posts wait for you to say who wrote them.`, `${n(waiting)} 篇等待你確認作者。`, `${n(waiting)} 篇等待你确认作者。`));
  const reasons = [...EXCLUSION_ORDER, ...Object.keys(account.excluded ?? {}).filter((reason) => !(EXCLUSION_ORDER as readonly string[]).includes(reason))];
  const left = reasons.filter((reason) => count(account.excluded?.[reason])).map((reason) => exclusionPhrase(reason, count(account.excluded?.[reason]), language, n));
  if (left.length) lines.push(t(`Left out: ${left.join(', ')}.`, `未採用：${left.join('、')}。`, `未采用：${left.join('、')}。`));
  const languages = Object.entries(account.languages ?? {})
    .filter(([, total]) => count(total))
    .toSorted((a, b) => count(b[1]) - count(a[1]))
    .map(([tag, total]) => `${languageName(tag, language)} ${n(count(total))}`);
  if (languages.length) lines.push(t(`Languages: ${languages.join(', ')}.`, `語言：${languages.join('、')}。`, `语言：${languages.join('、')}。`));
  return lines;
}

/** What is and is not analysed. Images and video are named so nobody assumes they were read. */
export function modalityLine(coverage: VoiceCoverage | null | undefined, language: Language): string {
  const { t } = formatter(language);
  const unread = (['images', 'video'] as const).filter((kind) => coverage?.modality?.[kind] !== 'analysed');
  if (unread.length === 2) return t('Text is analysed. Images and video are not analysed.', '只分析文字，不分析圖片及影片。', '仅分析文字，不分析图片及视频。');
  if (unread[0] === 'images') return t('Text and video are analysed. Images are not analysed.', '分析文字及影片，不分析圖片。', '分析文字及视频，不分析图片。');
  if (unread[0] === 'video') return t('Text and images are analysed. Video is not analysed.', '分析文字及圖片，不分析影片。', '分析文字及图片，不分析视频。');
  return t('Text, images and video are analysed.', '分析文字、圖片及影片。', '分析文字、图片及视频。');
}

/** The whole workspace in a few sentences, for the top of the receipt. */
export function coverageLines(coverage: VoiceCoverage | null | undefined, language: Language): string[] {
  const { n, posts, t } = formatter(language);
  const accounts = coverage?.accounts ?? [];
  const totals = coverageTotals(coverage);
  if (!totals.retrieved) return [t('No posts retrieved yet.', '尚未取得任何貼文。', '尚未获取任何帖子。'), modalityLine(coverage, language)];
  const unknown = accounts.filter((account) => count(account.retrieved) && !account.totalKnown).length;
  const lines: string[] = [];
  if (accounts.length === 1) lines.push(accountLines(accounts[0], language)[0]);
  else {
    const head = t(`${posts(totals.retrieved)} retrieved from ${n(accounts.length)} accounts`, `已從 ${n(accounts.length)} 個帳戶取得 ${n(totals.retrieved)} 篇貼文`, `已从 ${n(accounts.length)} 个账户获取 ${n(totals.retrieved)} 篇帖子`);
    lines.push(
      unknown === 0
        ? t(`${head}; the sources list no more.`, `${head}，來源沒有列出更多。`, `${head}，来源没有列出更多。`)
        : unknown === accounts.length
          ? t(`${head}; the platforms do not say how many exist.`, `${head}；平台沒有說明總共有多少篇。`, `${head}；平台没有说明总共有多少篇。`)
          : t(`${head}; the total is unknown for ${n(unknown)} of them.`, `${head}；其中 ${n(unknown)} 個帳戶的總數不明。`, `${head}；其中 ${n(unknown)} 个账户的总数不明。`)
    );
  }
  const connected = accounts.filter((account) => account.route === 'official_api').length;
  const exported = accounts.filter((account) => account.route === 'platform_export').length;
  if (connected && exported) lines.push(t(`Sources: ${n(connected)} connected, ${n(exported)} from export files.`, `來源：${n(connected)} 個已連接帳戶、${n(exported)} 個來自匯出檔案。`, `来源：${n(connected)} 个已连接账户、${n(exported)} 个来自导出文件。`));
  const usable = t(`${n(totals.eligible)} can be used for the profile`, `${n(totals.eligible)} 篇可用於建立風格檔案`, `${n(totals.eligible)} 篇可用于建立风格档案`);
  const parts = [usable];
  if (totals.excluded) parts.push(t(totals.excluded === 1 ? '1 was left out' : `${n(totals.excluded)} were left out`, `${n(totals.excluded)} 篇未採用`, `${n(totals.excluded)} 篇未采用`));
  if (totals.waiting) parts.push(t(totals.waiting === 1 ? '1 waits for an author' : `${n(totals.waiting)} wait for an author`, `${n(totals.waiting)} 篇等待確認作者`, `${n(totals.waiting)} 篇等待确认作者`));
  lines.push(`${parts.join(t('; ', '；', '；'))}${t('.', '。', '。')}`);
  lines.push(modalityLine(coverage, language));
  return lines;
}

/* ---------- accounts and their runs ---------- */

export function importActive(item: Pick<VoiceImport, 'status'> | null | undefined): boolean {
  return Boolean(item && ACTIVE.includes(item.status));
}

export function anyImportActive(view: Pick<VoiceImportsView, 'imports'> | null | undefined): boolean {
  return Boolean(view?.imports?.some(importActive));
}

export interface AccountReceipt {
  key: string;
  provider: string;
  accountKey: string;
  label: string;
  account: CoverageAccount | null;
  /** This account's runs, newest first. */
  imports: VoiceImport[];
  latest: VoiceImport | null;
  active: VoiceImport | null;
  /** Every route a run of this account used: an account can be read through a connection and from a file. */
  routes: ImportRoute[];
  voiceScope: VoiceScope | null;
}

/** One receipt per account: the coverage row joined to its runs. An account with a run and no stored post still gets a receipt. */
export function accountReceipts(view: Pick<VoiceImportsView, 'imports' | 'coverage'> | null | undefined): AccountReceipt[] {
  const receipts = new Map<string, AccountReceipt>();
  const receipt = (provider: string, accountKey: string) => {
    const key = `${provider}:${accountKey}`;
    let found = receipts.get(key);
    if (!found) {
      found = { key, provider, accountKey, label: accountKey, account: null, imports: [], latest: null, active: null, routes: [], voiceScope: null };
      receipts.set(key, found);
    }
    return found;
  };
  for (const account of view?.coverage?.accounts ?? []) {
    const entry = receipt(account.provider, account.accountKey);
    entry.account = account;
    entry.label = account.label || account.accountKey;
    entry.voiceScope = account.voiceScope ?? null;
    if ((account.route === 'official_api' || account.route === 'platform_export') && !entry.routes.includes(account.route)) entry.routes.push(account.route);
  }
  const runs = (view?.imports ?? []).toSorted((a, b) => (stampMs(b.createdAt) ?? 0) - (stampMs(a.createdAt) ?? 0));
  for (const run of runs) {
    const entry = receipt(run.provider, run.accountKey);
    entry.imports.push(run);
    if (!entry.latest) {
      entry.latest = run;
      if (run.accountLabel) entry.label = run.accountLabel;
      entry.voiceScope = entry.voiceScope ?? run.consent?.voiceScope ?? null;
    }
    if (!entry.active && importActive(run)) entry.active = run;
    if (!entry.routes.includes(run.route)) entry.routes.push(run.route);
  }
  return [...receipts.values()];
}

/**
 * The voices a proposal can be built for: the brand (every account blended into it) and each account kept separate.
 * The workspace's own list is used when it sends one.
 */
export function voiceGroups(view: Pick<VoiceImportsView, 'coverage' | 'groups'> | null | undefined): VoiceGroup[] {
  if (view?.groups?.length) return view.groups;
  const accounts = view?.coverage?.accounts ?? [];
  const blended = accounts.filter((account) => account.voiceScope !== 'separate');
  const groups: VoiceGroup[] = [];
  if (blended.length || !accounts.length) groups.push({ key: 'brand', eligible: blended.reduce((total, account) => total + count(account.eligible), 0) });
  for (const account of accounts) {
    if (account.voiceScope === 'separate') groups.push({ key: `separate:${account.provider}:${account.accountKey}`, label: account.label || account.accountKey, eligible: count(account.eligible) });
  }
  return groups;
}

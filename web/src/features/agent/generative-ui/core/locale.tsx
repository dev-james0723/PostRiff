'use client';
/**
 * Locale, time zone and native copy for generated views (lane C; lane E uses the same context).
 *
 * `RafiiGenerativeMessage` provides one `GenUiLocale` per message from the person's preferences (`lib/time.ts`
 * `timeDefaults()`, set by `PreferencesProvider`; browser defaults otherwise, e.g. in the founder app). Generated text is
 * written by the presenter in the conversation's language; this context only covers what Rafii itself renders: numbers,
 * dates, units and short native labels (not available, as of, coverage, confirmations), in English, Traditional Chinese
 * and Simplified Chinese. Unknown values are never formatted as zero.
 *
 *   const l = useGenUiLocale();
 *   l.formatNumber(1234.5) · l.formatDate('2026-10-08') · l.formatDateTime(1760000000) · l.t('notAvailable')
 */
import { createContext, type JSX, type ReactNode, useContext } from 'react';
import { timeDefaults } from '@/lib/time';

export type GenUiLanguage = 'en' | 'zh-Hant' | 'zh-Hans';
export type ValueKind = 'text' | 'number' | 'percent' | 'currency' | 'duration' | 'date' | 'datetime' | 'status' | 'link';

const MESSAGES = {
  notAvailable: ['Not available', '未有資料', '暂无数据'],
  notMeasured: ['Not measured', '未有量度', '未测量'],
  loading: ['Loading…', '載入中…', '加载中…'],
  waitingForData: ['Waiting for data…', '等候資料…', '等待数据…'],
  preparing: ['Preparing this view…', '正在準備畫面…', '正在准备视图…'],
  updating: ['Updating this view…', '正在更新畫面…', '正在更新视图…'],
  ready: ['View ready', '畫面已準備好', '视图已就绪'],
  viewFailed: ['This view couldn’t be shown. The answer above is complete.', '未能顯示這個畫面，上面的回答已經完整。', '无法显示这个视图，上面的回答已经完整。'],
  viewOutdated: ['This saved view was made with an earlier version and can’t be shown here.', '這個已儲存的畫面由較早的版本建立，無法在此顯示。', '这个已保存的视图由较早的版本创建，无法在此显示。'],
  viewTooLarge: ['This view is too large to show here.', '這個畫面太大，無法在此顯示。', '这个视图太大，无法在此显示。'],
  retryView: ['Try the view again', '重新製作畫面', '重新生成视图'],
  denied: ['You don’t have access to this data.', '你沒有權限查看這些資料。', '你没有权限查看这些数据。'],
  unavailable: ['This data isn’t available right now.', '暫時無法取得這些資料。', '暂时无法获取这些数据。'],
  stale: ['Showing earlier data.', '正在顯示較早的資料。', '正在显示较早的数据。'],
  partial: ['Some data is missing.', '部分資料缺失。', '部分数据缺失。'],
  empty: ['Nothing to show.', '沒有可顯示的內容。', '没有可显示的内容。'],
  asOf: ['As of {time}', '截至 {time}', '截至 {time}'],
  coverage: ['{known} of {total} covered', '已涵蓋 {known}/{total}', '已覆盖 {known}/{total}'],
  savedView: ['Saved view · data as of {time}', '已儲存的畫面 · 資料截至 {time}', '已保存的视图 · 数据截至 {time}'],
  showCurrent: ['Show current data', '顯示最新資料', '显示最新数据'],
  showTable: ['Show data table', '顯示資料表', '显示数据表'],
  hideTable: ['Hide data table', '隱藏資料表', '隐藏数据表'],
  chartLabel: ['{kind} chart: {series} by {x}', '{kind}圖：按{x}顯示{series}', '{kind}图：按{x}显示{series}'],
  lineChart: ['Line', '折線', '折线'],
  barChart: ['Bar', '棒形', '柱状'],
  nextPage: ['Next page', '下一頁', '下一页'],
  firstPage: ['Back to first page', '返回第一頁', '返回第一页'],
  sortBy: ['Sort by {label}', '按{label}排序', '按{label}排序'],
  selectedCount: ['{count} selected', '已選 {count} 項', '已选 {count} 项'],
  maxReached: ['You can pick up to {max}.', '最多可選 {max} 項。', '最多可选 {max} 项。'],
  previewUnavailable: ['Preview isn’t available', '無法預覽', '无法预览'],
  open: ['Open', '開啟', '打开'],
  start: ['Start', '開始', '开始'],
  end: ['End', '結束', '结束'],
  rangeTooLong: ['Pick at most 366 days.', '最多可選 366 日。', '最多可选 366 天。'],
  rangeOrder: ['The end date is before the start date.', '結束日期早於開始日期。', '结束日期早于开始日期。'],
  required: ['Required', '必填', '必填'],
  tooShort: ['Too short', '太短', '太短'],
  tooLong: ['Too long', '太長', '太长'],
  actionUnavailable: ['This action isn’t available here.', '這個操作在此不可用。', '这个操作在此不可用。'],
  working: ['Working…', '處理中…', '处理中…'],
  confirm: ['Confirm', '確認', '确认'],
  cancel: ['Cancel', '取消', '取消'],
  close: ['Close', '關閉', '关闭'],
  tryAgain: ['Try again', '再試一次', '再试一次'],
  timeZoneNote: ['Times in {zone}', '時間以 {zone} 顯示', '时间以 {zone} 显示'],
  costNote: ['Cost: {cost}', '費用：{cost}', '费用：{cost}'],
  outcomePrepared: ['Prepared for your review. Nothing has been applied yet.', '已準備好讓你審閱，尚未套用任何變更。', '已准备好供你审阅，尚未应用任何更改。'],
  outcomeApplied: ['Done.', '已完成。', '已完成。'],
  outcomeAppliedUnverified: ['Sent. Rafii hasn’t confirmed the result yet.', '已送出，Rafii 仍未確認結果。', '已发送，Rafii 尚未确认结果。'],
  outcomePending: ['Still in progress. Check again in a moment.', '仍在處理中，請稍後再查看。', '仍在处理中，请稍后再查看。'],
  outcomeConflict: ['This changed elsewhere, so nothing was applied.', '內容已在別處更改，因此沒有套用任何變更。', '内容已在别处更改，因此没有应用任何更改。'],
  outcomeRejected: ['This wasn’t allowed, so nothing was applied.', '這項操作不獲允許，因此沒有套用任何變更。', '这项操作不被允许，因此没有应用任何更改。'],
  outcomeFailed: ['That didn’t go through. Nothing was applied.', '未能完成，沒有套用任何變更。', '未能完成，没有应用任何更改。'],
  dirtyRemoved: ['The updated view leaves out fields you were editing: {fields}.', '更新後的畫面不包括你正在編輯的欄位：{fields}。', '更新后的视图不包括你正在编辑的字段：{fields}。'],
  keepEarlier: ['Keep the earlier view', '保留較早的畫面', '保留较早的视图'],
  useUpdate: ['Use the updated view', '使用更新後的畫面', '使用更新后的视图'],
  linkBlocked: ['This link can’t be opened from here.', '無法從這裡開啟這個連結。', '无法从这里打开这个链接。'],
  unknownComponent: ['This part can’t be shown.', '無法顯示這個部分。', '无法显示这个部分。'],
} as const;

export type GenUiMessageKey = keyof typeof MESSAGES;

export interface GenUiLocale {
  /** BCP 47 tag used for Intl formatting (the person's preference). */
  locale: string;
  /** Language of Rafii's own short labels. */
  language: GenUiLanguage;
  /** IANA zone every date and time is shown in. */
  timeZone: string;
  dir: 'ltr' | 'rtl';
  t(key: GenUiMessageKey, vars?: Readonly<Record<string, string | number>>): string;
  /** `null`/`undefined`/non-finite → "Not available" (never 0). */
  formatNumber(value: unknown, options?: Intl.NumberFormatOptions): string;
  /** Format a value by column kind; unknown values → "Not available". */
  formatValue(value: unknown, kind?: ValueKind, unit?: string | null): string;
  /** ISO date/time, `YYYY-MM-DD` calendar date, or epoch seconds/milliseconds. */
  formatDate(value: unknown, options?: Intl.DateTimeFormatOptions): string;
  formatDateTime(value: unknown): string;
  formatRelative(value: unknown, now?: number): string;
  /** Epoch milliseconds of a date-ish value, or null. */
  toEpochMs(value: unknown): number | null;
}

const RTL = /^(ar|fa|he|iw|ur|ps|sd|ug|yi|dv|ckb)(-|$)/i;

export function languageFor(locale: string): GenUiLanguage {
  const tag = locale.toLowerCase();
  if (/^(yue|zh-hant|zh-hk|zh-tw|zh-mo)/.test(tag)) return 'zh-Hant';
  if (tag.startsWith('zh')) return 'zh-Hans';
  return 'en';
}

function usable(make: () => unknown): boolean {
  try {
    make();
    return true;
  } catch {
    return false;
  }
}

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Pure: build a locale object (tests call this directly). */
export function createGenUiLocale(input: { locale?: string | null; timeZone?: string | null } = {}): GenUiLocale {
  const locale = input.locale && usable(() => new Intl.NumberFormat(input.locale as string)) ? input.locale : 'en';
  const timeZone =
    input.timeZone && usable(() => new Intl.DateTimeFormat('en', { timeZone: input.timeZone as string }))
      ? input.timeZone
      : browserZone();
  const language = languageFor(locale);
  const index = language === 'zh-Hant' ? 1 : language === 'zh-Hans' ? 2 : 0;
  const numberFormats = new Map<string, Intl.NumberFormat>();
  const numberFormat = (options: Intl.NumberFormatOptions = {}) => {
    const key = JSON.stringify(options);
    let format = numberFormats.get(key);
    if (!format) {
      try {
        format = new Intl.NumberFormat(locale, options);
      } catch {
        format = new Intl.NumberFormat(locale);
      }
      numberFormats.set(key, format);
    }
    return format;
  };
  const t: GenUiLocale['t'] = (key, vars) => {
    const template: string = MESSAGES[key]?.[index] ?? MESSAGES[key]?.[0] ?? '';
    if (!vars) return template;
    return template.replace(/\{([a-zA-Z]+)\}/g, (whole, name: string) =>
      Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole,
    );
  };
  const toEpochMs = (value: unknown): number | null => {
    if (typeof value === 'number' && Number.isFinite(value)) return value < 1e12 ? value * 1000 : value;
    if (typeof value !== 'string' || !value.trim()) return null;
    const date = DATE_ONLY.exec(value.trim());
    if (date) return Date.UTC(Number(date[1]), Number(date[2]) - 1, Number(date[3]));
    const ms = Date.parse(value);
    return Number.isFinite(ms) ? ms : null;
  };
  const formatDate: GenUiLocale['formatDate'] = (value, options = {}) => {
    const ms = toEpochMs(value);
    if (ms === null) return t('notAvailable');
    // A calendar date (YYYY-MM-DD) is the same day everywhere; never shift it across zones.
    const calendar = typeof value === 'string' && DATE_ONLY.test(value.trim());
    try {
      return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeZone: calendar ? 'UTC' : timeZone, ...options }).format(ms);
    } catch {
      return new Date(ms).toISOString().slice(0, 10);
    }
  };
  const formatDateTime: GenUiLocale['formatDateTime'] = (value) => {
    if (typeof value === 'string' && DATE_ONLY.test(value.trim())) return formatDate(value);
    const ms = toEpochMs(value);
    if (ms === null) return t('notAvailable');
    try {
      return new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short', timeZone }).format(ms);
    } catch {
      return new Date(ms).toISOString();
    }
  };
  const formatNumber: GenUiLocale['formatNumber'] = (value, options) => {
    if (typeof value !== 'number' || !Number.isFinite(value)) return t('notAvailable');
    return numberFormat(options).format(value);
  };
  const formatRelative: GenUiLocale['formatRelative'] = (value, now = Date.now()) => {
    const ms = toEpochMs(value);
    if (ms === null) return t('notAvailable');
    const diff = (ms - now) / 1000;
    const abs = Math.abs(diff);
    let rtf: Intl.RelativeTimeFormat;
    try {
      rtf = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    } catch {
      rtf = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });
    }
    if (abs < 60) return rtf.format(Math.round(diff), 'second');
    if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
    if (abs < 86400 * 30) return rtf.format(Math.round(diff / 86400), 'day');
    return rtf.format(Math.round(diff / (86400 * 30)), 'month');
  };
  const formatValue: GenUiLocale['formatValue'] = (value, kind = 'text', unit) => {
    if (value === null || value === undefined || value === '') return t('notAvailable');
    const withUnit = (text: string) => (unit ? `${text} ${unit}` : text);
    switch (kind) {
      case 'number':
        return typeof value === 'number' ? withUnit(formatNumber(value)) : t('notAvailable');
      case 'percent':
        // Server convention: percentages arrive as ratios (0.125 = 12.5 %).
        return typeof value === 'number' ? formatNumber(value, { style: 'percent', maximumFractionDigits: 1 }) : t('notAvailable');
      case 'currency':
        if (typeof value !== 'number') return t('notAvailable');
        return unit && /^[A-Z]{3}$/.test(unit) ? formatNumber(value, { style: 'currency', currency: unit }) : withUnit(formatNumber(value));
      case 'duration': {
        if (typeof value !== 'number' || !Number.isFinite(value)) return t('notAvailable');
        const seconds = Math.round(value);
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = seconds % 60;
        return h ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}` : `${m}:${String(s).padStart(2, '0')}`;
      }
      case 'date':
        return formatDate(value);
      case 'datetime':
        return formatDateTime(value);
      default:
        if (typeof value === 'number') return withUnit(formatNumber(value));
        if (typeof value === 'boolean') return String(value);
        if (typeof value === 'string') return withUnit(value);
        return t('notAvailable');
    }
  };
  return {
    locale,
    language,
    timeZone,
    dir: RTL.test(locale) ? 'rtl' : 'ltr',
    t,
    formatNumber,
    formatValue,
    formatDate,
    formatDateTime,
    formatRelative,
    toEpochMs,
  };
}

let fallback: GenUiLocale | null = null;
let fallbackKey = '';

/** The app-wide default (person's preferences when set, browser defaults otherwise). */
export function defaultGenUiLocale(): GenUiLocale {
  const { locale, timeZone } = timeDefaults();
  const key = `${locale}|${timeZone ?? ''}`;
  if (!fallback || key !== fallbackKey) {
    fallback = createGenUiLocale({ locale, timeZone });
    fallbackKey = key;
  }
  return fallback;
}

const GenUiLocaleContext = createContext<GenUiLocale | null>(null);

export function GenUiLocaleProvider(props: { value: GenUiLocale; children: ReactNode }): JSX.Element {
  return <GenUiLocaleContext.Provider value={props.value}>{props.children}</GenUiLocaleContext.Provider>;
}

/** The locale of the nearest generated view; outside one, the app default (never throws). */
export function useGenUiLocale(): GenUiLocale {
  return useContext(GenUiLocaleContext) ?? defaultGenUiLocale();
}

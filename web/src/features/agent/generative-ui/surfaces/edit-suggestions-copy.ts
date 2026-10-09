/**
 * Fixed copy of the "Change this view" suggestion chips (lane F), in English, Traditional Chinese (Hong Kong wording) and
 * Simplified Chinese, in that order. Data only, no React, no network.
 *
 * Every chip has a short label (what the chip shows) and an instruction (what a tap puts in the "What should change?" field,
 * exactly what would be sent if the person then presses "Update view"). The only variable parts are counts (`{n}`), ISO
 * dates (`{start}`, `{end}`) and the metric names of `METRIC_NAMES`. Nothing here is ever filled with a record title, a
 * binding name, a manifest description or anything the person wrote. Words with a fixed meaning keep it (journeys/copy.ts):
 * "scheduled" is the drafts filter's own state; "saved" sources are the ones the workspace stored.
 */
import type { GenUiLanguage } from '../core/locale';

export type Tri = readonly [en: string, zhHant: string, zhHans: string];
export interface ChipText {
  label: Tri;
  instruction: Tri;
}

const INDEX: Readonly<Record<GenUiLanguage, 0 | 1 | 2>> = { en: 0, 'zh-Hant': 1, 'zh-Hans': 2 };

/** One string of a triple in `language`, with `{name}` placeholders filled (unknown placeholders stay as they are). */
export function pick(text: Tri, language: GenUiLanguage, vars?: Readonly<Record<string, string | number>>): string {
  const template = text[INDEX[language] ?? 0] || text[0];
  if (!vars) return template;
  return template.replace(/\{([a-zA-Z]+)\}/g, (whole, name: string) => (Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : whole));
}

const chip = (label: Tri, instruction: Tri): ChipText => ({ label, instruction });

// --- R5: the person's live selection -------------------------------------------------------------------------------------
/** Selection chips by `@selection` item type. `binding` must be in the view's manifest; `min`/`max` bound the count. */
export interface SelectionChip {
  type: string;
  kind: 'compare' | 'details';
  binding: string;
  min: number;
  max: number;
  /** A component that already shows this comparison: the chip is not offered when the view has it (no no-op chips). */
  unlessComponent?: string;
  text: ChipText;
}

const COMPARE_LABEL: Tri = ['Compare the {n} selected', '比較已選的 {n} 項', '比较已选的 {n} 项'];
const DETAILS_LABEL: Tri = ['Details of the selection', '已選項目的詳情', '已选项目的详情'];

export const SELECTION_CHIPS: readonly SelectionChip[] = [
  { type: 'draft', kind: 'compare', binding: 'drafts_list', min: 2, max: 4,
    text: chip(COMPARE_LABEL, ['Compare only the {n} selected drafts', '只比較已選的 {n} 份草稿', '只比较已选的 {n} 份草稿']) },
  { type: 'web_page', kind: 'compare', binding: 'research_results', min: 2, max: 8, unlessComponent: 'ComparisonMatrix',
    text: chip(COMPARE_LABEL, ['Compare the {n} selected pages side by side', '並排比較已選的 {n} 個網頁', '并排比较已选的 {n} 个网页']) },
  { type: 'draft', kind: 'details', binding: 'draft_read', min: 1, max: 1,
    text: chip(DETAILS_LABEL, ['Show the details of the selected draft', '顯示已選草稿的詳情', '显示已选草稿的详情']) },
  { type: 'automation', kind: 'details', binding: 'automation_detail', min: 1, max: 1,
    text: chip(DETAILS_LABEL, ['Show the details of the selected automation', '顯示已選自動化的詳情', '显示已选自动化的详情']) },
  { type: 'campaign', kind: 'details', binding: 'campaign_detail', min: 1, max: 1,
    text: chip(DETAILS_LABEL, ['Show the details of the selected campaign', '顯示已選推廣活動的詳情', '显示已选推广活动的详情']) },
  { type: 'media', kind: 'details', binding: 'library_item', min: 1, max: 1,
    text: chip(DETAILS_LABEL, ['Show the details of the selected file', '顯示已選檔案的詳情', '显示已选文件的详情']) },
  { type: 'library_file', kind: 'details', binding: 'library_item', min: 1, max: 1,
    text: chip(DETAILS_LABEL, ['Show the details of the selected file', '顯示已選檔案的詳情', '显示已选文件的详情']) },
];

// --- R1/R2: filter alternatives on a Query argument ------------------------------------------------------------------------
/**
 * Values in the order they are offered (most useful first). `whenAbsent` is the value the binding uses when the argument is
 * missing, so it is never offered as a change; `null` means "everything" without an enum value for it.
 */
export interface FilterChips {
  binding: string;
  arg: string;
  whenAbsent: string | boolean | null;
  values: readonly { value: string | boolean; text: ChipText }[];
}

export const FILTER_CHIPS: readonly FilterChips[] = [
  { binding: 'drafts_list', arg: 'status', whenAbsent: 'all', values: [
    { value: 'needs_review', text: chip(['Needs review', '需要審閱', '需要审阅'], ['Show only drafts that need review', '只顯示需要審閱的草稿', '只显示需要审阅的草稿']) },
    { value: 'scheduled', text: chip(['Scheduled', '已排程', '已排程'], ['Show only scheduled drafts', '只顯示已排程的草稿', '只显示已排程的草稿']) },
    { value: 'unscheduled', text: chip(['Not scheduled', '未排程', '未排程'], ['Show only drafts that aren’t scheduled', '只顯示未排程的草稿', '只显示未排程的草稿']) },
    { value: 'all', text: chip(['All drafts', '所有草稿', '所有草稿'], ['Show all drafts', '顯示所有草稿', '显示所有草稿']) },
  ] },
  { binding: 'library_search', arg: 'kind', whenAbsent: 'all', values: [
    { value: 'video', text: chip(['Only videos', '只看影片', '只看视频'], ['Show only videos', '只顯示影片', '只显示视频']) },
    { value: 'document', text: chip(['Only documents', '只看文件', '只看文档'], ['Show only documents', '只顯示文件', '只显示文档']) },
    { value: 'image', text: chip(['Only photos', '只看相片', '只看照片'], ['Show only photos', '只顯示相片', '只显示照片']) },
    { value: 'audio', text: chip(['Only audio', '只看音訊', '只看音频'], ['Show only audio', '只顯示音訊', '只显示音频']) },
    { value: 'all', text: chip(['All files', '所有檔案', '所有文件'], ['Show all files', '顯示所有檔案', '显示所有文件']) },
  ] },
  { binding: 'automations_list', arg: 'status', whenAbsent: null, values: [
    { value: 'paused', text: chip(['Only paused', '只看已暫停', '只看已暂停'], ['Show only paused automations', '只顯示已暫停的自動化', '只显示已暂停的自动化']) },
    { value: 'active', text: chip(['Only active', '只看運行中', '只看运行中'], ['Show only active automations', '只顯示運行中的自動化', '只显示运行中的自动化']) },
    { value: 'draft', text: chip(['Only drafts', '只看草稿', '只看草稿'], ['Show only draft automations', '只顯示草稿自動化', '只显示草稿自动化']) },
  ] },
  { binding: 'campaigns_list', arg: 'status', whenAbsent: null, values: [
    { value: 'needs_input', text: chip(['Needs details', '需要補充資料', '需要补充信息'], ['Show only campaigns that need details', '只顯示需要補充資料的推廣活動', '只显示需要补充信息的推广活动']) },
    { value: 'active', text: chip(['Active', '進行中', '进行中'], ['Show only active campaigns', '只顯示進行中的推廣活動', '只显示进行中的推广活动']) },
    { value: 'completed', text: chip(['Completed', '已完成', '已完成'], ['Show only completed campaigns', '只顯示已完成的推廣活動', '只显示已完成的推广活动']) },
  ] },
  { binding: 'campaign_items', arg: 'kind', whenAbsent: null, values: [
    { value: 'post', text: chip(['Only posts', '只看帖文', '只看帖子'], ['Show only this campaign’s posts', '只顯示這個推廣活動的帖文', '只显示这个推广活动的帖子']) },
    { value: 'draft', text: chip(['Only drafts', '只看草稿', '只看草稿'], ['Show only this campaign’s drafts', '只顯示這個推廣活動的草稿', '只显示这个推广活动的草稿']) },
  ] },
  { binding: 'voice_sources', arg: 'activeOnly', whenAbsent: false, values: [
    { value: true, text: chip(['Only active samples', '只看使用中的樣本', '只看使用中的样本'], ['Show only the writing samples in use', '只顯示使用中的寫作樣本', '只显示使用中的写作样本']) },
  ] },
  { binding: 'founder_attention', arg: 'severity', whenAbsent: null, values: [
    { value: 'critical', text: chip(['Only critical', '只看嚴重', '只看严重'], ['Show only critical items', '只顯示嚴重項目', '只显示严重项目']) },
  ] },
  { binding: 'founder_costs', arg: 'dimension', whenAbsent: null, values: [
    { value: 'model', text: chip(['By model', '按模型', '按模型'], ['Break AI cost down by model', '按模型細分 AI 成本', '按模型细分 AI 成本']) },
    { value: 'feature', text: chip(['By feature', '按功能', '按功能'], ['Break AI cost down by feature', '按功能細分 AI 成本', '按功能细分 AI 成本']) },
    { value: 'plan', text: chip(['By plan', '按方案', '按方案'], ['Break AI cost down by plan', '按方案細分 AI 成本', '按方案细分 AI 成本']) },
  ] },
];

// --- R3: the period ------------------------------------------------------------------------------------------------------
/** Bindings whose `start`/`end` look back (performance) or ahead (calendar). Others never get date chips. */
export const PAST_DATE_BINDINGS: readonly string[] = ['analytics_posts', 'analytics_compare', 'analytics_series'];
export const FUTURE_DATE_BINDINGS: readonly string[] = ['calendar_agenda', 'campaign_timeline'];

export type DatePeriod = 'next' | 'previous' | 'nextMonth' | 'last7' | 'last30';

export const DATE_PERIOD_CHIPS: Readonly<Record<DatePeriod | 'nextWeek' | 'previousWeek', ChipText>> = {
  nextWeek: chip(['Next week', '下一星期', '下一周'],
    ['Change the period to the following week ({start} to {end})', '把時段改為下一星期（{start} 至 {end}）', '把时段改为下一周（{start} 至 {end}）']),
  next: chip(['Next {n} days', '之後 {n} 日', '之后 {n} 天'],
    ['Change the period to the following {n} days ({start} to {end})', '把時段改為之後的 {n} 日（{start} 至 {end}）', '把时段改为之后的 {n} 天（{start} 至 {end}）']),
  previousWeek: chip(['Previous week', '上一星期', '上一周'],
    ['Change the period to the week before ({start} to {end})', '把時段改為上一星期（{start} 至 {end}）', '把时段改为上一周（{start} 至 {end}）']),
  previous: chip(['Previous {n} days', '之前 {n} 日', '之前 {n} 天'],
    ['Change the period to the {n} days before ({start} to {end})', '把時段改為之前的 {n} 日（{start} 至 {end}）', '把时段改为之前的 {n} 天（{start} 至 {end}）']),
  nextMonth: chip(['Next month', '下個月', '下个月'],
    ['Change the period to next month ({start} to {end})', '把時段改為下個月（{start} 至 {end}）', '把时段改为下个月（{start} 至 {end}）']),
  last7: chip(['Last 7 days', '最近 7 日', '最近 7 天'],
    ['Change the period to the last 7 days ({start} to {end})', '把時段改為最近 7 日（{start} 至 {end}）', '把时段改为最近 7 天（{start} 至 {end}）']),
  last30: chip(['Last 30 days', '最近 30 日', '最近 30 天'],
    ['Change the period to the last 30 days ({start} to {end})', '把時段改為最近 30 日（{start} 至 {end}）', '把时段改为最近 30 天（{start} 至 {end}）']),
};

/** Named periods (founder bindings take `period` as an enum the server resolves; no dates are written). */
export const ENUM_PERIOD_CHIPS: readonly { value: string; text: ChipText }[] = [
  { value: 'last_month', text: chip(['Last month', '上個月', '上个月'], ['Change the period to last month', '把時段改為上個月', '把时段改为上个月']) },
  { value: '7d', text: chip(['Last 7 days', '最近 7 日', '最近 7 天'], ['Change the period to the last 7 days', '把時段改為最近 7 日', '把时段改为最近 7 天']) },
  { value: '30d', text: chip(['Last 30 days', '最近 30 日', '最近 30 天'], ['Change the period to the last 30 days', '把時段改為最近 30 日', '把时段改为最近 30 天']) },
  { value: 'mtd', text: chip(['This month so far', '本月至今', '本月至今'], ['Change the period to this month so far', '把時段改為本月至今', '把时段改为本月至今']) },
];

// --- R4/R9: a binding of the manifest the view does not show yet -----------------------------------------------------------
/** Only bindings listed here get an "also show" chip; a manifest binding without a curated label never yields one. */
export interface AddChip {
  binding: string;
  /** The view must already carry this argument on some Query (for example the campaign the timeline belongs to). */
  needsArg?: string;
  rule: 'add' | 'shape';
  text: ChipText;
}

export const ADD_CHIPS: readonly AddChip[] = [
  { binding: 'voice_learning_status', rule: 'add',
    text: chip(['Learning status', '學習狀態', '学习状态'], ['Also show what learning is doing now', '同時顯示學習現在的進度', '同时显示学习现在的进度']) },
  { binding: 'campaign_timeline', needsArg: 'campaignId', rule: 'add',
    text: chip(['Campaign timeline', '推廣活動時間線', '推广活动时间线'], ['Add the campaign timeline', '加入推廣活動的時間線', '加入推广活动的时间线']) },
  { binding: 'connections_status', rule: 'add',
    text: chip(['Accounts to reconnect', '需要重新連結的帳戶', '需要重新连接的账户'], ['Also show which accounts need reconnecting', '同時顯示哪些帳戶需要重新連結', '同时显示哪些账户需要重新连接']) },
  { binding: 'analytics_series', rule: 'shape',
    text: chip(['Chart of views by week', '按星期的瀏覽量圖表', '按周的浏览量图表'], ['Add a chart of views by week', '加入按星期顯示瀏覽量的圖表', '加入按周显示浏览量的图表']) },
  { binding: 'queue_status', rule: 'add',
    text: chip(['Publishing queue', '發佈佇列', '发布队列'], ['Also show the publishing queue', '同時顯示發佈佇列', '同时显示发布队列']) },
  { binding: 'open_proposals', rule: 'add',
    text: chip(['Waiting for you', '等待你處理', '等待你处理'], ['Also show the proposals waiting for me', '同時顯示等待我處理的提議', '同时显示等待我处理的提议']) },
  { binding: 'research_sources', rule: 'add',
    text: chip(['Saved web sources', '已儲存的網上來源', '已保存的网络来源'], ['Also show my saved web sources', '同時顯示我已儲存的網上來源', '同时显示我已保存的网络来源']) },
  { binding: 'voice_consent', rule: 'add',
    text: chip(['What you’ve allowed', '你已允許的事項', '你已允许的事项'], ['Also show what I’ve allowed', '同時顯示我已允許的事項', '同时显示我已允许的事项']) },
];

// --- R6/R7: chart kind, metric and columns ---------------------------------------------------------------------------------
export const METRIC_NAMES: Readonly<Record<string, Tri>> = {
  views: ['views', '瀏覽量', '浏览量'],
  reach: ['reach', '觸及人數', '触达人数'],
  likes: ['likes', '讚好', '点赞'],
  comments: ['comments', '留言', '评论'],
  replies: ['replies', '回覆', '回复'],
  reposts: ['reposts', '轉發', '转发'],
  quotes: ['quotes', '引用', '引用'],
  shares: ['shares', '分享', '分享'],
  saved: ['saves', '收藏', '收藏'],
};

/** Offered in this order, never the metric already shown. */
export const METRIC_SWAP_ORDER: readonly string[] = ['likes', 'reach', 'comments', 'shares', 'views'];
export const METRIC_COLUMN_ORDER: readonly string[] = ['reach', 'likes', 'comments', 'shares', 'saved', 'views'];
export const METRIC_TABLE_MAX_COLUMNS = 6;

export const SHAPE_CHIPS = {
  bar: chip(['Show as bars', '改用棒形圖', '改用柱状图'], ['Show the chart as bars', '把圖表改為棒形圖', '把图表改为柱状图']),
  line: chip(['Show as a line', '改用折線圖', '改用折线图'], ['Show the chart as a line', '把圖表改為折線圖', '把图表改为折线图']),
  swapMetric: chip(['Compare {metric}', '比較{metric}', '比较{metric}'], ['Compare {metric} instead of {current}', '改為比較{metric}，而不是{current}', '改为比较{metric}，而不是{current}']),
  addColumn: chip(['Add a {metric} column', '加入{metric}欄', '加入{metric}列'], ['Add a {metric} column to the table', '在表格加入{metric}欄', '在表格中加入{metric}列']),
  compareCost: chip(['Compare with before', '與之前比較', '与之前比较'], ['Compare cost with the previous period', '把成本與上一個時段比較', '把成本与上一个时段比较']),
} as const;

/** Charts whose second positional argument is `kind` (line | bar; MetricChart defaults to line). */
export const CHART_COMPONENTS: Readonly<Record<string, 'line' | null>> = { MetricChart: 'line', ToolBoundChart: null };

// --- R8: remove a section ------------------------------------------------------------------------------------------------
/** Only these sections can be offered for removal, and only when the view has at least 3 (never CoverageNote: metric views keep it). */
export const REMOVE_CHIPS: Readonly<Record<string, ChipText>> = {
  Commentary: chip(['Remove the note', '移除備註', '移除备注'], ['Remove the note', '移除這段備註', '移除这段备注']),
  QueueStatus: chip(['Remove the queue', '移除發佈佇列', '移除发布队列'], ['Remove the publishing queue', '移除發佈佇列', '移除发布队列']),
  TaskProgress: chip(['Remove the progress', '移除進度', '移除进度'], ['Remove the task progress', '移除任務進度', '移除任务进度']),
  RunHistory: chip(['Remove the run history', '移除執行記錄', '移除执行记录'], ['Remove the run history', '移除執行記錄', '移除执行记录']),
};
export const REMOVE_MIN_SECTIONS = 3;

// --- R9: the tested edit of each journey ---------------------------------------------------------------------------------
/**
 * Each journey's tested edit case (generated/journey-examples/journeys.json `editCase`), as the chip it maps to. When that
 * chip qualifies for the view it is shown right after the selection chip. J04 evidence column, J05 progress chart and J07
 * sort by date have no chip: they cannot be derived from the manifest and stay out until a live check passes.
 */
export const JOURNEY_SEEDS: Readonly<Record<string, string>> = {
  J01: 'selection:draft:compare',
  J02: 'period:next',
  J03: 'filter:library_search.kind:document',
  J04: 'add:voice_learning_status',
  J05: 'add:campaign_timeline',
  J06: 'shape:analytics_series',
  J07: 'selection:web_page:compare',
  J08: 'add:connections_status',
  J09: 'filter:founder_costs.dimension:model',
};

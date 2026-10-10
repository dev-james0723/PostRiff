import { z } from 'zod';

export const verificationKeys = ['implemented', 'runtime_bound', 'app_reviewed',
  'verified_scope_or_feature', 'live_read_verified', 'stored_and_processed',
  'production_ui_verified'] as const;
const verificationState = z.enum(['VERIFIED', 'UNVERIFIED', 'BLOCKED']);
export const publicSourceVerificationSchema = z.object({
  implemented: verificationState, runtime_bound: verificationState, app_reviewed: verificationState,
  verified_scope_or_feature: verificationState, live_read_verified: verificationState,
  stored_and_processed: verificationState, production_ui_verified: verificationState
}).strict();
export const publicSourceSchema = z.object({
  provider: z.enum(['instagram', 'threads', 'facebook']),
  operation: z.enum(['hashtag_discovery', 'keyword_search', 'page_public_posts']),
  label: z.string(),
  status: z.enum(['APP_REVIEW_REQUIRED', 'AUTHORIZATION_REQUIRED', 'UNVERIFIED', 'LIVE', 'STALE', 'PAUSED', 'REVOKED']),
  authorization_id: z.string().uuid().nullable(),
  latest_successful_read: z.string().datetime().nullable(),
  expires_at: z.string().datetime().nullable(),
  dispatch_enabled: z.boolean(),
  verification: publicSourceVerificationSchema,
  coverage: z.string(),
  semantic_evaluation: z.string()
}).strict();
export type PublicSource = z.infer<typeof publicSourceSchema>;
/** Cached evidence cannot keep a grant or dependent claim current after its deadline. */
export function publicSourcePresentation(source: PublicSource, expired: boolean, stale = false): PublicSource {
  if (!expired && !stale) return source;
  const verification = { ...source.verification };
  for (const key of ['verified_scope_or_feature', 'live_read_verified', 'stored_and_processed', 'production_ui_verified'] as const)
    if ((expired || key !== 'verified_scope_or_feature') && verification[key] === 'VERIFIED') verification[key] = 'UNVERIFIED';
  return { ...source, status: source.status === 'LIVE' ? (expired ? 'AUTHORIZATION_REQUIRED' : 'STALE') : source.status, verification };
}
const english = {
  title: 'Public discovery sources',
  caveat: 'Public discovery needs its own Meta approval and permission verification. Connecting your account for publishing or analytics does not grant public discovery access.',
  gates: {
    implemented: 'Adapter implemented', runtime_bound: 'Runtime connected', app_reviewed: 'Meta app approval',
    verified_scope_or_feature: 'Permission or feature verified', live_read_verified: 'Live public read verified',
    stored_and_processed: 'Stored and processed', production_ui_verified: 'Production interface verified'
  },
  states: { VERIFIED: 'Verified', UNVERIFIED: 'Not verified', BLOCKED: 'Blocked' },
  statuses: {
    APP_REVIEW_REQUIRED: 'Public access approval required', AUTHORIZATION_REQUIRED: 'Reconnect or verify public access',
    UNVERIFIED: 'Awaiting a verified public reading', LIVE: 'Live within this source scope',
    STALE: 'Last reading is out of date', PAUSED: 'Collection paused', REVOKED: 'Public access revoked'
  },
  providers: { instagram: 'Instagram hashtags', threads: 'Threads keywords', facebook: 'Facebook public Pages' },
  coverage: { instagram: 'Selected hashtags only. This sample does not cover all public Instagram posts.',
    threads: 'Selected keywords and search order only. This sample does not cover all public Threads posts.',
    facebook: 'Reviewed public Pages only. This sample does not cover personal profiles, Groups or all public Facebook posts.' },
  lastRead: 'Last verified reading', noRead: 'No verified third-party public reading.',
  revoke: 'Revoke public access', cancel: 'Cancel',
  revokeConfirm: 'Stop public collection and withdraw results derived from this grant?',
  revokeError: 'Access could not be revoked. A workspace member with connection management permission can try again.',
  jev: 'Trend measurements use the available observations. Optional JEV interpretation requires current source rights, workspace consent and an approved model budget.',
  loading: 'Loading public source evidence…', loadError: 'Public source evidence could not load.',
  unavailable: 'Public source evidence is unavailable.', partial: 'Some public source coverage is missing.',
  collecting: 'Collecting public source evidence.', retry: 'Try again',
  requestTitle: 'Request a public sample', hashtag: 'Instagram hashtag', query: 'Threads keyword query',
  searchOrder: 'Threads search order', top: 'Top results', recent: 'Recent results',
  page: 'Reviewed Facebook Page', choosePage: 'Choose a reviewed Page', queue: 'Queue discovery request',
  queueBusy: 'Submitting request…', requestDisabled: 'A current public access grant and collection permission are required.',
  requestError: 'The request could not be queued. Check your public access and workspace permission, then try again.',
  requestUnavailable: 'Discovery requests are unavailable.', requestLoading: 'Loading discovery request permissions…',
  receipts: 'Discovery request receipts', queued: 'Request queued. No live reading has been verified by this request.',
  receiptStatuses: { queued: 'Queued', running: 'Collecting', completed: 'Completed', failed: 'Failed', unavailable: 'Unavailable' },
  sample: 'Sample size', range: 'Source time range', retrieved: 'Retrieval time', created: 'Requested at',
  completeness: 'Completeness', completenessStates: { partial: 'Partial', gap: 'Gap', unknown: 'Unknown' },
  unknown: 'Unknown', selection: 'Selection'
};
type Copy = typeof english;
const traditionalChinese: Copy = {
  title: '公開內容探索來源',
  caveat: '探索公開內容需要獨立的 Meta 審批及權限核實。連接帳戶作發佈或數據分析，並不代表已獲准探索公開內容。',
  gates: {
    implemented: '已實作來源讀取', runtime_bound: '已連接執行流程', app_reviewed: 'Meta 應用程式審批',
    verified_scope_or_feature: '已核實權限或功能', live_read_verified: '已核實即時公開讀取',
    stored_and_processed: '已儲存及處理', production_ui_verified: '已核實正式介面'
  },
  states: { VERIFIED: '已核實', UNVERIFIED: '未核實', BLOCKED: '受阻' },
  statuses: { APP_REVIEW_REQUIRED: '需要公開內容存取審批', AUTHORIZATION_REQUIRED: '請重新連接或核實公開內容存取權',
    UNVERIFIED: '等待已核實的公開內容讀取', LIVE: '此來源範圍內的即時資料',
    STALE: '上次讀取資料已過時', PAUSED: '收集已暫停', REVOKED: '公開內容存取權已撤銷' },
  providers: { instagram: 'Instagram 主題標籤', threads: 'Threads 關鍵字', facebook: 'Facebook 公開專頁' },
  coverage: { instagram: '只涵蓋所選主題標籤。此樣本並不涵蓋所有 Instagram 公開貼文。',
    threads: '只涵蓋所選關鍵字及搜尋排序。此樣本並不涵蓋所有 Threads 公開貼文。',
    facebook: '只涵蓋已審批的公開專頁。此樣本並不涵蓋個人檔案、群組或所有 Facebook 公開貼文。' },
  lastRead: '上次已核實讀取', noRead: '尚未有已核實的第三方公開內容讀取。',
  revoke: '撤銷公開內容存取權', cancel: '取消',
  revokeConfirm: '停止收集公開內容，並撤回根據此授權產生的結果？',
  revokeError: '未能撤銷存取權。具備連接管理權限的工作區成員可以再試一次。',
  jev: '趨勢量度以現有觀察資料為依據。選用 JEV 解讀需要有效的來源權利、工作區同意及已批准的模型預算。',
  loading: '正在載入公開來源證據…', loadError: '未能載入公開來源證據。',
  unavailable: '公開來源證據暫時無法使用。', partial: '部分公開來源覆蓋資料缺漏。',
  collecting: '正在收集公開來源證據。', retry: '再試一次',
  requestTitle: '要求公開內容樣本', hashtag: 'Instagram 主題標籤', query: 'Threads 關鍵字查詢',
  searchOrder: 'Threads 搜尋排序', top: '熱門結果', recent: '最新結果',
  page: '已審批的 Facebook 專頁', choosePage: '選擇已審批專頁', queue: '將探索要求加入佇列',
  queueBusy: '正在提交要求…', requestDisabled: '需要有效的公開內容授權及收集權限。',
  requestError: '未能將要求加入佇列。請檢查公開內容存取權及工作區權限，然後再試。',
  requestUnavailable: '探索要求暫時無法使用。', requestLoading: '正在載入探索要求權限…',
  receipts: '探索要求紀錄', queued: '要求已加入佇列。此要求尚未核實任何即時讀取。',
  receiptStatuses: { queued: '已加入佇列', running: '正在收集', completed: '已完成', failed: '失敗', unavailable: '無法使用' },
  sample: '樣本數量', range: '來源時間範圍', retrieved: '讀取時間', created: '要求時間',
  completeness: '完整程度', completenessStates: { partial: '部分', gap: '有缺漏', unknown: '未知' },
  unknown: '未知', selection: '選取範圍'
};
export function publicSourceCopy(locale: string): Copy {
  return /^(zh|yue)(-|$)/i.test(locale.replaceAll('_', '-')) ? traditionalChinese : english;
}

/**
 * Words and rules for the Business results panel (G2-OUT, PRD R-OUT-01..03). Pure (no imports) so node's test runner
 * loads it directly (`web/tests/results.test.mjs`).
 *
 * Honesty rules: the three sources keep their own plain labels and are never added together; money is shown per
 * currency, never converted or summed; a source with no data says so instead of showing 0; clicks are clicks, not people.
 * Language follows the person's saved language (English or Traditional Chinese).
 */

export type Lang = 'en' | 'zh-Hant';
type Provenance = 'provider_native' | 'first_party_reported' | 'user_declared';
type Kind = 'click' | 'lead' | 'booking' | 'newsletter_signup' | 'sale';
type Attribution = 'associated' | 'unattributed' | 'expired_window' | 'not_this_workspace';
type Producer = 'form' | 'booking' | 'newsletter' | 'store' | 'other';
type State = 'available' | 'partial' | 'unavailable' | 'stale';

interface ClassSummary {
  counts: Partial<Record<Kind, number>>;
  money: Record<string, { minor: number; events: number }>;
  reversed: number;
  unattributed: number;
  associated: number;
}

/** Traditional Chinese for zh-Hant/TW/HK/MO and Cantonese; English otherwise (no Simplified copy exists yet). */
export function pickLanguage(locale: string | null | undefined): Lang {
  const tag = (locale ?? '').toLowerCase();
  return /^(zh-hant|zh-tw|zh-hk|zh-mo|yue)/.test(tag) ? 'zh-Hant' : 'en';
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

const EN_KINDS: Record<Kind, [string, string]> = {
  lead: ['lead', 'leads'],
  booking: ['booking', 'bookings'],
  newsletter_signup: ['newsletter sign-up', 'newsletter sign-ups'],
  sale: ['sale', 'sales'],
  click: ['click', 'clicks']
};
const ZH_KINDS: Record<Kind, [string, string]> = {
  lead: ['潛在客戶', '潛在客戶'],
  booking: ['預約', '預約'],
  newsletter_signup: ['電子報訂閱', '電子報訂閱'],
  sale: ['銷售', '銷售'],
  click: ['點擊', '點擊']
};

const en = {
  title: 'Business results',
  description: 'Leads, bookings, sign-ups and sales from what you record and the tools you connect. Each source stays separate, and nothing here claims Rafii caused a result.',
  periodLabel: 'Results period',
  periods: { d30: '30 days', d90: '90 days', all: 'All time' },
  classes: { user_declared: 'You reported', first_party_reported: 'Reported by your connected tools', provider_native: 'Platform-reported' } as Record<Provenance, string>,
  classHints: {
    user_declared: 'Results you recorded yourself. Not independently verified.',
    first_party_reported: 'Sent by a form, booking page or store you connected. A signed delivery shows where it came from, not that the result happened.',
    provider_native: 'Platform numbers aren’t connected to business results yet.'
  } as Record<Provenance, string>,
  noResults: 'No results in this period',
  notConnected: 'Not connected',
  kinds: EN_KINDS,
  kindNames: { lead: 'Lead', booking: 'Booking', newsletter_signup: 'Newsletter sign-up', sale: 'Sale', click: 'Click' } as Record<Kind, string>,
  count: (n: number, kind: Kind): string => plural(n, EN_KINDS[kind][0], EN_KINDS[kind][1]),
  allWithdrawn: 'Everything in this period was reversed',
  reversed: (n: number) => `${n} reversed`,
  associated: (n: number) => `${n} came through your tracking links`,
  unattributed: (n: number) => `${n} not linked to a tracking link`,
  moneyNote: 'Amounts are shown per currency and never added together.',
  states: {
    available: 'Up to date',
    open: 'Still collecting: results for this period can still arrive.',
    problem: 'A connection reported a problem, so some results may be missing.',
    paused: 'A connection is paused, so results from it aren’t arriving.',
    unavailable: 'No result sources yet. Record a result or connect a tool to start.',
    stale: 'No recent reports'
  },
  stateChip: { available: 'Up to date', partial: 'Still collecting', unavailable: 'No sources yet', stale: 'No recent reports' } as Record<State, string>,
  clicks: (n: number) => `${plural(n, 'click', 'clicks')} on your tracking links`,
  bots: (n: number) => `${plural(n, 'likely bot visit', 'likely bot visits')} counted separately where detectable`,
  clicksNotPeople: 'Clicks are counted per click, not per person.',
  testEvents: (n: number) => `${plural(n, 'test event', 'test events')} in this period ${n === 1 ? 'is' : 'are'} listed but never counted.`,
  quarantined: (n: number) => `${plural(n, 'conflicting delivery was', 'conflicting deliveries were')} held back and not applied.`,
  tabsLabel: 'Business results views',
  tabs: { ledger: 'Results', connections: 'Connections', links: 'Tracking links' },
  ledger: {
    record: 'Record a result',
    source: 'Source',
    type: 'Type',
    link: 'Tracking link',
    status: 'Status',
    all: 'All',
    associated: 'Through a tracking link',
    notAssociated: 'Not linked',
    active: 'Current',
    reversed: 'Reversed',
    empty: 'No results yet',
    emptyFiltered: 'No results match these filters',
    emptyDescription: 'Record a lead, booking, sign-up or sale, or connect a form or booking tool.',
    loading: 'Loading results…',
    error: 'Results couldn’t load',
    viewOnly: 'Your role can view results but not change them.'
  },
  item: {
    occurred: 'Happened',
    received: 'Received',
    lag: (t: string) => `arrived ${t} later`,
    test: 'Test',
    edited: 'Edited',
    reversed: 'Reversed',
    edit: 'Edit',
    reverse: 'Reverse',
    campaign: 'Campaign',
    via: (label: string) => `Via ${label}`,
    quantity: (n: number) => `× ${n}`,
    note: 'Note'
  },
  attribution: {
    associated: 'Through your tracking link',
    unattributed: 'Not linked',
    expired_window: 'Link click was too long before',
    not_this_workspace: 'Another workspace’s link'
  } as Record<Attribution, string>,
  form: {
    title: 'Record a result',
    amendTitle: 'Edit result',
    intro: 'Saved as “You reported”. Record only what happened; Rafii won’t guess amounts or dates.',
    type: 'What happened',
    occurredAt: 'When',
    amount: 'Amount (optional)',
    currency: 'Currency',
    quantity: 'How many',
    note: 'Note (optional)',
    noteHint: 'Up to 500 characters. Leave out other people’s contact details.',
    link: 'Tracking link (optional)',
    noLink: 'No link',
    campaign: 'Campaign label (optional)',
    save: 'Save result',
    saveEdit: 'Save changes',
    saving: 'Saving…',
    cancel: 'Cancel',
    amountOnlyFor: 'Only bookings and sales carry an amount.',
    amountInvalid: 'Enter an amount like 45 or 45.50.',
    currencyInvalid: 'Use a three-letter currency code such as USD or TWD.',
    dateInvalid: 'Choose when it happened.',
    quantityInvalid: 'Enter a number from 1 to 1,000.',
    campaignInvalid: 'Use letters, numbers, - _ or : (up to 80).'
  },
  reverse: {
    title: 'Reverse this result?',
    intro: 'It stays in your history marked reversed and stops counting in every total. Record it again if this was a mistake.',
    reason: 'Why (optional)',
    confirm: 'Reverse result',
    working: 'Reversing…'
  },
  connections: {
    create: 'Connect a tool',
    createTitle: 'Connect a form or booking tool',
    createIntro: 'Your tool sends each result to Rafii, signed with a secret only you and the tool know.',
    name: 'Name',
    namePlaceholder: 'Website booking form',
    producer: 'What sends the results',
    producers: { form: 'Form', booking: 'Booking page', newsletter: 'Newsletter', store: 'Store', other: 'Another tool you control' } as Record<Producer, string>,
    createButton: 'Create connection',
    creating: 'Creating…',
    ownerOnly: 'Only the workspace owner can connect tools.',
    empty: 'No tools connected',
    emptyDescription: 'Connect a form, booking page, newsletter or store you control. A test event shows the connection works; real results start when your tool sends them.',
    limit: (n: number) => `Up to ${n} connections.`,
    status: { active: 'Receiving', paused: 'Paused', removed: 'Removed' },
    fingerprint: (fp: string) => `Key ${fp}`,
    previousUntil: (fp: string, when: string) => `Previous key ${fp} works until ${when}`,
    lastEvent: (t: string) => `Last result ${t}`,
    never: 'No results received yet',
    lag: (t: string) => `arrived ${t} after it happened`,
    problem: (text: string) => `Last problem: ${text}`,
    counts: (accepted: number, reversals: number, tests: number) => `Last 24 hours: ${accepted} results · ${reversals} reversals · ${tests} tests`,
    held: (n: number) => `${n} held back`,
    rotate: 'Rotate secret',
    pause: 'Pause',
    resume: 'Resume',
    remove: 'Remove',
    rotateTitle: 'Rotate this secret?',
    rotateIntro: 'A new secret is shown once. The current one keeps working for 24 hours so you can update your tool.',
    removeTitle: 'Remove this connection?',
    removeIntro: 'It stops receiving results and its secret is deleted. Results already received stay in your history.',
    confirmRotate: 'Rotate secret',
    confirmRemove: 'Remove connection',
    working: 'Working…'
  },
  secret: {
    title: 'Copy your secret now',
    warning: 'This is the only time Rafii shows it. Store it in your tool’s secret settings. If you lose it, rotate to get a new one.',
    copy: 'Copy secret',
    copied: 'Secret copied',
    copyFailed: 'Couldn’t copy. Select the secret and copy it.',
    endpoint: 'Send results to',
    header: 'Signature header',
    format: 'Each delivery is signed with HMAC-SHA256 over its timestamp and exact body. Deliveries older than five minutes are refused.',
    done: 'I’ve stored it',
    replayed: 'This secret was already shown once. Rotate it to get a new one.',
    replayedTitle: 'Secret already shown'
  },
  links: {
    create: 'Create a tracking link',
    createTitle: 'Create a tracking link',
    createIntro: 'Share this link instead of the page address. Rafii counts clicks and adds a reference your tools can send back with a result.',
    destination: 'Page address',
    destinationHint: 'A public https:// page.',
    label: 'Name (optional)',
    campaign: 'Campaign label (optional)',
    campaignHint: 'Letters, numbers, - _ or :',
    createButton: 'Create link',
    creating: 'Creating…',
    created: 'Link ready',
    copy: 'Copy link',
    copied: 'Link copied',
    copyFailed: 'Couldn’t copy. Select the link and copy it.',
    empty: 'No tracking links yet',
    emptyDescription: 'Create one for a page you share, like a booking page.',
    clicks: (n: number) => plural(n, 'click', 'clicks'),
    bots: (n: number) => plural(n, 'likely bot visit', 'likely bot visits'),
    results: (n: number) => `${plural(n, 'result', 'results')} through this link`,
    off: 'Off',
    on: 'On',
    turnOff: 'Turn off',
    turnOn: 'Turn on',
    note: 'Clicks are counted per click, not per person. Likely bots are counted separately where detectable; some will still get through.',
    windowNote: (days: number) => `A result is linked when it carries this link’s reference and happens within ${days} days of the click.`
  },
  errors: {
    signature_mismatch: 'the signature didn’t match',
    signature_missing: 'an unsigned delivery',
    signature_malformed: 'a malformed signature',
    timestamp_outside_window: 'the sending clock was off by more than five minutes',
    rate_limited: 'too many deliveries at once',
    daily_budget_exhausted: 'the daily limit was reached',
    payload_invalid: 'an unreadable event',
    conflicting_payload: 'a duplicate with different content',
    reversal_duplicate: 'a second reversal of the same result',
    secret_unavailable: 'the secret needs rotating',
    result_reversal_unknown: 'a reversal arrived before its original',
    result_reversal_invalid: 'a reversal didn’t match its original'
  } as Record<string, string>,
  time: {
    justNow: 'just now',
    minutes: (n: number) => plural(n, 'minute', 'minutes'),
    hours: (n: number) => plural(n, 'hour', 'hours'),
    days: (n: number) => plural(n, 'day', 'days'),
    ago: (t: string) => `${t} ago`
  },
  loadMore: 'Show more',
  retry: 'Try again',
  unavailableTitle: 'Business results couldn’t load',
  unavailableDescription: 'Nothing is shown rather than a guess.'
};

export type ResultsCopy = typeof en;

const zh: ResultsCopy = {
  title: '業務成果',
  description: '來自你自行記錄和已連接工具的潛在客戶、預約、訂閱和銷售。每個來源分開顯示，這裡不會聲稱成果是 Rafii 帶來的。',
  periodLabel: '成果期間',
  periods: { d30: '30 天', d90: '90 天', all: '全部' },
  classes: { user_declared: '你自行記錄', first_party_reported: '由你連接的工具回報', provider_native: '平台回報' },
  classHints: {
    user_declared: '你自己記錄的成果，未經獨立核實。',
    first_party_reported: '由你連接的表單、預約頁或商店傳送。已簽署的傳送只證明來源，不證明成果確實發生。',
    provider_native: '平台數據尚未連接到業務成果。'
  },
  noResults: '這段期間沒有成果',
  notConnected: '未連接',
  kinds: ZH_KINDS,
  kindNames: { lead: '潛在客戶', booking: '預約', newsletter_signup: '電子報訂閱', sale: '銷售', click: '點擊' },
  count: (n: number, kind: Kind): string => `${ZH_KINDS[kind][0]} ${n}`,
  allWithdrawn: '這段期間的成果都已撤銷',
  reversed: (n: number) => `已撤銷 ${n} 項`,
  associated: (n: number) => `經由你的追蹤連結 ${n} 項`,
  unattributed: (n: number) => `未連結追蹤連結 ${n} 項`,
  moneyNote: '金額按幣別分開顯示，不會相加。',
  states: {
    available: '已是最新',
    open: '仍在收集中：這段期間的成果可能還會陸續送達。',
    problem: '有連接回報問題，部分成果可能缺漏。',
    paused: '有連接已暫停，來自它的成果目前不會送達。',
    unavailable: '尚未有成果來源。記錄一項成果或連接工具即可開始。',
    stale: '最近沒有回報'
  },
  stateChip: { available: '已是最新', partial: '仍在收集', unavailable: '尚無來源', stale: '最近沒有回報' },
  clicks: (n: number) => `追蹤連結共 ${n} 次點擊`,
  bots: (n: number) => `另有 ${n} 次疑似機器人造訪，能辨識時分開計算`,
  clicksNotPeople: '點擊按次數計算，不代表人數。',
  testEvents: (n: number) => `這段期間有 ${n} 個測試事件，會列出但不計入。`,
  quarantined: (n: number) => `有 ${n} 個內容衝突的傳送已被擱置，沒有套用。`,
  tabsLabel: '業務成果檢視',
  tabs: { ledger: '成果', connections: '連接', links: '追蹤連結' },
  ledger: {
    record: '記錄成果',
    source: '來源',
    type: '類型',
    link: '追蹤連結',
    status: '狀態',
    all: '全部',
    associated: '經由追蹤連結',
    notAssociated: '未連結',
    active: '有效',
    reversed: '已撤銷',
    empty: '尚未有成果',
    emptyFiltered: '沒有符合篩選條件的成果',
    emptyDescription: '記錄一項潛在客戶、預約、訂閱或銷售，或連接表單或預約工具。',
    loading: '正在載入成果…',
    error: '無法載入成果',
    viewOnly: '你的角色可以查看成果，但不能修改。'
  },
  item: {
    occurred: '發生於',
    received: '收到於',
    lag: (t: string) => `${t}後送達`,
    test: '測試',
    edited: '已修改',
    reversed: '已撤銷',
    edit: '修改',
    reverse: '撤銷',
    campaign: '活動',
    via: (label: string) => `經由 ${label}`,
    quantity: (n: number) => `× ${n}`,
    note: '備註'
  },
  attribution: {
    associated: '經由你的追蹤連結',
    unattributed: '未連結',
    expired_window: '連結點擊時間太久以前',
    not_this_workspace: '其他工作區的連結'
  },
  form: {
    title: '記錄成果',
    amendTitle: '修改成果',
    intro: '會標示為「你自行記錄」。只記錄實際發生的事，Rafii 不會推測金額或日期。',
    type: '發生了什麼',
    occurredAt: '時間',
    amount: '金額（選填）',
    currency: '幣別',
    quantity: '數量',
    note: '備註（選填）',
    noteHint: '最多 500 字。請不要填寫他人的聯絡資料。',
    link: '追蹤連結（選填）',
    noLink: '不連結',
    campaign: '活動標籤（選填）',
    save: '儲存成果',
    saveEdit: '儲存修改',
    saving: '正在儲存…',
    cancel: '取消',
    amountOnlyFor: '只有預約和銷售可以填寫金額。',
    amountInvalid: '請輸入金額，例如 45 或 45.50。',
    currencyInvalid: '請使用三個字母的幣別代碼，例如 USD 或 TWD。',
    dateInvalid: '請選擇發生時間。',
    quantityInvalid: '請輸入 1 至 1,000 的數字。',
    campaignInvalid: '請使用英文字母、數字、- _ 或 :（最多 80 個）。'
  },
  reverse: {
    title: '要撤銷這項成果嗎？',
    intro: '它會以「已撤銷」保留在紀錄中，並且不再計入任何統計。如果是誤操作，請重新記錄。',
    reason: '原因（選填）',
    confirm: '撤銷成果',
    working: '正在撤銷…'
  },
  connections: {
    create: '連接工具',
    createTitle: '連接表單或預約工具',
    createIntro: '你的工具會把每項成果傳送到 Rafii，並以只有你和該工具知道的密鑰簽署。',
    name: '名稱',
    namePlaceholder: '網站預約表單',
    producer: '傳送成果的工具',
    producers: { form: '表單', booking: '預約頁', newsletter: '電子報', store: '商店', other: '你控制的其他工具' },
    createButton: '建立連接',
    creating: '正在建立…',
    ownerOnly: '只有工作區擁有者可以連接工具。',
    empty: '尚未連接工具',
    emptyDescription: '連接你控制的表單、預約頁、電子報或商店。測試事件可以確認連接正常；真正的成果要等你的工具開始傳送。',
    limit: (n: number) => `最多 ${n} 個連接。`,
    status: { active: '接收中', paused: '已暫停', removed: '已移除' },
    fingerprint: (fp: string) => `密鑰 ${fp}`,
    previousUntil: (fp: string, when: string) => `舊密鑰 ${fp} 可用至 ${when}`,
    lastEvent: (t: string) => `最後一項成果：${t}`,
    never: '尚未收到成果',
    lag: (t: string) => `發生後 ${t}送達`,
    problem: (text: string) => `最近的問題：${text}`,
    counts: (accepted: number, reversals: number, tests: number) => `過去 24 小時：成果 ${accepted} 項 · 撤銷 ${reversals} 項 · 測試 ${tests} 項`,
    held: (n: number) => `已擱置 ${n} 項`,
    rotate: '輪換密鑰',
    pause: '暫停',
    resume: '恢復',
    remove: '移除',
    rotateTitle: '要輪換這個密鑰嗎？',
    rotateIntro: '新密鑰只會顯示一次。目前的密鑰會繼續有效 24 小時，方便你更新工具。',
    removeTitle: '要移除這個連接嗎？',
    removeIntro: '它會停止接收成果，密鑰也會被刪除。已收到的成果會保留在紀錄中。',
    confirmRotate: '輪換密鑰',
    confirmRemove: '移除連接',
    working: '處理中…'
  },
  secret: {
    title: '現在就複製密鑰',
    warning: 'Rafii 只會顯示這一次。請把它存入工具的密鑰設定。如果遺失，可以輪換取得新的密鑰。',
    copy: '複製密鑰',
    copied: '已複製密鑰',
    copyFailed: '無法複製，請選取密鑰後自行複製。',
    endpoint: '成果傳送至',
    header: '簽署標頭',
    format: '每次傳送都以 HMAC-SHA256 簽署時間戳記與完整內容。超過五分鐘的傳送會被拒絕。',
    done: '我已妥善保存',
    replayed: '這個密鑰之前已顯示過一次。請輪換以取得新的密鑰。',
    replayedTitle: '密鑰已顯示過'
  },
  links: {
    create: '建立追蹤連結',
    createTitle: '建立追蹤連結',
    createIntro: '分享這個連結來代替原網址。Rafii 會計算點擊，並加上一個參考碼，讓你的工具在回報成果時一併傳回。',
    destination: '網頁網址',
    destinationHint: '公開的 https:// 網頁。',
    label: '名稱（選填）',
    campaign: '活動標籤（選填）',
    campaignHint: '英文字母、數字、- _ 或 :',
    createButton: '建立連結',
    creating: '正在建立…',
    created: '連結已就緒',
    copy: '複製連結',
    copied: '已複製連結',
    copyFailed: '無法複製，請選取連結後自行複製。',
    empty: '尚未有追蹤連結',
    emptyDescription: '為你常分享的網頁建立一個，例如預約頁。',
    clicks: (n: number) => `${n} 次點擊`,
    bots: (n: number) => `${n} 次疑似機器人造訪`,
    results: (n: number) => `經由此連結的成果 ${n} 項`,
    off: '已關閉',
    on: '開啟中',
    turnOff: '關閉',
    turnOn: '開啟',
    note: '點擊按次數計算，不代表人數。能辨識時，疑似機器人會分開計算，但仍可能有漏網之魚。',
    windowNote: (days: number) => `成果帶有此連結的參考碼，並在點擊後 ${days} 天內發生，才會連結到這個連結。`
  },
  errors: {
    signature_mismatch: '簽署不相符',
    signature_missing: '傳送沒有簽署',
    signature_malformed: '簽署格式錯誤',
    timestamp_outside_window: '傳送端時鐘誤差超過五分鐘',
    rate_limited: '短時間內傳送太多',
    daily_budget_exhausted: '已達每日上限',
    payload_invalid: '無法讀取的事件',
    conflicting_payload: '內容不同的重複事件',
    reversal_duplicate: '同一項成果被撤銷第二次',
    secret_unavailable: '密鑰需要輪換',
    result_reversal_unknown: '撤銷比原始事件先送達',
    result_reversal_invalid: '撤銷與原始事件不相符'
  },
  time: {
    justNow: '剛剛',
    minutes: (n: number) => `${n} 分鐘`,
    hours: (n: number) => `${n} 小時`,
    days: (n: number) => `${n} 天`,
    ago: (t: string) => `${t}前`
  },
  loadMore: '顯示更多',
  retry: '再試一次',
  unavailableTitle: '無法載入業務成果',
  unavailableDescription: '寧可不顯示，也不顯示猜測的數字。'
};

export const COPY: Record<Lang, ResultsCopy> = { en, 'zh-Hant': zh };

/** Fraction digits a currency's minor unit has, as Intl reports it (2 for USD, 0 for JPY). */
export function currencyDigits(currency: string): number {
  try {
    return new Intl.NumberFormat('en', { style: 'currency', currency: currency.toUpperCase() }).resolvedOptions().maximumFractionDigits ?? 2;
  } catch {
    return 2;
  }
}

/** One amount in its own currency, never converted. */
export function formatMoney(minor: number, currency: string, locale: string): string {
  const digits = currencyDigits(currency);
  const value = minor / 10 ** digits;
  try {
    return new Intl.NumberFormat(locale || 'en', { style: 'currency', currency: currency.toUpperCase() }).format(value);
  } catch {
    return `${value.toFixed(digits)} ${currency.toUpperCase()}`;
  }
}

/** One line per currency, sorted by code. Never a total across currencies. */
export function moneyLines(money: ClassSummary['money'] | undefined, locale: string): { currency: string; text: string; events: number }[] {
  return Object.entries(money ?? {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([currency, value]) => ({ currency, text: formatMoney(value.minor, currency, locale), events: value.events }));
}

/** "45.50" → 4550 (USD). `null` for an empty field; `undefined` when it can't be a whole number of minor units. */
export function parseAmount(text: string, currency: string): number | null | undefined {
  const cleaned = text.replace(/[\s,]/g, '');
  if (!cleaned) return null;
  const digits = currencyDigits(currency);
  const match = /^(\d{1,12})(?:\.(\d+))?$/.exec(cleaned);
  if (!match || (match[2] ?? '').length > digits) return undefined;
  const fraction = (match[2] ?? '').padEnd(digits, '0');
  const minor = Number(match[1]) * 10 ** digits + (fraction ? Number(fraction) : 0);
  return Number.isSafeInteger(minor) && minor <= 100_000_000_000 ? minor : undefined;
}

/** "3 leads · 1 sale" in a fixed order; empty when nothing remains. */
export function countPhrase(counts: ClassSummary['counts'] | undefined, copy: ResultsCopy): string {
  const order: Kind[] = ['lead', 'booking', 'newsletter_signup', 'sale', 'click'];
  return order
    .filter((kind) => (counts?.[kind] ?? 0) > 0)
    .map((kind) => copy.count(counts![kind]!, kind))
    .join(' · ');
}

export interface ClassView {
  provenance: Provenance;
  label: string;
  hint: string;
  available: boolean;
  headline: string;
  money: { currency: string; text: string; events: number }[];
  notes: string[];
}

/** What one source card says. `null` (no data) reads "No results in this period" or "Not connected", never 0. */
export function classView(provenance: Provenance, summary: ClassSummary | null, copy: ResultsCopy, locale: string): ClassView {
  const base = { provenance, label: copy.classes[provenance], hint: copy.classHints[provenance] };
  if (!summary) {
    return { ...base, available: false, headline: provenance === 'provider_native' ? copy.notConnected : copy.noResults, money: [], notes: [] };
  }
  const headline = countPhrase(summary.counts, copy) || copy.allWithdrawn;
  const notes = [
    summary.associated ? copy.associated(summary.associated) : '',
    summary.unattributed ? copy.unattributed(summary.unattributed) : '',
    summary.reversed ? copy.reversed(summary.reversed) : ''
  ].filter(Boolean);
  return { ...base, available: true, headline, money: moneyLines(summary.money, locale), notes };
}

/** The summary's state sentence: why the numbers may still change, or why there are none. */
export function stateSentence(state: State, open: boolean, sources: { errored: number; paused: number }, copy: ResultsCopy): string {
  if (state === 'unavailable') return copy.states.unavailable;
  if (state === 'stale') return copy.states.stale;
  if (state !== 'partial') return copy.states.available;
  if (sources.errored > 0) return copy.states.problem;
  if (open) return copy.states.open;
  return sources.paused > 0 ? copy.states.paused : copy.states.problem;
}

/** "5 minutes", "3 hours", "2 days". */
export function duration(seconds: number, copy: ResultsCopy): string {
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return copy.time.justNow;
  if (s < 3600) return copy.time.minutes(Math.round(s / 60));
  if (s < 86_400) return copy.time.hours(Math.round(s / 3600));
  return copy.time.days(Math.round(s / 86_400));
}

export function ago(at: number, now: number, copy: ResultsCopy): string {
  const text = duration(now - at, copy);
  return text === copy.time.justNow ? text : copy.time.ago(text);
}

/** A stored health code in words; unknown codes stay readable instead of hidden. */
export function problemText(code: string, copy: ResultsCopy): string {
  return copy.errors[code] ?? code.replaceAll('_', ' ');
}

export interface DeclarationForm {
  type: 'lead' | 'booking' | 'newsletter_signup' | 'sale';
  /** `datetime-local` value (YYYY-MM-DDTHH:mm), read in the browser's zone. */
  occurredAt: string;
  amount: string;
  currency: string;
  quantity: string;
  note: string;
  linkId: string;
  campaignRef: string;
}

export type DeclarationCheck =
  | { ok: true; value: { type: DeclarationForm['type']; occurredAt: string; amount: { minor: number; currency: string } | null; quantity: number; note: string | null; linkId: string | null; campaignRef: string | null } }
  | { ok: false; field: keyof DeclarationForm; message: string };

/** The form as the API's declaration, or the first field to fix (with its message). Nothing is guessed. */
export function checkDeclaration(form: DeclarationForm, copy: ResultsCopy, toIso: (local: string) => string | null = localToIso): DeclarationCheck {
  const occurredAt = form.occurredAt ? toIso(form.occurredAt) : null;
  if (!occurredAt) return { ok: false, field: 'occurredAt', message: copy.form.dateInvalid };
  const quantity = Number(form.quantity || '1');
  if (!Number.isInteger(quantity) || quantity < 1 || quantity > 1000) return { ok: false, field: 'quantity', message: copy.form.quantityInvalid };
  let amount: { minor: number; currency: string } | null = null;
  if (form.amount.trim()) {
    if (form.type !== 'booking' && form.type !== 'sale') return { ok: false, field: 'amount', message: copy.form.amountOnlyFor };
    const currency = form.currency.trim().toLowerCase();
    if (!/^[a-z]{3}$/.test(currency)) return { ok: false, field: 'currency', message: copy.form.currencyInvalid };
    const minor = parseAmount(form.amount, currency);
    if (minor === undefined || minor === null) return { ok: false, field: 'amount', message: copy.form.amountInvalid };
    amount = { minor, currency };
  }
  const campaignRef = form.campaignRef.trim();
  if (campaignRef && !/^[A-Za-z0-9_:-]{1,80}$/.test(campaignRef)) return { ok: false, field: 'campaignRef', message: copy.form.campaignInvalid };
  const note = form.note.split(/\s+/).filter(Boolean).join(' ').slice(0, 500);
  return { ok: true, value: { type: form.type, occurredAt, amount, quantity, note: note || null, linkId: form.linkId || null, campaignRef: campaignRef || null } };
}

/** A `datetime-local` value as an ISO instant (the browser's zone decides the offset). */
export function localToIso(local: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?$/.test(local)) return null;
  const date = new Date(local);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

/** An instant as a `datetime-local` value in the browser's zone (to prefill an edit). */
export function isoToLocal(seconds: number): string {
  const date = new Date(seconds * 1000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** An amount in minor units back into the form's text (4550 USD → "45.50"). */
export function amountText(minor: number, currency: string): string {
  const digits = currencyDigits(currency);
  return digits ? (minor / 10 ** digits).toFixed(digits) : String(minor);
}

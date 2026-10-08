/**
 * Journey chrome copy (lane E) in English, Traditional Chinese (Hong Kong wording) and Simplified Chinese.
 *
 * The app has no UI translation framework (evidence/r0/web-surfaces.md §12). Lane C's locale context
 * (`core/locale.tsx`, `useGenUiLocale().language`) decides the language for the whole view; these are the journey labels
 * in that language. Record text (titles, drafts, page facts) is shown as stored. Data only, no React.
 *
 * Words with a fixed meaning keep it in every language: "saved", "scheduled", "published" and "trained" are never used
 * for anything a service result did not report, and "prepared" never reads as "applied".
 */

export const JOURNEY_LOCALES = ['en', 'zh-Hant', 'zh-Hans'] as const;
/** Same values as lane C's `GenUiLanguage` (core/locale.tsx), which decides the language for the whole view. */
export type JourneyLocale = (typeof JOURNEY_LOCALES)[number];

/** BCP 47 tag used for Intl number/date formatting in each journey locale. */
export const INTL_TAG: Readonly<Record<JourneyLocale, string>> = { en: 'en', 'zh-Hant': 'zh-Hant-HK', 'zh-Hans': 'zh-Hans-CN' };

type Count = (n: number) => string;

export interface JourneyCopy {
  states: {
    loading: string;
    empty: string;
    denied: string;
    deniedHint: string;
    unavailable: string;
    invalid: string;
    invalidHint: string;
    partial: string;
    stale: string;
    historical: string;
  };
  common: {
    asOf: string;
    unknown: string;
    unavailable: string;
    notMeasured: string;
    none: string;
    noDate: string;
    rafiiNote: string;
    selectionHint: string;
    selected: Count;
    shownOf: (shown: number, total: number) => string;
    more: string;
    open: string;
    timeZone: string;
    rule: string;
    demo: string;
    verified: string;
    notVerified: string;
    prepared: string;
    preparedHint: string;
    applied: string;
    working: string;
    confirmInSheet: string;
    actionUnavailable: string;
    waitForView: string;
    tryAgain: string;
  };
  drafts: {
    title: string;
    platform: string;
    language: string;
    account: string;
    characters: string;
    overLimit: (limit: number) => string;
    needsReview: string;
    rewriteWaiting: string;
    inQueue: string;
    setAside: string;
    voicePersonal: string;
    voiceNeutral: string;
    sources: Count;
    sourcesLabel: string;
    voiceLabel: string;
    unknowns: Count;
    warnings: Count;
    revision: (n: number) => string;
    compareTitle: string;
    compareNeedTwo: string;
    missingRequested: string;
    text: string;
    openings: string;
    editLabel: string;
    editBlocked: string;
    editHint: string;
    save: string;
    evidenceTitle: string;
    sourceRemoved: string;
    approvedFacts: (approved: number, total: number) => string;
    voiceFit: string;
    relations: string;
    blockedByRetraction: string;
    scheduledAt: string;
    fromAutomation: string;
  };
  calendar: {
    title: string;
    when: string;
    status: string;
    statusLabel: Readonly<Record<string, string>>;
    unknownStates: string;
    closeTogether: (minutes: number) => string;
    emptyDays: string;
    queueTitle: string;
    waitingApproval: string;
    upcoming: string;
    attention: string;
    draftsUnscheduled: string;
    expired: string;
    slotTitle: string;
    slotValid: string;
    slotInvalid: string;
    collisions: Count;
    noCollisions: string;
    rescheduleTitle: string;
    date: string;
    time: string;
    pickTarget: string;
    prepare: string;
    prepareHint: string;
    proposalsTitle: string;
    proposalExpires: string;
    applyOnCard: string;
    jobZone: string;
  };
}

const EN: JourneyCopy = {
  states: {
    loading: 'Getting the latest records…',
    empty: 'Nothing here yet.',
    denied: 'You don’t have access to this.',
    deniedHint: 'Ask a workspace owner if you need it.',
    unavailable: 'This can’t be shown right now.',
    invalid: 'Rafii couldn’t show this data.',
    invalidHint: 'The records are unchanged. Open the page itself to see them.',
    partial: 'Only part of this could be read.',
    stale: 'This may be out of date.',
    historical: 'Saved view from earlier',
  },
  common: {
    asOf: 'As of',
    unknown: 'Unknown',
    unavailable: 'Unavailable',
    notMeasured: 'Not measured',
    none: 'None',
    noDate: 'No date',
    rafiiNote: 'Rafii’s note',
    selectionHint: 'Picking only selects. Nothing is approved, scheduled or published.',
    selected: (n) => (n === 1 ? '1 selected' : `${n} selected`),
    shownOf: (shown, total) => `Showing ${shown} of ${total}`,
    more: 'More',
    open: 'Open',
    timeZone: 'Time zone',
    rule: 'Rule',
    demo: 'Practice run',
    verified: 'Verified',
    notVerified: 'Not verified yet',
    prepared: 'Prepared for review',
    preparedHint: 'Nothing changes until you apply it on its card.',
    applied: 'Done',
    working: 'Working…',
    confirmInSheet: 'Check the details to continue.',
    actionUnavailable: 'This action isn’t available here.',
    waitForView: 'Available when the view has finished loading.',
    tryAgain: 'Try again',
  },
  drafts: {
    title: 'Drafts',
    platform: 'Platform',
    language: 'Language',
    account: 'Account',
    characters: 'Characters',
    overLimit: (limit) => `Over the ${limit}-character limit`,
    needsReview: 'Needs review',
    rewriteWaiting: 'Rewrite waiting',
    inQueue: 'In the publishing queue',
    setAside: 'Set aside',
    voicePersonal: 'Your voice',
    voiceNeutral: 'Neutral voice',
    sources: (n) => (n === 1 ? '1 source' : `${n} sources`),
    sourcesLabel: 'Sources',
    voiceLabel: 'Voice',
    unknowns: (n) => (n === 1 ? '1 open question' : `${n} open questions`),
    warnings: (n) => (n === 1 ? '1 warning' : `${n} warnings`),
    revision: (n) => `Revision ${n}`,
    compareTitle: 'Drafts side by side',
    compareNeedTwo: 'Pick two to four drafts to compare them.',
    missingRequested: 'Some drafts you picked are no longer in this workspace.',
    text: 'Text',
    openings: 'Other openings',
    editLabel: 'Draft text',
    editBlocked: 'This draft can’t be edited here.',
    editHint: 'Saving asks you to check the change first. The draft then needs review again.',
    save: 'Save edit',
    evidenceTitle: 'Where this draft came from',
    sourceRemoved: 'No longer in the workspace',
    approvedFacts: (approved, total) => `${approved} of ${total} facts approved`,
    voiceFit: 'Voice check',
    relations: 'Linked records',
    blockedByRetraction: 'A source behind this draft was withdrawn.',
    scheduledAt: 'Scheduled for',
    fromAutomation: 'From an automation',
  },
  calendar: {
    title: 'Calendar',
    when: 'When',
    status: 'Status',
    statusLabel: {
      scheduled: 'Scheduled',
      awaiting_approval: 'Waiting for approval',
      in_flight: 'Publishing',
      failed_held_uncertain: 'Needs attention',
      published: 'Published',
      verified: 'Published and checked',
      planned: 'Planned',
      unknown: 'Unknown state',
    },
    unknownStates: 'Some items are in a state Rafii doesn’t recognise. They are counted as unknown.',
    closeTogether: (minutes) => `Less than 2 hours apart on the same account (${minutes} min)`,
    emptyDays: 'Open days',
    queueTitle: 'Publishing queue',
    waitingApproval: 'Waiting for approval',
    upcoming: 'Approved, waiting for their time',
    attention: 'Needs attention',
    draftsUnscheduled: 'Drafts not scheduled',
    expired: 'Approval expired',
    slotTitle: 'Time check',
    slotValid: 'This time works.',
    slotInvalid: 'This time can’t be used.',
    collisions: (n) => (n === 1 ? '1 post nearby on this account' : `${n} posts nearby on this account`),
    noCollisions: 'No other posts on this account within 2 hours.',
    rescheduleTitle: 'Choose a time',
    date: 'Date',
    time: 'Time',
    pickTarget: 'Pick a draft or a waiting post first.',
    prepare: 'Prepare proposal',
    prepareHint: 'This prepares a proposal. Nothing is scheduled until you apply it, and the post still needs its own approval.',
    proposalsTitle: 'Waiting for you',
    proposalExpires: 'Expires',
    applyOnCard: 'Apply or dismiss it on its card in this conversation.',
    jobZone: 'Post’s own time zone',
  },
};

const ZH_HANT: JourneyCopy = {
  states: {
    loading: '正在讀取最新紀錄…',
    empty: '暫時未有內容。',
    denied: '你沒有權限查看。',
    deniedHint: '如有需要，請向工作區擁有人申請。',
    unavailable: '暫時未能顯示。',
    invalid: 'Rafii 未能顯示這些資料。',
    invalidHint: '紀錄沒有改動，可到相關頁面查看。',
    partial: '只讀取到部分資料。',
    stale: '資料可能不是最新。',
    historical: '較早前保存的畫面',
  },
  common: {
    asOf: '資料時間',
    unknown: '不明',
    unavailable: '未能提供',
    notMeasured: '未有量度',
    none: '沒有',
    noDate: '沒有日期',
    rafiiNote: 'Rafii 的說明',
    selectionHint: '揀選只是選取，不會批准、排程或發佈任何內容。',
    selected: (n) => `已選 ${n} 項`,
    shownOf: (shown, total) => `顯示 ${shown} / ${total}`,
    more: '更多',
    open: '打開',
    timeZone: '時區',
    rule: '規則',
    demo: '練習運行',
    verified: '已核實',
    notVerified: '尚未核實',
    prepared: '已準備，待你審閱',
    preparedHint: '在卡片上套用之前，不會有任何改動。',
    applied: '完成',
    working: '處理中…',
    confirmInSheet: '請先核對詳情。',
    actionUnavailable: '這裏不能進行這個操作。',
    waitForView: '畫面載入完成後才可使用。',
    tryAgain: '再試一次',
  },
  drafts: {
    title: '草稿',
    platform: '平台',
    language: '語言',
    account: '帳戶',
    characters: '字數',
    overLimit: (limit) => `超出 ${limit} 字上限`,
    needsReview: '需要審閱',
    rewriteWaiting: '有改寫待處理',
    inQueue: '已在發佈佇列',
    setAside: '已擱置',
    voicePersonal: '你的語氣',
    voiceNeutral: '中性語氣',
    sources: (n) => `${n} 個來源`,
    sourcesLabel: '來源',
    voiceLabel: '語氣',
    unknowns: (n) => `${n} 個待確認問題`,
    warnings: (n) => `${n} 個提示`,
    revision: (n) => `第 ${n} 版`,
    compareTitle: '草稿並排比較',
    compareNeedTwo: '揀選兩至四份草稿作比較。',
    missingRequested: '你揀選的部分草稿已不在這個工作區。',
    text: '內文',
    openings: '其他開頭',
    editLabel: '草稿內文',
    editBlocked: '這份草稿不能在這裏修改。',
    editHint: '儲存前會先請你核對改動，之後草稿需要重新審閱。',
    save: '儲存修改',
    evidenceTitle: '這份草稿的來源',
    sourceRemoved: '已不在工作區',
    approvedFacts: (approved, total) => `${total} 項事實中 ${approved} 項已批准`,
    voiceFit: '語氣檢查',
    relations: '相關紀錄',
    blockedByRetraction: '這份草稿引用的一個來源已撤回。',
    scheduledAt: '排程時間',
    fromAutomation: '來自自動化',
  },
  calendar: {
    title: '日曆',
    when: '時間',
    status: '狀態',
    statusLabel: {
      scheduled: '已排程',
      awaiting_approval: '等待批准',
      in_flight: '發佈中',
      failed_held_uncertain: '需要處理',
      published: '已發佈',
      verified: '已發佈並核實',
      planned: '已計劃',
      unknown: '狀態不明',
    },
    unknownStates: '部分項目的狀態 Rafii 未能辨認，已計作不明。',
    closeTogether: (minutes) => `同一帳戶相隔不足 2 小時（${minutes} 分鐘）`,
    emptyDays: '未有安排的日子',
    queueTitle: '發佈佇列',
    waitingApproval: '等待批准',
    upcoming: '已批准，等待發佈時間',
    attention: '需要處理',
    draftsUnscheduled: '未排程草稿',
    expired: '批准已過期',
    slotTitle: '時間檢查',
    slotValid: '這個時間可以使用。',
    slotInvalid: '這個時間不能使用。',
    collisions: (n) => `此帳戶附近有 ${n} 個帖文`,
    noCollisions: '此帳戶前後 2 小時內沒有其他帖文。',
    rescheduleTitle: '選擇時間',
    date: '日期',
    time: '時間',
    pickTarget: '請先揀選草稿或等待中的帖文。',
    prepare: '準備建議',
    prepareHint: '這只會準備一個建議。套用之前不會排程，帖文仍需要另行批准。',
    proposalsTitle: '等待你處理',
    proposalExpires: '到期',
    applyOnCard: '請在對話中的卡片上套用或略過。',
    jobZone: '帖文本身的時區',
  },
};

const ZH_HANS: JourneyCopy = {
  states: {
    loading: '正在读取最新记录…',
    empty: '暂时没有内容。',
    denied: '你没有权限查看。',
    deniedHint: '如有需要，请向工作区所有者申请。',
    unavailable: '暂时无法显示。',
    invalid: 'Rafii 无法显示这些数据。',
    invalidHint: '记录没有改动，可以到相关页面查看。',
    partial: '只读取到部分数据。',
    stale: '数据可能不是最新的。',
    historical: '之前保存的视图',
  },
  common: {
    asOf: '数据时间',
    unknown: '未知',
    unavailable: '暂无',
    notMeasured: '未测量',
    none: '无',
    noDate: '无日期',
    rafiiNote: 'Rafii 的说明',
    selectionHint: '选择只是选中，不会批准、排程或发布任何内容。',
    selected: (n) => `已选 ${n} 项`,
    shownOf: (shown, total) => `显示 ${shown} / ${total}`,
    more: '更多',
    open: '打开',
    timeZone: '时区',
    rule: '规则',
    demo: '练习运行',
    verified: '已核实',
    notVerified: '尚未核实',
    prepared: '已准备，等你审阅',
    preparedHint: '在卡片上应用之前，不会有任何改动。',
    applied: '完成',
    working: '处理中…',
    confirmInSheet: '请先核对详情。',
    actionUnavailable: '这里不能进行这个操作。',
    waitForView: '视图加载完成后才可使用。',
    tryAgain: '再试一次',
  },
  drafts: {
    title: '草稿',
    platform: '平台',
    language: '语言',
    account: '账户',
    characters: '字数',
    overLimit: (limit) => `超出 ${limit} 字上限`,
    needsReview: '需要审阅',
    rewriteWaiting: '有改写待处理',
    inQueue: '已在发布队列',
    setAside: '已搁置',
    voicePersonal: '你的语气',
    voiceNeutral: '中性语气',
    sources: (n) => `${n} 个来源`,
    sourcesLabel: '来源',
    voiceLabel: '语气',
    unknowns: (n) => `${n} 个待确认问题`,
    warnings: (n) => `${n} 个提示`,
    revision: (n) => `第 ${n} 版`,
    compareTitle: '草稿并排比较',
    compareNeedTwo: '选择两到四份草稿进行比较。',
    missingRequested: '你选择的部分草稿已不在这个工作区。',
    text: '正文',
    openings: '其他开头',
    editLabel: '草稿正文',
    editBlocked: '这份草稿不能在这里修改。',
    editHint: '保存前会先请你核对改动，之后草稿需要重新审阅。',
    save: '保存修改',
    evidenceTitle: '这份草稿的来源',
    sourceRemoved: '已不在工作区',
    approvedFacts: (approved, total) => `${total} 项事实中 ${approved} 项已批准`,
    voiceFit: '语气检查',
    relations: '相关记录',
    blockedByRetraction: '这份草稿引用的一个来源已撤回。',
    scheduledAt: '排程时间',
    fromAutomation: '来自自动化',
  },
  calendar: {
    title: '日历',
    when: '时间',
    status: '状态',
    statusLabel: {
      scheduled: '已排程',
      awaiting_approval: '等待批准',
      in_flight: '发布中',
      failed_held_uncertain: '需要处理',
      published: '已发布',
      verified: '已发布并核实',
      planned: '已计划',
      unknown: '状态未知',
    },
    unknownStates: '部分项目的状态 Rafii 无法识别，已计为未知。',
    closeTogether: (minutes) => `同一账户间隔不到 2 小时（${minutes} 分钟）`,
    emptyDays: '没有安排的日子',
    queueTitle: '发布队列',
    waitingApproval: '等待批准',
    upcoming: '已批准，等待发布时间',
    attention: '需要处理',
    draftsUnscheduled: '未排程草稿',
    expired: '批准已过期',
    slotTitle: '时间检查',
    slotValid: '这个时间可以使用。',
    slotInvalid: '这个时间不能使用。',
    collisions: (n) => `此账户附近有 ${n} 条帖子`,
    noCollisions: '此账户前后 2 小时内没有其他帖子。',
    rescheduleTitle: '选择时间',
    date: '日期',
    time: '时间',
    pickTarget: '请先选择草稿或等待中的帖子。',
    prepare: '准备建议',
    prepareHint: '这只会准备一个建议。应用之前不会排程，帖子仍需要另行批准。',
    proposalsTitle: '等待你处理',
    proposalExpires: '到期',
    applyOnCard: '请在对话中的卡片上应用或忽略。',
    jobZone: '帖子本身的时区',
  },
};

const COPY: Readonly<Record<JourneyLocale, JourneyCopy>> = { en: EN, 'zh-Hant': ZH_HANT, 'zh-Hans': ZH_HANS };

export function journeyCopy(locale: JourneyLocale): JourneyCopy {
  return COPY[locale] ?? EN;
}

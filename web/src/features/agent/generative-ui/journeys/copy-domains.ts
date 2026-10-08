/**
 * Journey labels for J03–J09 (lane E), in English, Traditional Chinese (Hong Kong wording) and Simplified Chinese.
 * Merged into `journeyCopy()` (copy.ts). Data only, no React. Words with a fixed meaning keep it: nothing here says
 * "trained", "saved", "scheduled" or "published" unless the component shows a service result that says so.
 */
import type { JourneyLocale } from './copy';

type Count = (n: number) => string;

export interface DomainCopy {
  tasks: { title: string; state: Readonly<Record<string, string>>; doneOf: (done: number, total: number) => string; dependsOn: string; verifiedByTool: string };
  library: {
    title: string;
    kind: Readonly<Record<string, string>>;
    alreadySource: string;
    duplicate: string;
    extractionProblem: string;
    processing: string;
    size: string;
    tags: string;
    pickUpTo: Count;
    lineageTitle: string;
    excerptTitle: string;
    chunks: Count;
    modelMayView: string;
    modelMayNotView: string;
    useAsSourceHint: string;
    selectionTitle: string;
    attachments: Count;
    references: Count;
    refused: Readonly<Record<string, string>>;
    sendHint: string;
    noPreview: string;
    open: string;
  };
  voice: {
    samplesTitle: string;
    origin: string;
    selected: string;
    notSelected: string;
    revoked: string;
    grants: string;
    noGrants: string;
    eligibility: (purpose: string, route: string) => string;
    excluded: Readonly<Record<string, string>>;
    analyzeHint: string;
    pickSamples: string;
    profileTitle: string;
    approved: string;
    proposed: string;
    noneApproved: string;
    noneProposed: string;
    stale: string;
    evidence: Readonly<Record<string, string>>;
    supports: Count;
    against: Count;
    affects: (drafts: number, posts: number) => string;
    method: Readonly<Record<string, string>>;
    prefsTitle: string;
    learned: string;
    pending: string;
    noLearned: string;
    noPending: string;
    why: string;
    remember: string;
    dismiss: string;
    consentTitle: string;
    layer: Readonly<Record<string, string>>;
    on: string;
    off: string;
    samplesGranted: (analysis: number, generation: number, total: number) => string;
    ownerDecides: string;
    learningTitle: string;
    learningOn: string;
    learningOff: string;
    eventsWaiting: string;
    pendingProposals: string;
    newestProposal: string;
    importTitle: string;
    importText: string;
    importTitleField: string;
    importConfirm: string;
    importHint: string;
  };
  campaigns: {
    listTitle: string;
    goal: string;
    audience: string;
    status: Readonly<Record<string, string>>;
    missingFacts: string;
    facts: string;
    automations: string;
    platforms: string;
    nextRun: string;
    noNextRun: string;
    gaps: string;
    progressTitle: string;
    progress: (p: { drafts: number; review: number; posts: number; verified: number; waiting: number }) => string;
    missingItems: Count;
    itemsTitle: string;
    itemKind: Readonly<Record<string, string>>;
    itemGone: string;
    timelineTitle: string;
    eventKind: Readonly<Record<string, string>>;
    noDependencies: string;
    briefTitle: string;
    date: string;
    venue: string;
    briefHint: string;
    editTitle: string;
    editHint: string;
    linkTitle: string;
    linkHint: string;
    pickDrafts: string;
  };
  analytics: {
    tableTitle: string;
    metric: Readonly<Record<string, string>>;
    published: string;
    post: string;
    availability: Readonly<Record<string, string>>;
    readAfter: string;
    chartTitle: string;
    showTable: string;
    hideTable: string;
    bucket: string;
    measuredOf: (measured: number, posts: number) => string;
    compareTitle: string;
    interpretation: Readonly<Record<string, string>>;
    sampleSize: string;
    measured: string;
    missing: string;
    mean: string;
    minimum: (n: number) => string;
    notCausal: string;
    coverageTitle: string;
    coverageState: Readonly<Record<string, string>>;
    direct: string;
    notDirect: string;
    readOf: (read: number, verified: number) => string;
    enable: string;
    lastReading: string;
    feedbackTitle: string;
    undated: Count;
    readingsOf: (withReadings: number, verified: number) => string;
  };
  research: {
    statusTitle: string;
    on: string;
    off: string;
    reason: Readonly<Record<string, string>>;
    openGuide: string;
    briefTitle: string;
    fetched: string;
    quoted: string;
    unsafeUrl: string;
    pickPages: string;
    savedTitle: string;
    factsApproved: (approved: number, total: number) => string;
    retracted: string;
    matrixTitle: string;
    pickToCompare: string;
    facts: string;
  };
  automations: {
    listTitle: string;
    status: Readonly<Record<string, string>>;
    nextRun: string;
    noNextRun: string;
    policy: Readonly<Record<string, string>>;
    platforms: string;
    detailTitle: string;
    upcoming: string;
    needs: string;
    paused: string;
    historyTitle: string;
    attention: string;
    cost: string;
    costUnknown: string;
    runStatus: Readonly<Record<string, string>>;
    connectionsTitle: string;
    needsReconnect: string;
    canPublish: string;
    cannotPublish: string;
    reconnect: string;
    attentionUnavailable: string;
    guidesTitle: string;
    openGuide: string;
    changeTitle: string;
    changeLabel: string;
    changeHint: string;
    pickAutomation: string;
  };
  founder: {
    metricsTitle: string;
    costsTitle: string;
    attentionTitle: string;
    sourcesTitle: string;
    receipt: string;
    dataState: Readonly<Record<string, string>>;
    actual: string;
    estimated: string;
    costState: string;
    severity: Readonly<Record<string, string>>;
    lastGood: string;
    since: string;
    previous: string;
    current: string;
    demo: string;
  };
}

const EN: DomainCopy = {
  tasks: {
    title: 'Progress',
    state: { planned: 'Not started', running: 'In progress', done: 'Done', needs_user: 'Needs you', blocked: 'Blocked', failed: 'Failed', canceled: 'Cancelled' },
    doneOf: (done, total) => `${done} of ${total} steps done`,
    dependsOn: 'After',
    verifiedByTool: 'Checked by Rafii',
  },
  library: {
    title: 'Library',
    kind: { image: 'Photo', video: 'Video', audio: 'Audio', document: 'Document', file: 'File' },
    alreadySource: 'Already a source',
    duplicate: 'Duplicate',
    extractionProblem: 'Text couldn’t be read',
    processing: 'Processing',
    size: 'Size',
    tags: 'Tags',
    pickUpTo: (n) => `Pick up to ${n} for your next message.`,
    lineageTitle: 'Where it came from',
    excerptTitle: 'Text in this file',
    chunks: (n) => (n === 1 ? '1 indexed passage' : `${n} indexed passages`),
    modelMayView: 'Rafii may look at this photo when you send it.',
    modelMayNotView: 'Rafii won’t look at photos until an owner allows it.',
    useAsSourceHint: 'Imports this file’s text as a source that needs your review before Rafii uses its facts.',
    selectionTitle: 'Ready for your next message',
    attachments: (n) => (n === 1 ? '1 attachment' : `${n} attachments`),
    references: (n) => (n === 1 ? '1 source' : `${n} sources`),
    refused: { not_ready: 'Still processing', not_found: 'No longer in the Library', needs_source_import: 'Use it as a source first' },
    sendHint: 'Write your next message to use these. Selecting doesn’t send or publish anything.',
    noPreview: 'No preview',
    open: 'Open in Library',
  },
  voice: {
    samplesTitle: 'Writing samples',
    origin: 'Origin',
    selected: 'Used in analysis',
    notSelected: 'Not used',
    revoked: 'Revoked',
    grants: 'Allowed for',
    noGrants: 'Not allowed for any use yet',
    eligibility: (purpose, route) => `For ${purpose} on ${route}`,
    excluded: {
      revoked: 'Revoked',
      not_selected: 'Not selected',
      purpose_not_granted: 'Not allowed for this use',
      route_not_granted: 'Not allowed for this writer',
    },
    analyzeHint: 'Local analysis uses Rafii’s own rules: no AI model and no cost. The result is a proposal.',
    pickSamples: 'Pick the samples to analyse.',
    profileTitle: 'Voice profile',
    approved: 'In effect',
    proposed: 'Proposed',
    noneApproved: 'No approved voice yet.',
    noneProposed: 'Nothing waiting for approval.',
    stale: 'Out of date',
    evidence: { supported: 'Supported', strong: 'Strong evidence', moderate: 'Some evidence', limited: 'Limited evidence', weak: 'Weak evidence', conflicting: 'Mixed evidence', insufficient: 'Not enough evidence' },
    supports: (n) => (n === 1 ? '1 supporting sample' : `${n} supporting samples`),
    against: (n) => (n === 1 ? '1 against' : `${n} against`),
    affects: (drafts, posts) => `Approving marks ${drafts} draft${drafts === 1 ? '' : 's'} for review and affects ${posts} waiting post${posts === 1 ? '' : 's'}.`,
    method: { 'local-rules': 'Rafii’s rules', ai: 'AI analysis' },
    prefsTitle: 'Learned preferences',
    learned: 'In effect',
    pending: 'Waiting for an owner',
    noLearned: 'Nothing learned yet.',
    noPending: 'No proposals waiting.',
    why: 'Why',
    remember: 'Remember',
    dismiss: 'Dismiss',
    consentTitle: 'What you’ve allowed',
    layer: { samples: 'Writing samples', cloudMemory: 'Cloud memory', cloudExtraction: 'Learning from edits in the cloud', media: 'Photo processing', webResearch: 'Web research' },
    on: 'On',
    off: 'Off',
    samplesGranted: (analysis, generation, total) => `${analysis} of ${total} allowed for analysis, ${generation} for writing`,
    ownerDecides: 'Only an owner can change these, on the Memory page.',
    learningTitle: 'Learning status',
    learningOn: 'Learning is on',
    learningOff: 'Learning is off',
    eventsWaiting: 'Edits waiting to be read',
    pendingProposals: 'Proposals waiting',
    newestProposal: 'Newest proposal',
    importTitle: 'Add a writing sample',
    importText: 'Paste your writing',
    importTitleField: 'Title (optional)',
    importConfirm: 'This is my own writing and Rafii may keep it as a private style sample.',
    importHint: 'Samples are style evidence only, never facts for posts.',
  },
  campaigns: {
    listTitle: 'Campaigns',
    goal: 'Goal',
    audience: 'Audience',
    status: { needs_input: 'Needs details', draft: 'Draft', active: 'Active', completed: 'Completed', cancelled: 'Cancelled' },
    missingFacts: 'Still missing',
    facts: 'Details',
    automations: 'Automations',
    platforms: 'Platforms',
    nextRun: 'Next run',
    noNextRun: 'No upcoming run',
    gaps: 'Gaps',
    progressTitle: 'Progress',
    progress: (p) => `${p.drafts} drafts (${p.review} need review) · ${p.posts} posts (${p.verified} published and checked, ${p.waiting} waiting)`,
    missingItems: (n) => (n === 1 ? '1 linked item is gone' : `${n} linked items are gone`),
    itemsTitle: 'In this campaign',
    itemKind: { draft: 'Draft', post: 'Post', asset: 'Image' },
    itemGone: 'No longer in the workspace',
    timelineTitle: 'Timeline',
    eventKind: { planned_run: 'Planned run', run: 'Run', post: 'Post' },
    noDependencies: 'Rafii doesn’t record dependencies between campaign items.',
    briefTitle: 'New campaign',
    date: 'Date (optional)',
    venue: 'Venue (optional)',
    briefHint: 'Creates the brief only. Nothing is drafted, scheduled or published.',
    editTitle: 'Edit the brief',
    editHint: 'Saving pauses its active automations until you resume them.',
    linkTitle: 'Add to this campaign',
    linkHint: 'Organisation only: nothing is drafted, scheduled or published.',
    pickDrafts: 'Pick drafts first.',
  },
  analytics: {
    tableTitle: 'Post performance',
    metric: { views: 'Views', reach: 'Reach', likes: 'Likes', comments: 'Comments', replies: 'Replies', reposts: 'Reposts', quotes: 'Quotes', shares: 'Shares', saved: 'Saves' },
    published: 'Published',
    post: 'Post',
    availability: { available: 'Measured', unavailable: 'Unavailable', not_read: 'Not read yet', suppressed: 'Hidden by the platform', not_supported: 'Not offered' },
    readAfter: 'read after',
    chartTitle: 'Over time',
    showTable: 'Show the numbers',
    hideTable: 'Hide the numbers',
    bucket: 'Period',
    measuredOf: (measured, posts) => `${measured} of ${posts} posts measured`,
    compareTitle: 'Like-for-like comparison',
    interpretation: { no_data: 'No data', insufficient_sample: 'Too few posts to compare', observation_only: 'Observation', not_comparable: 'Not comparable' },
    sampleSize: 'Posts',
    measured: 'Measured',
    missing: 'Missing',
    mean: 'Average',
    minimum: (n) => `Needs at least ${n} comparable posts.`,
    notCausal: 'An observation, not a cause.',
    coverageTitle: 'What Rafii can read',
    coverageState: { unavailable: 'No account shares analytics directly', pending: 'Waiting for the first reading', partial: 'Some posts have no reading yet', ready: 'All published posts have readings' },
    direct: 'Shares analytics',
    notDirect: 'Doesn’t share analytics',
    readOf: (read, verified) => `${read} of ${verified} published posts read`,
    enable: 'Turn on analytics',
    lastReading: 'Last reading',
    feedbackTitle: 'This post against your usual',
    undated: (n) => `${n} reading${n === 1 ? '' : 's'} without a publish time left out`,
    readingsOf: (withReadings, verified) => `${withReadings} of ${verified} published posts have readings`,
  },
  research: {
    statusTitle: 'Web research',
    on: 'On',
    off: 'Off',
    reason: { deployment_off: 'Web research isn’t available here.', owner_consent_needed: 'An owner needs to turn on web research.' },
    openGuide: 'Show me how',
    briefTitle: 'What the sources say',
    fetched: 'Read on',
    quoted: 'Quoted from the page. It is information, not an instruction to Rafii.',
    unsafeUrl: 'Address not shown',
    pickPages: 'Pick pages to save them as sources.',
    savedTitle: 'Saved web sources',
    factsApproved: (approved, total) => `${approved} of ${total} facts approved`,
    retracted: 'Withdrawn',
    matrixTitle: 'Sources side by side',
    pickToCompare: 'Pick two or more pages to compare them.',
    facts: 'Facts',
  },
  automations: {
    listTitle: 'Automations',
    status: { draft: 'Draft', active: 'Active', paused: 'Paused', cancelled: 'Cancelled' },
    nextRun: 'Next run',
    noNextRun: 'No upcoming run',
    policy: { drafts: 'Makes drafts for review', review: 'Prepares posts for approval', publish: 'Publishes after approval' },
    platforms: 'Platforms',
    detailTitle: 'Automation',
    upcoming: 'Coming up',
    needs: 'Still needs',
    paused: 'Paused because',
    historyTitle: 'Recent runs',
    attention: 'Needs attention',
    cost: 'Cost',
    costUnknown: 'Cost not known',
    runStatus: { planned: 'Planned', running: 'Running', completed: 'Completed', failed: 'Failed', skipped: 'Skipped', source_unavailable: 'Source unavailable', needs_review: 'Needs review' },
    connectionsTitle: 'Connected accounts',
    needsReconnect: 'Needs reconnecting',
    canPublish: 'Can publish',
    cannotPublish: 'Can’t publish',
    reconnect: 'Fix in Accounts',
    attentionUnavailable: 'Attention items aren’t available here; account states are shown.',
    guidesTitle: 'Step-by-step help',
    openGuide: 'Open guide',
    changeTitle: 'Ask for a change',
    changeLabel: 'What should change?',
    changeHint: 'This prepares a proposal. Nothing changes until you apply it on its card.',
    pickAutomation: 'Pick an automation first.',
  },
  founder: {
    metricsTitle: 'Metrics',
    costsTitle: 'AI cost',
    attentionTitle: 'Needs your attention',
    sourcesTitle: 'Data sources',
    receipt: 'Receipt',
    dataState: { available: 'Measured', measured: 'Measured', partial: 'Partial', unavailable: 'Unavailable', stale: 'Out of date', empty: 'Empty' },
    actual: 'Actual',
    estimated: 'Estimated',
    costState: 'Cost basis',
    severity: { critical: 'Critical', warning: 'Warning', info: 'Info' },
    lastGood: 'Last good',
    since: 'Since',
    previous: 'Previous period',
    current: 'This period',
    demo: 'Demo data',
  },
};

const ZH_HANT: DomainCopy = {
  tasks: {
    title: '進度',
    state: { planned: '未開始', running: '進行中', done: '完成', needs_user: '需要你處理', blocked: '受阻', failed: '失敗', canceled: '已取消' },
    doneOf: (done, total) => `${total} 個步驟中完成 ${done} 個`,
    dependsOn: '之後',
    verifiedByTool: 'Rafii 已核實',
  },
  library: {
    title: '資料庫',
    kind: { image: '相片', video: '影片', audio: '音訊', document: '文件', file: '檔案' },
    alreadySource: '已是來源',
    duplicate: '重複',
    extractionProblem: '未能讀取文字',
    processing: '處理中',
    size: '大小',
    tags: '標籤',
    pickUpTo: (n) => `最多揀選 ${n} 項用於下一則訊息。`,
    lineageTitle: '來龍去脈',
    excerptTitle: '檔案內的文字',
    chunks: (n) => `${n} 段已索引內容`,
    modelMayView: '你傳送後，Rafii 可以查看這張相片。',
    modelMayNotView: '擁有人允許之前，Rafii 不會查看相片。',
    useAsSourceHint: '把檔案文字匯入為來源；Rafii 使用其中事實前需要你審閱。',
    selectionTitle: '可用於下一則訊息',
    attachments: (n) => `${n} 個附件`,
    references: (n) => `${n} 個來源`,
    refused: { not_ready: '仍在處理', not_found: '已不在資料庫', needs_source_import: '請先設為來源' },
    sendHint: '在下一則訊息中使用。揀選不會傳送或發佈任何內容。',
    noPreview: '沒有預覽',
    open: '在資料庫打開',
  },
  voice: {
    samplesTitle: '寫作樣本',
    origin: '來源',
    selected: '用於分析',
    notSelected: '未使用',
    revoked: '已撤回',
    grants: '允許用於',
    noGrants: '尚未允許任何用途',
    eligibility: (purpose, route) => `用於 ${purpose}（${route}）`,
    excluded: { revoked: '已撤回', not_selected: '未選取', purpose_not_granted: '未允許此用途', route_not_granted: '未允許此寫作模型' },
    analyzeHint: '本機分析使用 Rafii 自己的規則：不用 AI 模型，不收費。結果只是建議。',
    pickSamples: '請揀選要分析的樣本。',
    profileTitle: '語氣檔案',
    approved: '生效中',
    proposed: '建議中',
    noneApproved: '尚未有已批准的語氣。',
    noneProposed: '沒有等待批准的建議。',
    stale: '已過時',
    evidence: { supported: '有支持', strong: '證據充分', moderate: '有一定證據', limited: '證據有限', weak: '證據薄弱', conflicting: '證據不一致', insufficient: '證據不足' },
    supports: (n) => `${n} 個支持樣本`,
    against: (n) => `${n} 個相反`,
    affects: (drafts, posts) => `批准後，${drafts} 份草稿需要重新審閱，並影響 ${posts} 個等待中的帖文。`,
    method: { 'local-rules': 'Rafii 規則', ai: 'AI 分析' },
    prefsTitle: '已學習的偏好',
    learned: '生效中',
    pending: '等待擁有人決定',
    noLearned: '暫時未有學到的偏好。',
    noPending: '沒有等待中的建議。',
    why: '原因',
    remember: '記住',
    dismiss: '略過',
    consentTitle: '你已允許的事項',
    layer: { samples: '寫作樣本', cloudMemory: '雲端記憶', cloudExtraction: '在雲端從修改中學習', media: '相片處理', webResearch: '網上搜尋' },
    on: '開啟',
    off: '關閉',
    samplesGranted: (analysis, generation, total) => `${total} 個中 ${analysis} 個允許分析、${generation} 個允許寫作`,
    ownerDecides: '只有擁有人可以在記憶頁更改。',
    learningTitle: '學習狀態',
    learningOn: '學習已開啟',
    learningOff: '學習已關閉',
    eventsWaiting: '等待讀取的修改',
    pendingProposals: '等待中的建議',
    newestProposal: '最新建議',
    importTitle: '加入寫作樣本',
    importText: '貼上你的文字',
    importTitleField: '標題（可選）',
    importConfirm: '這是我自己寫的文字，Rafii 可以保存為私人風格樣本。',
    importHint: '樣本只作風格參考，不會當作帖文事實。',
  },
  campaigns: {
    listTitle: '推廣活動',
    goal: '目標',
    audience: '對象',
    status: { needs_input: '需要補充資料', draft: '草稿', active: '進行中', completed: '已完成', cancelled: '已取消' },
    missingFacts: '仍欠',
    facts: '資料',
    automations: '自動化',
    platforms: '平台',
    nextRun: '下次運行',
    noNextRun: '沒有即將運行',
    gaps: '缺口',
    progressTitle: '進度',
    progress: (p) => `${p.drafts} 份草稿（${p.review} 份需要審閱）· ${p.posts} 個帖文（${p.verified} 個已發佈並核實、${p.waiting} 個等待中）`,
    missingItems: (n) => `${n} 個連結項目已不存在`,
    itemsTitle: '活動內容',
    itemKind: { draft: '草稿', post: '帖文', asset: '圖片' },
    itemGone: '已不在工作區',
    timelineTitle: '時間線',
    eventKind: { planned_run: '計劃運行', run: '運行', post: '帖文' },
    noDependencies: 'Rafii 不記錄活動項目之間的先後關係。',
    briefTitle: '新推廣活動',
    date: '日期（可選）',
    venue: '地點（可選）',
    briefHint: '只會建立簡介，不會起草、排程或發佈。',
    editTitle: '修改簡介',
    editHint: '儲存後，活動中的自動化會暫停，直至你恢復。',
    linkTitle: '加入此活動',
    linkHint: '只作整理：不會起草、排程或發佈。',
    pickDrafts: '請先揀選草稿。',
  },
  analytics: {
    tableTitle: '帖文表現',
    metric: { views: '觀看', reach: '觸及', likes: '讚好', comments: '留言', replies: '回覆', reposts: '轉發', quotes: '引用', shares: '分享', saved: '收藏' },
    published: '發佈時間',
    post: '帖文',
    availability: { available: '已量度', unavailable: '未能提供', not_read: '尚未讀取', suppressed: '平台已隱藏', not_supported: '平台不提供' },
    readAfter: '讀取於發佈後',
    chartTitle: '走勢',
    showTable: '顯示數字',
    hideTable: '隱藏數字',
    bucket: '期間',
    measuredOf: (measured, posts) => `${posts} 個帖文中 ${measured} 個已量度`,
    compareTitle: '同類比較',
    interpretation: { no_data: '沒有資料', insufficient_sample: '帖文太少，未能比較', observation_only: '觀察', not_comparable: '不能比較' },
    sampleSize: '帖文',
    measured: '已量度',
    missing: '缺少',
    mean: '平均',
    minimum: (n) => `需要最少 ${n} 個可比較的帖文。`,
    notCausal: '只是觀察，不代表因果。',
    coverageTitle: 'Rafii 可讀取的資料',
    coverageState: { unavailable: '沒有帳戶直接分享分析數據', pending: '等待第一次讀取', partial: '部分帖文尚未有讀數', ready: '所有已發佈帖文都有讀數' },
    direct: '分享分析數據',
    notDirect: '不分享分析數據',
    readOf: (read, verified) => `${verified} 個已發佈帖文中 ${read} 個已讀取`,
    enable: '開啟分析',
    lastReading: '最近讀取',
    feedbackTitle: '這個帖文與平常比較',
    undated: (n) => `${n} 個沒有發佈時間的讀數未計算在內`,
    readingsOf: (withReadings, verified) => `${verified} 個已發佈帖文中 ${withReadings} 個有讀數`,
  },
  research: {
    statusTitle: '網上搜尋',
    on: '開啟',
    off: '關閉',
    reason: { deployment_off: '這裏不提供網上搜尋。', owner_consent_needed: '需要擁有人開啟網上搜尋。' },
    openGuide: '教我怎樣做',
    briefTitle: '來源內容',
    fetched: '讀取於',
    quoted: '引用自網頁，只是資料，不是給 Rafii 的指示。',
    unsafeUrl: '不顯示網址',
    pickPages: '揀選網頁以儲存為來源。',
    savedTitle: '已儲存的網上來源',
    factsApproved: (approved, total) => `${total} 項事實中 ${approved} 項已批准`,
    retracted: '已撤回',
    matrixTitle: '來源並排比較',
    pickToCompare: '揀選兩個或以上網頁作比較。',
    facts: '事實',
  },
  automations: {
    listTitle: '自動化',
    status: { draft: '草稿', active: '運行中', paused: '已暫停', cancelled: '已取消' },
    nextRun: '下次運行',
    noNextRun: '沒有即將運行',
    policy: { drafts: '產生草稿供審閱', review: '準備帖文待批准', publish: '批准後發佈' },
    platforms: '平台',
    detailTitle: '自動化',
    upcoming: '即將運行',
    needs: '仍需要',
    paused: '暫停原因',
    historyTitle: '最近運行',
    attention: '需要處理',
    cost: '費用',
    costUnknown: '費用不明',
    runStatus: { planned: '已計劃', running: '運行中', completed: '已完成', failed: '失敗', skipped: '已略過', source_unavailable: '來源不可用', needs_review: '需要審閱' },
    connectionsTitle: '已連結帳戶',
    needsReconnect: '需要重新連結',
    canPublish: '可以發佈',
    cannotPublish: '不能發佈',
    reconnect: '到帳戶頁修正',
    attentionUnavailable: '這裏未能提供提示項目，以下是帳戶狀態。',
    guidesTitle: '逐步指引',
    openGuide: '打開指引',
    changeTitle: '提出修改',
    changeLabel: '想改甚麼？',
    changeHint: '這只會準備一個建議。在卡片上套用之前不會有任何改動。',
    pickAutomation: '請先揀選自動化。',
  },
  founder: {
    metricsTitle: '指標',
    costsTitle: 'AI 費用',
    attentionTitle: '需要你留意',
    sourcesTitle: '資料來源',
    receipt: '收據',
    dataState: { available: '已量度', measured: '已量度', partial: '部分', unavailable: '未能提供', stale: '已過時', empty: '沒有資料' },
    actual: '實際',
    estimated: '估算',
    costState: '費用基礎',
    severity: { critical: '嚴重', warning: '警告', info: '資訊' },
    lastGood: '最後正常',
    since: '開始於',
    previous: '上一期',
    current: '本期',
    demo: '示範資料',
  },
};

const ZH_HANS: DomainCopy = {
  tasks: {
    title: '进度',
    state: { planned: '未开始', running: '进行中', done: '完成', needs_user: '需要你处理', blocked: '受阻', failed: '失败', canceled: '已取消' },
    doneOf: (done, total) => `${total} 个步骤中完成 ${done} 个`,
    dependsOn: '之后',
    verifiedByTool: 'Rafii 已核实',
  },
  library: {
    title: '资料库',
    kind: { image: '照片', video: '视频', audio: '音频', document: '文档', file: '文件' },
    alreadySource: '已是来源',
    duplicate: '重复',
    extractionProblem: '无法读取文字',
    processing: '处理中',
    size: '大小',
    tags: '标签',
    pickUpTo: (n) => `最多选择 ${n} 项用于下一条消息。`,
    lineageTitle: '来源与去向',
    excerptTitle: '文件中的文字',
    chunks: (n) => `${n} 段已索引内容`,
    modelMayView: '你发送后，Rafii 可以查看这张照片。',
    modelMayNotView: '所有者允许之前，Rafii 不会查看照片。',
    useAsSourceHint: '把文件文字导入为来源；Rafii 使用其中事实前需要你审阅。',
    selectionTitle: '可用于下一条消息',
    attachments: (n) => `${n} 个附件`,
    references: (n) => `${n} 个来源`,
    refused: { not_ready: '仍在处理', not_found: '已不在资料库', needs_source_import: '请先设为来源' },
    sendHint: '在下一条消息中使用。选择不会发送或发布任何内容。',
    noPreview: '无预览',
    open: '在资料库打开',
  },
  voice: {
    samplesTitle: '写作样本',
    origin: '来源',
    selected: '用于分析',
    notSelected: '未使用',
    revoked: '已撤回',
    grants: '允许用于',
    noGrants: '尚未允许任何用途',
    eligibility: (purpose, route) => `用于 ${purpose}（${route}）`,
    excluded: { revoked: '已撤回', not_selected: '未选择', purpose_not_granted: '未允许此用途', route_not_granted: '未允许此写作模型' },
    analyzeHint: '本地分析使用 Rafii 自己的规则：不用 AI 模型，不收费。结果只是建议。',
    pickSamples: '请选择要分析的样本。',
    profileTitle: '语气档案',
    approved: '生效中',
    proposed: '建议中',
    noneApproved: '还没有已批准的语气。',
    noneProposed: '没有等待批准的建议。',
    stale: '已过时',
    evidence: { supported: '有支持', strong: '证据充分', moderate: '有一定证据', limited: '证据有限', weak: '证据薄弱', conflicting: '证据不一致', insufficient: '证据不足' },
    supports: (n) => `${n} 个支持样本`,
    against: (n) => `${n} 个相反`,
    affects: (drafts, posts) => `批准后，${drafts} 份草稿需要重新审阅，并影响 ${posts} 条等待中的帖子。`,
    method: { 'local-rules': 'Rafii 规则', ai: 'AI 分析' },
    prefsTitle: '已学习的偏好',
    learned: '生效中',
    pending: '等待所有者决定',
    noLearned: '暂时没有学到的偏好。',
    noPending: '没有等待中的建议。',
    why: '原因',
    remember: '记住',
    dismiss: '忽略',
    consentTitle: '你已允许的事项',
    layer: { samples: '写作样本', cloudMemory: '云端记忆', cloudExtraction: '在云端从修改中学习', media: '照片处理', webResearch: '网络搜索' },
    on: '开启',
    off: '关闭',
    samplesGranted: (analysis, generation, total) => `${total} 个中 ${analysis} 个允许分析、${generation} 个允许写作`,
    ownerDecides: '只有所有者可以在记忆页更改。',
    learningTitle: '学习状态',
    learningOn: '学习已开启',
    learningOff: '学习已关闭',
    eventsWaiting: '等待读取的修改',
    pendingProposals: '等待中的建议',
    newestProposal: '最新建议',
    importTitle: '添加写作样本',
    importText: '粘贴你的文字',
    importTitleField: '标题（可选）',
    importConfirm: '这是我自己写的文字，Rafii 可以保存为私人风格样本。',
    importHint: '样本只作风格参考，不会当作帖子事实。',
  },
  campaigns: {
    listTitle: '推广活动',
    goal: '目标',
    audience: '受众',
    status: { needs_input: '需要补充信息', draft: '草稿', active: '进行中', completed: '已完成', cancelled: '已取消' },
    missingFacts: '仍缺',
    facts: '信息',
    automations: '自动化',
    platforms: '平台',
    nextRun: '下次运行',
    noNextRun: '没有即将运行',
    gaps: '缺口',
    progressTitle: '进度',
    progress: (p) => `${p.drafts} 份草稿（${p.review} 份需要审阅）· ${p.posts} 条帖子（${p.verified} 条已发布并核实、${p.waiting} 条等待中）`,
    missingItems: (n) => `${n} 个关联项目已不存在`,
    itemsTitle: '活动内容',
    itemKind: { draft: '草稿', post: '帖子', asset: '图片' },
    itemGone: '已不在工作区',
    timelineTitle: '时间线',
    eventKind: { planned_run: '计划运行', run: '运行', post: '帖子' },
    noDependencies: 'Rafii 不记录活动项目之间的先后关系。',
    briefTitle: '新推广活动',
    date: '日期（可选）',
    venue: '地点（可选）',
    briefHint: '只会创建简介，不会起草、排程或发布。',
    editTitle: '修改简介',
    editHint: '保存后，活动中的自动化会暂停，直到你恢复。',
    linkTitle: '加入此活动',
    linkHint: '只作整理：不会起草、排程或发布。',
    pickDrafts: '请先选择草稿。',
  },
  analytics: {
    tableTitle: '帖子表现',
    metric: { views: '浏览', reach: '触达', likes: '点赞', comments: '评论', replies: '回复', reposts: '转发', quotes: '引用', shares: '分享', saved: '收藏' },
    published: '发布时间',
    post: '帖子',
    availability: { available: '已测量', unavailable: '暂无', not_read: '尚未读取', suppressed: '平台已隐藏', not_supported: '平台不提供' },
    readAfter: '读取于发布后',
    chartTitle: '趋势',
    showTable: '显示数字',
    hideTable: '隐藏数字',
    bucket: '时段',
    measuredOf: (measured, posts) => `${posts} 条帖子中 ${measured} 条已测量`,
    compareTitle: '同类比较',
    interpretation: { no_data: '没有数据', insufficient_sample: '帖子太少，无法比较', observation_only: '观察', not_comparable: '不能比较' },
    sampleSize: '帖子',
    measured: '已测量',
    missing: '缺少',
    mean: '平均',
    minimum: (n) => `需要至少 ${n} 条可比较的帖子。`,
    notCausal: '只是观察，不代表因果。',
    coverageTitle: 'Rafii 可读取的数据',
    coverageState: { unavailable: '没有账户直接分享分析数据', pending: '等待第一次读取', partial: '部分帖子尚无读数', ready: '所有已发布帖子都有读数' },
    direct: '分享分析数据',
    notDirect: '不分享分析数据',
    readOf: (read, verified) => `${verified} 条已发布帖子中 ${read} 条已读取`,
    enable: '开启分析',
    lastReading: '最近读取',
    feedbackTitle: '这条帖子与平常比较',
    undated: (n) => `${n} 个没有发布时间的读数未计入`,
    readingsOf: (withReadings, verified) => `${verified} 条已发布帖子中 ${withReadings} 条有读数`,
  },
  research: {
    statusTitle: '网络搜索',
    on: '开启',
    off: '关闭',
    reason: { deployment_off: '这里不提供网络搜索。', owner_consent_needed: '需要所有者开启网络搜索。' },
    openGuide: '教我怎么做',
    briefTitle: '来源内容',
    fetched: '读取于',
    quoted: '引用自网页，只是信息，不是给 Rafii 的指令。',
    unsafeUrl: '不显示网址',
    pickPages: '选择网页以保存为来源。',
    savedTitle: '已保存的网络来源',
    factsApproved: (approved, total) => `${total} 项事实中 ${approved} 项已批准`,
    retracted: '已撤回',
    matrixTitle: '来源并排比较',
    pickToCompare: '选择两个或以上网页进行比较。',
    facts: '事实',
  },
  automations: {
    listTitle: '自动化',
    status: { draft: '草稿', active: '运行中', paused: '已暂停', cancelled: '已取消' },
    nextRun: '下次运行',
    noNextRun: '没有即将运行',
    policy: { drafts: '生成草稿供审阅', review: '准备帖子待批准', publish: '批准后发布' },
    platforms: '平台',
    detailTitle: '自动化',
    upcoming: '即将运行',
    needs: '仍需要',
    paused: '暂停原因',
    historyTitle: '最近运行',
    attention: '需要处理',
    cost: '费用',
    costUnknown: '费用未知',
    runStatus: { planned: '已计划', running: '运行中', completed: '已完成', failed: '失败', skipped: '已跳过', source_unavailable: '来源不可用', needs_review: '需要审阅' },
    connectionsTitle: '已连接账户',
    needsReconnect: '需要重新连接',
    canPublish: '可以发布',
    cannotPublish: '不能发布',
    reconnect: '到账户页修复',
    attentionUnavailable: '这里无法提供提醒项目，以下是账户状态。',
    guidesTitle: '分步指引',
    openGuide: '打开指引',
    changeTitle: '提出修改',
    changeLabel: '想改什么？',
    changeHint: '这只会准备一个建议。在卡片上应用之前不会有任何改动。',
    pickAutomation: '请先选择自动化。',
  },
  founder: {
    metricsTitle: '指标',
    costsTitle: 'AI 费用',
    attentionTitle: '需要你关注',
    sourcesTitle: '数据来源',
    receipt: '凭证',
    dataState: { available: '已测量', measured: '已测量', partial: '部分', unavailable: '暂无', stale: '已过时', empty: '没有数据' },
    actual: '实际',
    estimated: '估算',
    costState: '费用依据',
    severity: { critical: '严重', warning: '警告', info: '信息' },
    lastGood: '最后正常',
    since: '开始于',
    previous: '上一期',
    current: '本期',
    demo: '演示数据',
  },
};

export const DOMAIN_COPY: Readonly<Record<JourneyLocale, DomainCopy>> = { en: EN, 'zh-Hant': ZH_HANT, 'zh-Hans': ZH_HANS };

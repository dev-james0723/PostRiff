/**
 * Words for the Pricing v2 parts of Usage & plan and the work surfaces (managed credits, Free preview, v2 plan
 * cards), in English and Traditional Chinese. Legacy allowance copy stays where it always was; nothing here mentions
 * writing batches. Pure and import-free so `node --test` can load it. Numbers and dates arrive already formatted.
 *
 * The app's own copy is English. A person who saved a Traditional Chinese language on their profile gets these
 * strings in Traditional Chinese (`useCopyLocale`); everyone else reads English.
 */

export type CopyLocale = 'en' | 'zh-Hant';

/** zh-Hant, zh-TW, zh-HK, zh-MO and Cantonese read Traditional Chinese; every other tag reads English. */
export function copyLocale(tag: string | null | undefined): CopyLocale {
  const value = (tag ?? '').trim().toLowerCase();
  return /^(?:zh-(?:hant|tw|hk|mo)(?:$|-)|yue(?:$|-))/.test(value) ? 'zh-Hant' : 'en';
}

const en = {
  creditMeter: {
    title: 'Managed credits',
    aboutLabel: 'About managed credits',
    howItWorks: 'Each task shows its credit limit before it runs. Rafii holds that limit, charges what the task used and returns the rest; a failed task uses none.',
    left: (n: string, total: string) => `${n} left of ${total}`,
    available: (n: string) => `${n} available`,
    barLabel: 'Managed credits left this period',
    barValue: (n: string, total: string) => `${n} credits left of ${total}`,
    held: (n: string) => `${n} held for tasks in progress`,
    resets: (date: string) => `Resets ${date}`,
    expiring: (n: string, date: string) => `${n} credits expire ${date}. Unused credits don’t roll over.`,
    totalUnknown: 'This period’s total isn’t on record yet.',
    planIncludes: (n: string) => `Your plan includes ${n} each billing period.`,
    aboveGrant: 'Includes credits from outside this period’s grant.',
    debt: (n: string) => `Billing adjustment pending: ${n} credits. New paid tasks are paused.`,
    unavailable: 'Credit balance unavailable',
    unavailableHint: 'Paid tasks wait until it can be read. Nothing is charged meanwhile.',
    noSilentOverage: 'No silent overage: paid work stops at your limit.'
  },
  costGuard: {
    title: 'AI cost guard',
    ownerOnly: 'Owner only',
    hint: 'What AI work cost Rafii this month, against the workspace’s safety limit. Separate from your credits.'
  },
  freePreview: {
    title: 'Free preview',
    postDoctor: 'Post Doctor check',
    genome: (n: string) => `Recent-post analysis (up to ${n} posts)`,
    genomeNoMax: 'Recent-post analysis',
    left: (n: string) => `${n} left`,
    ready: 'Ready',
    used: 'Used',
    reasons: {
      plan_unavailable: 'Not on this plan',
      permission_required: 'Needs edit access',
      feature_disabled: 'Not available yet',
      consent_required: 'Needs your consent first',
      funding_unavailable: 'Paused for now',
      rate_limited: 'Busy today — try tomorrow',
      unknown: 'Unavailable'
    },
    unavailable: 'Preview status unavailable',
    note: 'Free has no monthly credits, so nothing is charged. Drafts, edits and exports stay available.'
  },
  plans: {
    heading: 'Plans',
    ownerOnly: 'Only the owner can change plans.',
    current: 'Current',
    notIncluded: 'Not included',
    managedCredits: 'Managed credits each month',
    firstLook: 'Included once',
    firstLookValue: (posts: string) => `1 Post Doctor check · 1 analysis of up to ${posts} recent posts`,
    none: 'None',
    connectedAccounts: 'Connected accounts',
    brands: 'Brands',
    seats: 'Seats',
    perMonth: '/ month',
    ownerSeesPrice: 'The owner sees this workspace’s price.',
    choose: (label: string) => `Choose ${label}`,
    opening: 'Opening checkout…',
    tryAgain: 'Try again',
    stripeNote: 'Checkout by Stripe. Nothing is charged until you confirm.',
    notOpen: 'Checkout isn’t open yet.',
    creditsOff: (label: string) => `${label} can’t be bought yet: managed credits aren’t switched on here.`,
    noSilentOverage: 'Stops at your limit — no silent overage.'
  },
  summary: {
    freeTitle: 'Free',
    freeLine: 'Nothing is charged on Free.',
    ended: (label: string, date: string) => `${label} ended ${date}`,
    seeCreator: 'See Creator',
    seePlans: 'See plans',
    legacyBadge: 'Legacy plan',
    legacyNote: 'Kept for you: your price and allowances stay as they are.',
    legacyEndedNote: 'Legacy plans aren’t offered again. Your drafts and exports stay available.',
    legacyEndedChoose: 'Legacy plans aren’t offered again. Choose Creator below to keep using managed AI work; your drafts stay.'
  },
  planSummary: {
    trial: 'Trial',
    planUnavailable: 'Plan unavailable',
    daysLeft: (n: string) => `${n} left`,
    day: (n: number): string => (n === 1 ? 'day' : 'days'),
    publishingPaused: 'Publishing is paused',
    renews: (date: string) => `Renews ${date}`,
    ends: (date: string) => `Ends ${date} · won’t renew`,
    endsExact: (date: string) => `Ends ${date}`,
    endedExact: (date: string) => `Ended ${date}`,
    ended: (date: string) => `Ended ${date}`,
    endedNoDate: 'Ended',
    updatePaymentBy: (date: string) => `Update payment by ${date}`,
    updatePaymentMethod: 'Update your payment method',
    manage: 'Manage plan',
    choose: 'Choose a plan',
    updatePayment: 'Update payment',
    badgeEnded: 'Ended',
    badgePaymentFailed: 'Payment failed',
    statuses: { trial: 'Trial', active: 'Active', past_due: 'Payment failed', grace: 'Payment failed', cancelled: 'Cancelled', expired: 'Expired' } as Record<string, string>,
    statusUnavailable: 'Status unavailable',
    proposedPrice: 'proposed price',
    details: 'Details',
    opening: 'Opening…',
    tryAgain: 'Try again'
  },
  work: {
    creditsLeft: (n: string) => `${n} credits left`,
    creditsUnavailable: 'Credits unavailable',
    freeNoManaged: 'Managed AI writing isn’t included on Free',
    quoteLine: 'Each run shows its credit limit first; failed runs use none.',
    ideasCostCredits: (n: string) => `${n} credits left. Cloud drafts show their credit limit before they run; saving sources is free.`,
    ideasCostCreditsResets: (n: string, date: string) => `${n} credits left, resets ${date}. Cloud drafts show their credit limit before they run; saving sources is free.`,
    ideasCostFree: 'Saving sources is free. Free includes no managed AI writing; a writer on your own CLI subscription still works.',
    ideasCostUnavailable: 'Usage unavailable. Saving sources is free.',
    reminderCreditsOut: 'No managed credits left',
    reminderCreditsOutBody: (date: string) => `Resets ${date}. Paid drafts wait until then; nothing extra is charged.`,
    reminderCreditsOutNoDate: 'Paid drafts wait until more are available; nothing extra is charged.',
    reminderAction: 'Usage & plan'
  },
  attention: {
    creditsOutTitle: 'Managed credits used up',
    creditsOutBody: (when: string) => `Paid tasks pause until they reset ${when}; nothing extra is charged.`,
    creditsOutBodyNoDate: 'Paid tasks pause until more are available; nothing extra is charged.',
    creditsLowTitle: (n: string) => `${n} managed credits left`,
    creditsLowBody: 'Paid tasks stop when they run out; nothing extra is charged.',
    debtTitle: 'Billing adjustment pending',
    debtBody: (n: string) => `${n} credits are owed after a refund or dispute. New paid tasks are paused.`,
    action: 'See plan'
  },
  costClass: {
    creditsBadge: 'Managed credits',
    creditsLine: 'Each run shows its credit limit before it starts; Rafii charges what it used and returns the rest. Failed runs use no credits.',
    freeBadge: 'Creator plan',
    freeLine: 'Managed writing needs the Creator plan. Free includes no managed credits.',
    paidBadge: 'Paid model',
    paidLine: 'Uses your plan’s paid AI usage per finished run. Failed runs don’t count.'
  },
  info: {
    title: 'Billing',
    overageTitle: 'No silent overage',
    overageBodyCredits: 'When credits run out, paid work stops. You are never charged for going over.',
    overageBodyFree: 'Free has no paid usage, so nothing is ever charged.',
    creditsTitle: 'Managed credits',
    creditsBody: (perUsd: string) => `${perUsd} credits equal US$1 of a task’s verified AI and tool cost, rounded once per task. Credits reset each billing period and don’t roll over.`,
    freeTitle: 'Free preview',
    freeBody: 'One Post Doctor check and one recent-post analysis, on us. Choose Creator when you want managed AI work every month.',
    cancelTitle: 'Cancelling',
    cancelBody: 'Creator runs to the end of the paid period, then the workspace returns to Free. Drafts stay available to read and export.',
    guide: 'Usage & billing guide'
  }
};

export type BillingCopy = typeof en;

const zhHant: BillingCopy = {
  creditMeter: {
    title: '代管點數',
    aboutLabel: '關於代管點數',
    howItWorks: '每項工作執行前會先顯示點數上限。Rafii 先暫扣該上限，按實際用量扣點並退回其餘點數；失敗的工作不扣點。',
    left: (n, total) => `剩餘 ${n} / ${total}`,
    available: (n) => `可用 ${n} 點`,
    barLabel: '本期剩餘代管點數',
    barValue: (n, total) => `剩餘 ${n} / ${total} 點`,
    held: (n) => `${n} 點暫扣給進行中的工作`,
    resets: (date) => `${date} 重設`,
    expiring: (n, date) => `${n} 點將於 ${date} 到期，未用完的點數不會累積到下期。`,
    totalUnknown: '本期總額尚未入帳。',
    planIncludes: (n) => `你的方案每個計費週期包含 ${n} 點。`,
    aboveGrant: '包含本期配額以外的點數。',
    debt: (n) => `帳務調整待處理：${n} 點。新的付費工作已暫停。`,
    unavailable: '無法讀取點數餘額',
    unavailableHint: '恢復讀取前，付費工作會先等待；期間不會收費。',
    noSilentOverage: '不會悄悄超額收費：額度用完，付費工作即停止。'
  },
  costGuard: {
    title: 'AI 成本保護',
    ownerOnly: '僅擁有者可見',
    hint: 'Rafii 本月 AI 工作的實際成本與工作區安全上限，與你的點數分開計算。'
  },
  freePreview: {
    title: '免費預覽',
    postDoctor: 'Post Doctor 檢查',
    genome: (n) => `近期貼文分析（最多 ${n} 篇）`,
    genomeNoMax: '近期貼文分析',
    left: (n) => `剩 ${n} 次`,
    ready: '可使用',
    used: '已使用',
    reasons: {
      plan_unavailable: '目前方案不提供',
      permission_required: '需要編輯權限',
      feature_disabled: '尚未開放',
      consent_required: '需先取得你的同意',
      funding_unavailable: '暫時停用',
      rate_limited: '今日名額已滿，請明天再試',
      unknown: '無法使用'
    },
    unavailable: '無法讀取預覽狀態',
    note: 'Free 方案沒有每月點數，因此不會收費。草稿、編輯與匯出照常可用。'
  },
  plans: {
    heading: '方案',
    ownerOnly: '只有擁有者可以更改方案。',
    current: '目前方案',
    notIncluded: '不包含',
    managedCredits: '每月代管點數',
    firstLook: '一次性提供',
    firstLookValue: (posts) => `1 次 Post Doctor 檢查 · 1 次近期貼文分析（最多 ${posts} 篇）`,
    none: '無',
    connectedAccounts: '連結帳號',
    brands: '品牌',
    seats: '席位',
    perMonth: '／月',
    ownerSeesPrice: '價格只向工作區擁有者顯示。',
    choose: (label) => `選擇 ${label}`,
    opening: '正在開啟結帳…',
    tryAgain: '再試一次',
    stripeNote: '由 Stripe 處理結帳。你確認之前不會收費。',
    notOpen: '尚未開放結帳。',
    creditsOff: (label) => `暫時無法購買 ${label}：這裡尚未啟用代管點數。`,
    noSilentOverage: '用完即停，不會悄悄超額收費。'
  },
  summary: {
    freeTitle: 'Free 方案',
    freeLine: 'Free 方案不會收費。',
    ended: (label, date) => `${label} 已於 ${date} 結束`,
    seeCreator: '查看 Creator',
    seePlans: '查看方案',
    legacyBadge: '舊方案',
    legacyNote: '為你保留：價格與額度維持不變。',
    legacyEndedNote: '舊方案不再提供。你的草稿與匯出仍可使用。',
    legacyEndedChoose: '舊方案不再提供。在下方選擇 Creator，即可繼續使用代管 AI 工作；草稿會保留。'
  },
  planSummary: {
    trial: '試用',
    planUnavailable: '無法讀取方案',
    daysLeft: (n) => `剩餘 ${n}`,
    day: () => '天',
    publishingPaused: '發佈已暫停',
    renews: (date) => `${date} 續訂`,
    ends: (date) => `${date} 結束 · 不會續訂`,
    endsExact: (date) => `${date} 結束`,
    endedExact: (date) => `已於 ${date} 結束`,
    ended: (date) => `已於 ${date} 結束`,
    endedNoDate: '已結束',
    updatePaymentBy: (date) => `請在 ${date} 前更新付款資料`,
    updatePaymentMethod: '請更新付款方式',
    manage: '管理方案',
    choose: '選擇方案',
    updatePayment: '更新付款資料',
    badgeEnded: '已結束',
    badgePaymentFailed: '付款失敗',
    statuses: { trial: '試用', active: '使用中', past_due: '付款失敗', grace: '付款失敗', cancelled: '已取消', expired: '已到期' },
    statusUnavailable: '無法讀取狀態',
    proposedPrice: '建議價格',
    details: '詳情',
    opening: '正在開啟…',
    tryAgain: '再試一次'
  },
  work: {
    creditsLeft: (n) => `剩餘 ${n} 點`,
    creditsUnavailable: '無法讀取點數',
    freeNoManaged: 'Free 方案不含代管 AI 寫作',
    quoteLine: '每次執行前先顯示點數上限；失敗不扣點。',
    ideasCostCredits: (n) => `剩餘 ${n} 點。雲端草稿執行前會先顯示點數上限；儲存素材免費。`,
    ideasCostCreditsResets: (n, date) => `剩餘 ${n} 點，${date} 重設。雲端草稿執行前會先顯示點數上限；儲存素材免費。`,
    ideasCostFree: '儲存素材免費。Free 方案不含代管 AI 寫作；使用你自己 CLI 訂閱的寫作工具仍可使用。',
    ideasCostUnavailable: '無法讀取用量。儲存素材免費。',
    reminderCreditsOut: '代管點數已用完',
    reminderCreditsOutBody: (date) => `${date} 重設。付費草稿會等到那時；不會額外收費。`,
    reminderCreditsOutNoDate: '付費草稿會等到有可用點數；不會額外收費。',
    reminderAction: '用量與方案'
  },
  attention: {
    creditsOutTitle: '代管點數已用完',
    creditsOutBody: (when) => `付費工作暫停至點數 ${when} 重設；不會額外收費。`,
    creditsOutBodyNoDate: '付費工作暫停至有可用點數；不會額外收費。',
    creditsLowTitle: (n) => `剩餘 ${n} 代管點數`,
    creditsLowBody: '點數用完時付費工作會停止；不會額外收費。',
    debtTitle: '帳務調整待處理',
    debtBody: (n) => `因退款或爭議，尚欠 ${n} 點。新的付費工作已暫停。`,
    action: '查看方案'
  },
  costClass: {
    creditsBadge: '代管點數',
    creditsLine: '每次執行前會先顯示點數上限；Rafii 按實際用量扣點並退回其餘點數。失敗的執行不扣點。',
    freeBadge: 'Creator 方案',
    freeLine: '代管寫作需要 Creator 方案。Free 方案不含代管點數。',
    paidBadge: '付費模型',
    paidLine: '每次完成的執行會使用方案的付費 AI 用量；失敗不計。'
  },
  info: {
    title: '帳單',
    overageTitle: '不會悄悄超額收費',
    overageBodyCredits: '點數用完時，付費工作會停止。超出部分永不收費。',
    overageBodyFree: 'Free 方案沒有付費用量，因此不會收費。',
    creditsTitle: '代管點數',
    creditsBody: (perUsd) => `${perUsd} 點等於一項工作經核實的 AI 與工具成本 1 美元，每項工作只進位一次。點數每個計費週期重設，不會累積到下期。`,
    freeTitle: '免費預覽',
    freeBody: '一次 Post Doctor 檢查與一次近期貼文分析，由 Rafii 負擔。想每月使用代管 AI 工作時，再選擇 Creator。',
    cancelTitle: '取消訂閱',
    cancelBody: 'Creator 會持續到已付費期間結束，之後工作區回到 Free 方案。草稿仍可閱讀與匯出。',
    guide: '用量與帳單指南'
  }
};

export const BILLING_COPY: Record<CopyLocale, BillingCopy> = { en, 'zh-Hant': zhHant };

export function billingCopy(locale: CopyLocale = 'en'): BillingCopy {
  return BILLING_COPY[locale];
}

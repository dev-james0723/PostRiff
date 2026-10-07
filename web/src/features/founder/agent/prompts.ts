/**
 * Suggested questions for Founder Rafii, by section (PRD §6.4's seven example questions and their Cantonese forms).
 * Each one maps to founder tools on the server; the panel only offers the words.
 */
const GENERAL = ['What changed since yesterday, and what needs me first?', '整理今日最需要我處理的三件事。', 'Which sources are stale right now, and what could that be hiding?'];

const BY_SECTION: Record<string, string[]> = {
  overview: GENERAL,
  customers: ['哪些客戶快用完額度？', 'Which customers are high value but inactive for 30 days?', 'Draft a payment reminder for me to review first.', '邊個客戶嘅 AI 成本最高？'],
  revenue: ['Explain this month’s MRR bridge: what drove the change?', '邊啲付款失敗咗，影響幾多收入？', 'How much cash was collected this month versus last?', 'Draft a payment reminder for me to review first.'],
  product: ['這張 retention 圖真正代表什麼？', 'Where do new workspaces stall in activation?', 'Which features are reused after the first week?'],
  'ai-cost': ['今個月 AI 成本為甚麼上升？', '哪個 plan 的使用成本最高？', 'How much of this month’s cost is still unknown, and why?', 'Which feature costs the most per useful result?'],
  operations: ['今日發布失敗影響了誰？', 'Which incident is open, and who is affected?', 'Is the cron heartbeat healthy in this environment?'],
  support: ['What is the oldest open request, and which workspace sent it?', '邊啲問題重複出現？', 'How many data requests are waiting?'],
  settings: ['What does my contact policy allow right now?', 'When is the next briefing scheduled?', '而家會唔會真係打電話畀我？'],
  advanced: ['Explain the receipt I have open.', 'Which security events happened this week?', 'Which source last reported, and when?']
};

export function suggestedPrompts(section: string, limit = 4): string[] {
  return (BY_SECTION[section] ?? GENERAL).slice(0, limit);
}

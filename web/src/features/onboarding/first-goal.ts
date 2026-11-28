export const firstGoals = {
  caption: { label: 'Write a caption', href: '/app?first=caption', match: /\b(captions?|posts?|teasers?)\b/i },
  campaign: { label: 'Draft a campaign post', href: '/app?first=campaign', match: /\b(campaigns?|launch plan|messaging strategy)\b/i },
  video: { label: 'Plan a video', href: '/app/creative', match: /\b(videos?|reels?|storyboards?|footage)\b/i },
  calendar: { label: 'See my calendar', href: '/app/calendar', match: /\b(calendar|scheduled posts?)\b/i }
};
export type FirstGoal = keyof typeof firstGoals;
export const goalIds = Object.keys(firstGoals) as FirstGoal[];

// Suggest a destination only. A phrase with competing goals still gets a choice.
export function matchGoal(brief: string, canEdit: boolean): FirstGoal | null {
  // Count each compound phrase once, leaving other requests in the brief intact.
  const goals = brief.replace(/\bcampaign\s+posts?\b/gi, 'campaign')
    .replace(/\bscheduled\s+posts?\b/gi, 'calendar');
  const matches = goalIds.filter(goal => (canEdit || goal === 'calendar') && firstGoals[goal].match.test(goals));
  return matches.length === 1 ? matches[0] : null;
}

// Carry a brief across client-side navigation in this tab. Only the opaque ticket goes in history.
let pending: { id: string; owner: string; workspace: string; goal: FirstGoal; brief: string; expires: number } | null = null;

export function firstGoalLink(goal: FirstGoal, text: string, owner: string, workspace: string): string {
  const href = firstGoals[goal].href;
  pending = null;
  const brief = text.trim().slice(0, 1200);
  if (!owner || !workspace || !brief || goal === 'calendar') return href;
  const id = crypto.randomUUID();
  pending = { id, owner, workspace, goal, brief, expires: Date.now() + 300_000 };
  return href + (href.includes('?') ? '&' : '?') + 'briefTicket=' + id;
}

export function takeFirstBrief(id: string | null, goal: FirstGoal | null, owner: string, workspace: string): string | null {
  if (!pending || !id || pending.id !== id) return null;
  const item = pending;
  pending = null;
  return item.goal === goal && item.owner === owner && item.workspace === workspace && item.expires > Date.now()
    ? item.brief : null;
}

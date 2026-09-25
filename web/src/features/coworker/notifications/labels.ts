/** Plain names for notification events and categories (catalog: src/postriff_phase2/notifications/catalog.py). */

export const EVENT_LABELS: Record<string, string> = {
  'campaign.week_ready': 'Next week is ready for review',
  'campaign.drafts_ready': 'Drafts are ready',
  'campaign.approval_required': 'A post needs approval',
  'campaign.blocked': 'Rafii needs you to continue',
  'research.needs_input': 'Research needs your input',
  'asset.review_required': 'An image needs review',
  'publish.scheduled': 'A post is scheduled',
  'publish.verified': 'A post was published',
  'publish.failed': 'A post did not publish',
  'publish.uncertain': 'A post may not have gone out',
  'automation.completed': 'An automation finished',
  'automation.failed': 'An automation failed',
  'channel.reconnect_required': 'An account needs reconnecting',
  'engagement.needs_attention': 'A comment needs a reply',
  'opportunity.detected': 'A new opportunity',
  'analytics.weekly_ready': 'Your weekly results are ready',
  'analytics.anomaly_detected': 'Unusual results',
  'learning.preference_proposed': 'Rafii noticed a preference',
  'budget.threshold_reached': 'A budget limit was reached',
  'billing.payment_failed': 'A payment failed',
  'billing.trial_ending': 'Your trial is ending',
  'billing.subscription_active': 'Your plan is active',
  'security.new_device': 'New sign-in',
  'security.account_change': 'Account change'
};

export const CATEGORY_LABELS: Record<string, { label: string; hint: string }> = {
  approvals: { label: 'Approvals', hint: 'A post needs someone to approve it.' },
  publishing: { label: 'Publishing', hint: 'A post failed, may not have gone out, or was published.' },
  weekly: { label: 'Weekly review', hint: 'Next week is drafted and ready for you.' },
  campaigns: { label: 'Campaigns', hint: 'Drafts are ready or Rafii needs a decision.' },
  automation: { label: 'Automations', hint: 'An automation finished or failed.' },
  channels: { label: 'Accounts', hint: 'An account needs reconnecting.' },
  engagement: { label: 'Comments and mentions', hint: 'Someone asked a question or needs an answer.' },
  opportunities: { label: 'Opportunities', hint: 'Something fresh from a topic you follow.' },
  analytics: { label: 'Results', hint: 'Weekly results and unusual changes.' },
  learning: { label: 'Learned preferences', hint: 'Rafii noticed a pattern in your edits.' },
  research: { label: 'Research', hint: 'Research needs your input.' },
  assets: { label: 'Images', hint: 'An image needs review.' },
  budget: { label: 'Budget', hint: 'A spending limit was reached.' },
  billing: { label: 'Billing', hint: 'Payments and trial. Emails always reach the owner.' },
  security: { label: 'Security', hint: 'New sign-ins and account changes. Emails always reach you.' }
};

export function eventLabel(type: string): string {
  return EVENT_LABELS[type] ?? type.replace(/[._]+/g, ' ').replace(/^./, (c) => c.toUpperCase());
}

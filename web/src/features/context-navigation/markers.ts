import type { NavigationItem } from '@/lib/api/types';

export const MARKER_LABELS: Record<NavigationItem['kind'], string> = {
  user_request: 'Your request', rafii_decision: 'Rafii response', approval_required: 'Needs approval',
  draft: 'Draft', media: 'Media', research: 'Research', automation: 'Automation',
  completion: 'Completed', error: 'Blocker', moment: 'Saved moment'
};

export function navigationId(item: NavigationItem): string {
  return item.momentId ?? item.messageId ?? '';
}

/** Bounded marker density while preserving every exact turn in an expandable cluster. */
export function clusterNavigation(items: NavigationItem[], maxMarkers = 36): NavigationItem[][] {
  if (!items.length) return [];
  const size = Math.max(1, Math.ceil(items.length / Math.max(1, maxMarkers)));
  const groups: NavigationItem[][] = [];
  for (let i = 0; i < items.length; i += size) groups.push(items.slice(i, i + size));
  return groups;
}

import { levelKey } from '@/components/app/level-badge';
import { CapabilityBadge } from '@/components/marketing/capability-badge';

/**
 * An API capability level (Direct / Assisted / Bridge / Unsupported) as the shared badge. The badge's own
 * hover title describes publishing, which is wrong for comments and replies, so it is dropped here; the
 * evidence next to it says what the level means. Borderless, like every resting Rafii surface (DNA §2.2).
 */
export function InboxLevelBadge({ level, label }: { level: string | undefined; label?: string }) {
  return <CapabilityBadge level={levelKey(level)} label={label} title={undefined} className='border-0' />;
}

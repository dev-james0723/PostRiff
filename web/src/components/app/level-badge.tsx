import { CapabilityBadge, type CapabilityLevel } from '@/components/marketing/capability-badge';

/** API capability level → shared badge. 'Bridge' is the API's name for the desktop companion. */
export function levelKey(level: string | undefined): CapabilityLevel {
  switch (level) {
    case 'Direct':
      return 'direct';
    case 'Assisted':
      return 'assisted';
    case 'Bridge':
      return 'local';
    default:
      return 'unsupported';
  }
}

export function LevelBadge({ level, label, size }: { level?: string; label?: string; size?: 'sm' | 'md' }) {
  return <CapabilityBadge level={levelKey(level)} label={label} size={size} />;
}

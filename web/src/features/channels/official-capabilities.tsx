'use client';

import type { OfficialCapability } from '@/lib/api/types';
import type { ConnectCapability } from '@/lib/channels/state';
import { Button } from '@/components/ui/button';

function label(key: string) {
  return key.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase());
}

function status(feature: OfficialCapability) {
  if (feature.state === 'READY') return 'Ready · live tested';
  if (feature.officialSupport === 'unsupported') return 'Official API unsupported';
  if (feature.officialSupport === 'audit_unavailable') return 'Official support needs verification';
  if (!feature.implemented) return 'Engineering pending';
  if (!feature.appApproved) return 'Platform approval unverified';
  if (!feature.granted) return 'Permission required';
  if (!feature.eligible) return 'Account eligibility unverified';
  return 'Live test pending';
}

export function OfficialCapabilities({ features, offered, onEnable }: {
  features: Record<string, OfficialCapability>;
  offered?: Record<string, boolean>;
  onEnable?: (capability: ConnectCapability) => void;
}) {
  return (
    <details className='rafii-quiet rounded-xl p-3'>
      <summary className='rafii-focus cursor-pointer text-sm'>Individual capabilities and verification</summary>
      <p className='text-muted-foreground mt-2 text-xs'>Each feature requires platform support, app approval, your permission, account eligibility, an implementation and a live test.</p>
      <ul className='mt-3 flex flex-col gap-3' aria-label='Official capabilities'>
        {Object.entries(features).map(([key, feature]) => (
          <li key={key} className='flex flex-wrap items-start justify-between gap-2 border-b border-foreground/5 pb-2 last:border-0'>
            <div className='min-w-0 flex-1'>
              <p className='text-sm'>{label(key)} <span className='text-muted-foreground text-xs'>— {status(feature)}</span></p>
              {feature.limitation && <p className='text-muted-foreground mt-1 text-xs'>{feature.limitation}</p>}
              <p className='text-muted-foreground mt-1 text-xs'>{feature.blockers.join(' · ')}</p>
            </div>
            {onEnable && offered?.[feature.permission_group] && feature.officialSupport === 'documented' && !feature.granted && (
              <Button variant='glass' size='sm' onClick={() => onEnable(feature.permission_group as ConnectCapability)}>Enable {label(feature.permission_group)}</Button>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

'use client';

import type { ChannelView, OfficialCapability } from '@/lib/api/types';
import { isVerifiedConnectionFeature, officialCapabilityStatus } from '@/lib/channels/connection-status';
import type { ConnectCapability } from '@/lib/channels/state';
import { Button } from '@/components/ui/button';

function label(key: string) {
  return key.replace(/_/g, ' ').replace(/^./, (first) => first.toUpperCase());
}

export function OfficialCapabilities({ features, readiness, offered, onEnable }: {
  features: Record<string, OfficialCapability>;
  readiness?: ChannelView['socialReadiness'];
  offered?: Record<string, boolean>;
  onEnable?: (capability: ConnectCapability) => void;
}) {
  return (
    <details className='rafii-quiet rounded-xl p-3'>
      <summary className='rafii-focus cursor-pointer text-sm'>Individual capabilities and verification</summary>
      <p className='text-muted-foreground mt-2 text-xs'>Your saved connection and each additional feature have separate permissions and verification.</p>
      <ul className='mt-3 flex flex-col gap-3' aria-label='Official capabilities'>
        {Object.entries(features).map(([key, feature]) => (
          <li key={key} className='flex flex-wrap items-start justify-between gap-2 border-b border-foreground/5 pb-2 last:border-0'>
            <div className='min-w-0 flex-1'>
              <p className='text-sm'>{label(key)} <span className='text-muted-foreground text-xs'>— {officialCapabilityStatus(key, feature, readiness)}</span></p>
              {feature.limitation && <p className='text-muted-foreground mt-1 text-xs'>{feature.limitation}</p>}
              {isVerifiedConnectionFeature(key, feature, readiness) && feature.state !== 'READY' ? (
                <details className='text-muted-foreground mt-1 text-xs'>
                  <summary className='rafii-focus cursor-pointer'>Public release verification pending</summary>
                  <p className='mt-1'>{feature.blockers.join(' · ')}</p>
                </details>
              ) : <p className='text-muted-foreground mt-1 text-xs'>{feature.blockers.join(' · ')}</p>}
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

'use client';

import packs from '../../lib/channels/discord-copy.json';
import type { DiscordCopy } from '@/lib/channels/discord-copy';
import type { DiscordIdentity } from '@/lib/api/types';

interface Props {
  copy?: DiscordCopy;
  identities: DiscordIdentity[];
  available: boolean;
  canManage: boolean;
  canConnect: boolean;
  onConnect: () => void;
  onManage: (identityId: string) => void;
}

const CONTROL = 'rafii-focus rafii-quiet min-h-11 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50';

/** Personal identity is deliberately separate from publishing channel cards. */
export function DiscordPersonalAccounts({ identities, available, canManage, canConnect, onConnect, onManage, copy = packs.en }: Props) {
  return (
    <section className='flex min-w-0 flex-col gap-3' aria-labelledby='discord-personal-accounts-heading'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h2 id='discord-personal-accounts-heading' className='text-foreground text-lg font-medium tracking-tight'>{copy.personalTitle}</h2>
        {canManage && <button type='button' className={CONTROL} disabled={!available || !canConnect} onClick={onConnect}>{copy.connectIdentity}</button>}
      </div>
      <p className='text-muted-foreground max-w-[70ch] text-sm leading-relaxed'>{copy.identityNotice}</p>
      {!canManage && <p className='text-muted-foreground text-sm'>{copy.managePermission}</p>}
      {canManage && (!available || !canConnect) && <p className='text-muted-foreground text-sm'>{copy.connectionsUnavailable}</p>}
      {identities.length === 0 ? <p className='text-muted-foreground text-sm'>{copy.noIdentity}</p> : (
        <div className='grid min-w-0 gap-3 sm:grid-cols-2'>
          {identities.map(identity => (
            <article key={identity.id} id={`discord-identity-${identity.id}`} className='rafii-quiet flex min-w-0 flex-col items-start gap-2 rounded-[var(--rafii-radius-card)] p-4'>
              <p className='max-w-full font-medium [overflow-wrap:anywhere]'>{identity.account}</p>
              <p className='text-muted-foreground max-w-full text-xs [overflow-wrap:anywhere]'>{copy.accountId} {identity.userId} · {copy.storedStatus}: {identity.status === 'linked' ? copy.statusLinked : identity.status === 'disconnected' ? copy.statusDisconnected : identity.status === 'reconnect_required' ? copy.statusReconnect : copy.statusUnknown}</p>
              <p className='text-muted-foreground text-xs'>{identity.discoverGuilds === true ? copy.scopeGranted : copy.scopeNotGranted}. {copy.notDestination}</p>
              {identity.privateDraftsLinked !== undefined && <p className='text-muted-foreground text-xs'>{identity.privateDraftsLinked ? copy.privateStoredLinked : copy.privateStoredUnlinked}</p>}
              {canManage && <button type='button' className={CONTROL} disabled={!available} onClick={() => onManage(identity.id)}>{copy.manageIdentity}</button>}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

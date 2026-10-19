'use client';

import type { DiscordIdentity } from '@/lib/api/types';

interface Props {
  identities: DiscordIdentity[];
  available: boolean;
  canManage: boolean;
  canConnect: boolean;
  onConnect: () => void;
  onManage: (identityId: string) => void;
}

const CONTROL = 'rafii-focus rafii-quiet min-h-11 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50';

/** Personal identity is deliberately separate from publishing channel cards. */
export function DiscordPersonalAccounts({ identities, available, canManage, canConnect, onConnect, onManage }: Props) {
  return (
    <section className='flex min-w-0 flex-col gap-3' aria-labelledby='discord-personal-accounts-heading'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h2 id='discord-personal-accounts-heading' className='text-foreground text-lg font-medium tracking-tight'>Personal Discord accounts</h2>
        {canManage && <button type='button' className={CONTROL} disabled={!available || !canConnect} onClick={onConnect}>Connect personal Discord account</button>}
      </div>
      <p className='text-muted-foreground max-w-[70ch] text-sm leading-relaxed'>Connecting your account does not authorize publishing as you. Server posts are sent by Rafii’s bot after separate server, channel and message approval.</p>
      {!canManage && <p className='text-muted-foreground text-sm'>Managing these connections requires the appropriate workspace permission.</p>}
      {canManage && (!available || !canConnect) && <p className='text-muted-foreground text-sm'>New connections are currently unavailable. Existing account records remain visible.</p>}
      {identities.length === 0 ? <p className='text-muted-foreground text-sm'>No personal Discord account linked.</p> : (
        <div className='grid min-w-0 gap-3 sm:grid-cols-2'>
          {identities.map(identity => (
            <article key={identity.id} id={`discord-identity-${identity.id}`} className='rafii-quiet flex min-w-0 flex-col items-start gap-2 rounded-[var(--rafii-radius-card)] p-4'>
              <p className='max-w-full font-medium [overflow-wrap:anywhere]'>{identity.account}</p>
              <p className='text-muted-foreground max-w-full text-xs [overflow-wrap:anywhere]'>Discord account {identity.userId} · Stored link status: {identity.status.replaceAll('_', ' ')}</p>
              <p className='text-muted-foreground text-xs'>{identity.discoverGuilds === true ? 'Server-list permission granted' : 'Server-list permission not granted'}. This identity is not a publishing destination.</p>
              {canManage && <button type='button' className={CONTROL} disabled={!available} onClick={() => onManage(identity.id)}>Manage personal account</button>}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

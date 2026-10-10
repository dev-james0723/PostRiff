'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { AnimatedBadge } from '@/components/motion/animated-badge';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import type { ChannelView } from '@/lib/api/types';
import { copyFor, fill, type HealthCopy } from '@/lib/channels/health-copy';
import { badgeKey, lineKey, lineWorks, stateTone, type HealthAccount, type HealthAutonomy, type HealthState, type LineName } from '@/lib/channels/health';
import { CONNECT_CAPABILITIES, reconnectCapability, type ConnectCapability } from '@/lib/channels/state';
import { formatDate, relativeTime } from '@/lib/time';
import type { ConnectRequest } from '../connect-sheet';

const LINE_ORDER: LineName[] = ['publishing', 'analytics', 'history', 'comments'];

export function StateBadge({ copy, account, state }: { copy: HealthCopy; account?: Pick<HealthAccount, 'state' | 'reasons'>; state?: HealthState }) {
  const value = account?.state ?? state ?? 'not_connected';
  const label = copyFor(copy, account ? badgeKey(account) : `state.${value}`, 'state.not_connected');
  return (
    <AnimatedBadge status={stateTone(value)} size='sm' contentKey={label} className='shrink-0'>
      {label}
    </AnimatedBadge>
  );
}

function when(epoch: number | null | undefined) {
  return epoch ? relativeTime(epoch) : '—';
}

/** What the account can do, line by line. A gap is never styled like a working line. */
function Lines({ copy, account }: { copy: HealthCopy; account: HealthAccount }) {
  return (
    <dl className='grid gap-2 text-sm sm:grid-cols-[minmax(7rem,auto)_1fr] sm:gap-x-4'>
      {LINE_ORDER.map((name) => {
        const line = account.lines[name];
        if (!line) return null;
        const works = lineWorks(line);
        const Mark = works ? Icons.check : line.status === 'unavailable' ? Icons.warning : Icons.slash;
        return (
          <div key={name} className='contents'>
            <dt className='text-foreground font-medium'>{copy[`line.${name}` as keyof HealthCopy]}</dt>
            <dd className='text-muted-foreground flex min-w-0 items-start gap-2'>
              <Mark className={works ? 'text-foreground mt-0.5 size-4 shrink-0' : 'mt-0.5 size-4 shrink-0'} aria-hidden />
              <span className='min-w-0 text-pretty'>{fill(copyFor(copy, lineKey(name, line), 'status.not_offered'), { platform: account.platform })}</span>
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

function MissingPermissions({ copy, account, onGrant }: { copy: HealthCopy; account: HealthAccount; onGrant?: (capability: ConnectCapability) => void }) {
  const [open, setOpen] = useState(false);
  if (account.missingPermissions.length === 0) return null;
  const listId = `missing-${account.channelId}`;
  return (
    <section className='flex flex-col gap-2' aria-label={copy.missingTitle}>
      <h4 className='text-foreground text-sm font-medium'>{copy.missingTitle}</h4>
      <ul className='flex flex-col gap-2'>
        {account.missingPermissions.map((entry) => {
          const name = copyFor(copy, `capability.${entry.capability}`, 'capability.publish');
          const grantable = CONNECT_CAPABILITIES.find((value) => value === entry.capability);
          return (
            <li key={entry.capability} className='flex flex-wrap items-center justify-between gap-2 text-sm'>
              <span className='text-muted-foreground'>{name}</span>
              {onGrant && grantable && account.reconnect.available && (
                <Button variant='quiet' size='sm' className='h-11 min-w-11' onClick={() => onGrant(grantable)}>
                  {fill(copy.grant, { capability: name })}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      <Button variant='quiet' size='sm' className='h-11 self-start px-2' aria-expanded={open} aria-controls={listId} onClick={() => setOpen((value) => !value)}>
        <Icons.chevronDown className={open ? 'size-4 rotate-180 transition-transform motion-reduce:transition-none' : 'size-4 transition-transform motion-reduce:transition-none'} aria-hidden />
        {open ? copy.hideScopes : copy.showScopes}
      </Button>
      <ul id={listId} hidden={!open} className='text-muted-foreground flex flex-wrap gap-1.5 font-mono text-xs' lang='en'>
        {[...new Set(account.missingPermissions.flatMap((entry) => entry.scopes))].map((scope) => (
          <li key={scope} className='rafii-quiet rounded-[var(--rafii-radius-control)] px-2 py-1 break-all'>
            {scope}
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Last verified, access lifetime, last successful read and data age: the server's facts, never invented. */
function Facts({ copy, account }: { copy: HealthCopy; account: HealthAccount }) {
  const facts: { key: string; text: string; title?: string; strong?: boolean }[] = [];
  if (account.lastVerifiedAt) facts.push({ key: 'verified', text: fill(copy.lastVerified, { when: when(account.lastVerifiedAt) }), title: formatDate(account.lastVerifiedAt) });
  if (account.access.renewsAutomatically) facts.push({ key: 'access', text: copy.renews });
  else if (account.access.expiresAt && account.access.status !== 'expired')
    facts.push({ key: 'access', text: fill(copy.expires, { when: when(account.access.expiresAt) }), title: formatDate(account.access.expiresAt), strong: account.access.status === 'expiring' });
  const sync = account.sync;
  if (sync.status === 'unknown') facts.push({ key: 'sync', text: copy.lastSyncUnknown });
  else if (sync.lastSuccessAt)
    facts.push({ key: 'sync', text: fill(copyFor(copy, `lastSync.${sync.lastSuccessKind ?? ''}`, 'lastSync'), { when: when(sync.lastSuccessAt) }), title: formatDate(sync.lastSuccessAt) });
  else if (sync.status === 'not_applicable') facts.push({ key: 'sync', text: copy.lastSyncNone });
  else facts.push({ key: 'sync', text: copy.lastSyncNever });
  if (sync.lastProblemAt) facts.push({ key: 'problem', text: fill(copy.lastProblem, { when: when(sync.lastProblemAt) }), title: formatDate(sync.lastProblemAt), strong: true });
  if (sync.status !== 'not_applicable') {
    const band = account.freshness.band;
    facts.push({ key: 'fresh', text: fill(copyFor(copy, `freshness.${band}`, 'freshness.unknown'), { when: when(account.freshness.latestDataAt) }), title: account.freshness.latestDataAt ? formatDate(account.freshness.latestDataAt) : undefined });
  }
  return (
    <ul className='text-muted-foreground flex flex-col gap-1 text-xs sm:flex-row sm:flex-wrap sm:gap-x-3'>
      {facts.map((fact) => (
        <li key={fact.key} title={fact.title} className={fact.strong ? 'text-foreground font-medium' : undefined}>
          {fact.text}
        </li>
      ))}
    </ul>
  );
}

/** One reason in words, with the account's own platform and access deadline filled in. */
export function reasonText(copy: HealthCopy, reason: string, account: HealthAccount) {
  const text = copyFor(copy, `reason.${reason}`, 'stateLine.limited');
  return fill(text, { when: when(account.access.expiresAt), platform: account.platform });
}

export function AccountHealthCard({ copy, account, onConnect }: { copy: HealthCopy; account: HealthAccount; onConnect?: (request: ConnectRequest) => void }) {
  const reconnect = account.reconnect;
  const target = reconnect.available ? { channelId: reconnect.channelId, account: reconnect.account } : undefined;
  const request = (capability?: ConnectCapability): ConnectRequest | null =>
    reconnect.available && target
      ? { providerId: reconnect.providerId, capability: capability ?? reconnectCapability({ capabilities: account.capabilities as ChannelView['capabilities'] }), reconnect: target }
      : null;
  const open = (capability?: ConnectCapability) => {
    const next = request(capability);
    if (next && onConnect) onConnect(next);
  };
  const reasons = account.reasons;
  const needsReconnect = account.state === 'expired' || account.reasons.includes('access_expiring') || account.reasons.includes('no_permissions');
  return (
    <Surface as='article' material='glass' radius='card' padding='md' className='flex flex-col gap-4' aria-labelledby={`health-${account.channelId}`} data-attention={account.attention ? 'true' : undefined}>
      <header className='flex flex-wrap items-start justify-between gap-3'>
        <div className='flex min-w-0 items-center gap-3'>
          <ChannelIcon platform={account.platform} name={account.platform} size='md' />
          <div className='min-w-0'>
            <h4 id={`health-${account.channelId}`} className='text-foreground truncate text-base font-medium'>
              {account.account}
            </h4>
            <p className='text-muted-foreground truncate text-sm'>{account.platform}</p>
          </div>
        </div>
        <StateBadge copy={copy} account={account} />
      </header>
      <div className='flex flex-col gap-1'>
        <p className='text-foreground text-sm text-pretty'>{copyFor(copy, `stateLine.${account.state}`, 'stateLine.limited')}</p>
        {reasons.length > 0 && (
          <ul className='text-muted-foreground flex flex-col gap-1 text-sm'>
            {reasons.map((reason) => (
              <li key={reason} className='text-pretty'>
                {reasonText(copy, reason, account)}
              </li>
            ))}
          </ul>
        )}
      </div>
      <Lines copy={copy} account={account} />
      <MissingPermissions copy={copy} account={account} onGrant={onConnect ? (capability) => open(capability) : undefined} />
      <Facts copy={copy} account={account} />
      <footer className='flex flex-wrap items-center gap-3'>
        {reconnect.available ? (
          onConnect && (
            <>
              <Button variant={needsReconnect ? 'action' : 'glass'} size='control' onClick={() => open()}>
                <Icons.refresh className='size-4' aria-hidden />
                {copy.reconnect}
              </Button>
              <p className='text-muted-foreground max-w-prose text-xs text-pretty'>{fill(copy.reconnectNote, { platform: account.platform })}</p>
            </>
          )
        ) : (
          <p className='text-muted-foreground text-sm'>
            {reconnect.reason === 'manage_required' ? copy.manageRequired : fill(copy.reconnectUnavailable, { platform: account.platform })}
          </p>
        )}
      </footer>
    </Surface>
  );
}

const CATEGORY_KEYS = ['read_analyze', 'navigate_interact', 'create_edit', 'manage_settings', 'manage_connected_services', 'execute_automations'];

/** The agent's autonomy: lane B1's permissions when its flag is on, otherwise exactly today's behaviour. */
export function AutonomySummary({ copy, autonomy }: { copy: HealthCopy; autonomy: HealthAutonomy }) {
  return (
    <Surface as='section' material='quiet' radius='card' padding='md' className='flex flex-col gap-3' aria-labelledby='health-autonomy'>
      <h2 id='health-autonomy' className='text-foreground text-lg font-medium tracking-tight'>
        {copy.autonomyTitle}
      </h2>
      {autonomy.source === 'todays_behaviour' ? (
        <p className='text-muted-foreground text-sm text-pretty'>{copy.autonomyToday}</p>
      ) : autonomy.source === 'unavailable' ? (
        <p className='text-foreground text-sm'>{copy.autonomyUnavailable}</p>
      ) : (
        <div className='flex flex-col gap-2 text-sm'>
          <p className='text-foreground'>{fill(copy.autonomyPreset, { preset: copyFor(copy, `preset.${autonomy.preset ?? 'legacy'}`, 'preset.legacy') })}</p>
          {autonomy.mode === 'shadow' && <p className='text-muted-foreground'>{copy.autonomyShadow}</p>}
          {autonomy.needsChoice && <p className='text-muted-foreground'>{copy.autonomyNeedsChoice}</p>}
          {autonomy.categories.length > 0 && (
            <dl className='grid gap-1 sm:grid-cols-[minmax(10rem,auto)_1fr] sm:gap-x-4'>
              {autonomy.categories
                .filter((row) => CATEGORY_KEYS.includes(row.id))
                .map((row) => (
                  <div key={row.id} className='contents'>
                    <dt className='text-foreground'>{copyFor(copy, `category.${row.id}`, 'category.read_analyze')}</dt>
                    <dd className='text-muted-foreground'>{copyFor(copy, `effective.${row.effective}`, 'effective.unavailable')}</dd>
                  </div>
                ))}
            </dl>
          )}
        </div>
      )}
      <p className='text-muted-foreground text-sm text-pretty'>{copy.autonomyConnections}</p>
      {autonomy.source === 'agent_permissions' && (
        <Link href={autonomy.href} className='rafii-focus text-foreground inline-flex min-h-11 items-center gap-1 self-start rounded-sm text-sm underline underline-offset-2'>
          {copy.autonomyOpen}
          <Icons.arrowRight className='size-4' aria-hidden />
        </Link>
      )}
    </Surface>
  );
}

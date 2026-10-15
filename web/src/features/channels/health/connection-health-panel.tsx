'use client';

import Link from 'next/link';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { Surface } from '@/components/rafii';
import { useConnectionHealth } from '@/lib/api/hooks';
import { copyFor, fill, healthCopy } from '@/lib/channels/health-copy';
import { attentionAccounts, HEALTH_HREF, panelNumbers } from '@/lib/channels/health';
import { usePreferences } from '@/lib/preferences';
import { reasonText, StateBadge } from './health-parts';

/**
 * The compact Health Center panel on Channels, the page Rafii's agent already links to. Mounted only when the
 * Channels response names the Health Center (`connectionHealth.available`), so with the flag off nothing is asked for
 * and nothing is drawn. Counts and attention rows are the server's; the panel never summarizes them as "all good".
 */
export function ConnectionHealthPanel() {
  const { locale } = usePreferences();
  const { copy, lang } = healthCopy(locale);
  const health = useConnectionHealth();
  const data = health.data;
  if (!data) return null;   // loading or unreadable: the full page carries the error state
  const numbers = panelNumbers(data);
  const rows = attentionAccounts(data);
  return (
    <Surface as='section' material='quiet' radius='card' padding='md' lang={lang} className='flex flex-col gap-3' aria-labelledby='connection-health-panel'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <h2 id='connection-health-panel' className='text-foreground text-base font-medium tracking-tight'>
          {copy.panelTitle}
        </h2>
        <Link href={HEALTH_HREF} className='rafii-focus text-foreground inline-flex min-h-11 items-center gap-1 rounded-sm text-sm underline underline-offset-2'>
          {copy.panelOpen}
          <Icons.arrowRight className='size-4' aria-hidden />
        </Link>
      </div>
      <p className='text-muted-foreground text-sm'>{fill(copy.panelSummary, numbers)}</p>
      {rows.length > 0 && (
        <ul className='flex flex-col gap-2'>
          {rows.map((account) => (
            <li key={account.channelId} className='flex flex-wrap items-center justify-between gap-2 text-sm'>
              <span className='flex min-w-0 items-center gap-2'>
                <ChannelIcon platform={account.platform} name={account.platform} size='sm' />
                <span className='text-foreground truncate'>{account.account}</span>
                <span className='text-muted-foreground truncate'>
                  {account.reasons[0] ? reasonText(copy, account.reasons[0], account) : copyFor(copy, `stateLine.${account.state}`, 'stateLine.limited')}
                </span>
              </span>
              <StateBadge copy={copy} account={account} />
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}

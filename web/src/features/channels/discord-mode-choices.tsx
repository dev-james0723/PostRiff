'use client';
import packs from '../../lib/channels/discord-copy.json';
import type { DiscordCopy } from '@/lib/channels/discord-copy';
import type { DiscordModes } from '@/lib/api/types';
export type DiscordPurpose = 'identity' | 'installation' | 'webhook';
const CONTROL = 'rafii-focus rafii-quiet min-h-11 rounded-[var(--rafii-radius-control)] px-3 py-2 text-left text-sm disabled:cursor-not-allowed disabled:opacity-50';

export function DiscordModeChoices({purpose, busy, modes, onChange, copy = packs.en}: {
  purpose: DiscordPurpose; busy: boolean; modes?: DiscordModes;
  onChange: (purpose: DiscordPurpose) => void; copy?: DiscordCopy;
}) {
  let installUrl: string | undefined;
  try {
    const u = new URL(modes?.userInstall.installUrl ?? '');
    if (u.origin === 'https://discord.com' && u.pathname === '/oauth2/authorize'
      && u.searchParams.get('integration_type') === '1' && u.searchParams.get('scope') === 'applications.commands'
      && /^[0-9]{5,25}$/.test(u.searchParams.get('client_id') ?? '') && !u.hash && !u.username && !u.password
      && [...u.searchParams.keys()].every(k => ['client_id', 'scope', 'integration_type'].includes(k))) installUrl = u.href;
  } catch { /* unavailable/untrusted provider URL has no operative link */ }
  return <div className='flex min-w-0 flex-col gap-3' data-discord-modes>
    <div className='flex flex-wrap gap-2'>
      <button type='button' className={CONTROL} disabled={busy} aria-pressed={purpose === 'identity'} onClick={() => onChange('identity')}>{copy.connectIdentity}</button>
      <button type='button' className={CONTROL} disabled={busy} aria-pressed={purpose === 'installation'} onClick={() => onChange('installation')}>{copy.authorizeServer}</button>
      <button type='button' className={CONTROL} disabled={busy || !modes?.webhook.enabled} aria-pressed={purpose === 'webhook'} onClick={() => onChange('webhook')}>{copy.authorizeWebhook}</button>
      {modes?.userInstall.enabled && installUrl ? <a className={CONTROL} href={busy ? undefined : installUrl} aria-disabled={busy || undefined}>{copy.installUser}</a>
        : <button type='button' className={CONTROL} disabled>{copy.userInstall}</button>}
    </div>
    {!modes?.webhook.enabled && <p className='text-muted-foreground text-xs'>{copy.webhookUnavailable}</p>}
    <p className='text-muted-foreground text-xs'>{modes?.userInstall.enabled && installUrl ? copy.interactionNotice : copy.interactionUnavailable}</p>
    {purpose === 'webhook' && <p className='text-muted-foreground text-sm'>{copy.webhookNotice}</p>}
  </div>;
}

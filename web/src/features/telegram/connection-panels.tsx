'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useWorkspaceAccess, checkAccess } from '@/lib/auth/access';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Label } from '@/components/ui/label';
import type { TelegramControls, TelegramBotAccessPreview } from './types';

export function TelegramIdentityPanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const allowed = checkAccess(access, { permission: 'manage_connections' });
  const identities = useQuery({ queryKey: [workspaceId, 'telegram-identities'], queryFn: () => api.telegramIdentities(workspaceId), enabled: allowed });
  const consumed = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [disconnect, setDisconnect] = useState('');

  useEffect(() => {
    if (!allowed || consumed.current) return;
    const params = new URLSearchParams(window.location.search);
    const state = params.get('state');
    if (!state || (!params.has('code') && !params.has('error'))) return;
    consumed.current = true;
    window.history.replaceState(null, '', window.location.pathname);
    setBusy(true);
    void api.telegramLoginComplete(workspaceId, { state, code: params.get('code') ?? undefined, error: params.get('error') ?? undefined })
      .then(result => { if (result.status === 'denied') setError('Telegram connection was cancelled.'); return identities.refetch(); })
      .catch(e => setError(e instanceof Error ? e.message : 'Telegram Login could not be verified.'))
      .finally(() => setBusy(false));
  }, [allowed, api, workspaceId, identities]);

  return <section className='space-y-3 rounded-xl border p-4' aria-label='Telegram identity'>
    <h2 className='font-medium'>Connect Telegram</h2>
    <p className='text-muted-foreground text-sm'>Verify your Telegram identity, then choose which channels, groups or Secretary conversations Rafii may manage.</p>
    {error && <p role='alert' className='text-sm'>{error}</p>}
    {identities.isError && <p role='alert' className='text-sm'>{identities.error instanceof Error ? identities.error.message : 'Connection status is unavailable.'}</p>}
    {identities.data?.configured === false && <p role='status' className='text-sm'>Telegram Login is awaiting Rafii setup. Bot destination connections are available below when configured.</p>}
    <Button variant='glass' disabled={!allowed || busy || !identities.data?.configured} onClick={() => {
      setBusy(true); setError('');
      void api.telegramLoginStart(workspaceId).then(result => window.location.assign(result.authorizeUrl))
        .catch(e => { setError(e instanceof Error ? e.message : 'Telegram Login is unavailable.'); setBusy(false); });
    }}>{busy ? 'Connecting…' : 'Connect Telegram identity'}</Button>
    {identities.data?.identities.map(identity => <div key={identity.id} className='space-y-2 rounded-lg border p-3 text-sm'>
      <p>{identity.name || identity.username || 'Telegram identity'} · Connected</p>
      <p className='text-muted-foreground text-xs'>Identity verified. Destination management permissions are granted separately.</p>
      <Button variant='quiet' disabled={busy} onClick={() => setDisconnect(identity.id)}>Disconnect identity</Button>
      {disconnect === identity.id && <div className='space-y-2'>
        <p>Disconnect this identity? Review bot and destination permissions separately below.</p>
        <Button variant='action' disabled={busy} onClick={() => {
          setBusy(true);
          void api.telegramIdentityDisconnect(workspaceId, identity.id).then(() => { setDisconnect(''); return identities.refetch(); })
            .catch(e => setError(e instanceof Error ? e.message : 'Disconnect failed.')).finally(() => setBusy(false));
        }}>Confirm disconnect</Button>
      </div>}
    </div>)}
  </section>;
}

export function TelegramAutomationPanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const owner = access?.role === 'owner';
  const settings = useQuery({ queryKey: [workspaceId, 'telegram-controls'], queryFn: () => api.telegramControls(workspaceId) });
  const destinations = useQuery({ queryKey: [workspaceId, 'telegram-destinations'], queryFn: () => api.telegramDestinations(workspaceId) });
  const [draft, setDraft] = useState<TelegramControls | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const value = draft ?? settings.data;
  async function save(paused: boolean) {
    if (!value) return;
    setBusy(true); setError('');
    try {
      const result = await api.telegramSetControls(workspaceId, { ...value, paused, confirmed: !paused });
      setDraft(result); await settings.refetch();
    } catch (e) { setError(e instanceof Error ? e.message : 'Telegram settings could not be saved.'); }
    finally { setBusy(false); }
  }
  return <section className='space-y-3 rounded-xl border p-4' aria-label='Telegram automation consent'>
    <h2 className='font-medium'>Automation permissions</h2>
    <p role='status' className='text-sm'>{settings.data ? settings.data.paused ? 'Telegram automations paused' : 'Telegram automations enabled for selected destinations' : 'Loading automation status…'}</p>
    {error && <p role='alert' className='text-sm'>{error}</p>}
    {settings.isError && <p role='alert' className='text-sm'>Automation settings are unavailable. Automatic execution stays blocked.</p>}
    <Button variant='action' disabled={!owner || busy || !settings.data} onClick={() => void save(true)}>Pause all Telegram automations</Button>
    {value && <>
      <Label>Approval policy<select aria-label='Telegram approval policy' className='bg-background w-full rounded border p-2' disabled={!owner || busy} value={value.approvalPolicy} onChange={e => setDraft({ ...value, approvalPolicy: e.target.value as TelegramControls['approvalPolicy'] })}>
        <option value='always'>Approve every action before sending</option><option value='scoped_auto'>Automatic execution for selected actions and destinations</option>
      </select></Label>
      <div className='space-y-2'><p className='text-sm'>Authorized destinations</p>{destinations.data?.destinations.map(destination => <Label key={destination.connectionId} className='flex items-center gap-2 text-sm'>
        <Checkbox disabled={!owner || busy} checked={value.allowedConnections.includes(destination.connectionId)} onCheckedChange={checked => setDraft({ ...value, allowedConnections: checked ? [...value.allowedConnections, destination.connectionId] : value.allowedConnections.filter(id => id !== destination.connectionId) })} />{destination.title || destination.connectionId}
      </Label>)}</div>
      <div className='flex flex-wrap gap-4'>{['publish', 'reply', 'moderate'].map(action => <Label key={action} className='flex items-center gap-2 text-sm'>
        <Checkbox aria-label={`Automatic Telegram ${action}`} disabled={!owner || busy || action !== 'publish'} checked={value.allowedActions.includes(action)} onCheckedChange={checked => setDraft({ ...value, allowedActions: checked ? [...value.allowedActions, action] : value.allowedActions.filter(a => a !== action) })} />{action}{action !== 'publish' && ' · unavailable'}
      </Label>)}</div>
      <Label>Conversation retention<select aria-label='Telegram conversation retention' className='bg-background w-full rounded border p-2' disabled={!owner || busy} value={value.retentionDays} onChange={e => setDraft({ ...value, retentionDays: Number(e.target.value) })}>{[1, 7, 30, 90].map(days => <option key={days} value={days}>{days} days</option>)}</select></Label>
      <p className='text-muted-foreground text-xs'>This consent applies only to the selected actions. Telegram permissions and real capability verification are checked again before every send.</p>
      <Button variant='glass' disabled={!owner || busy || !value.allowedConnections.length || !value.allowedActions.length} onClick={() => void save(false)}>Confirm selected permissions and enable</Button>
      <Button variant='quiet' disabled={!owner || busy} onClick={() => void save(true)}>Save with automations paused</Button>
    </>}
  </section>;
}


export function TelegramManagedBotPanel() {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const allowed = checkAccess(access, { permission: 'manage_connections' });
  const status = useQuery({ queryKey: [workspaceId, 'telegram-managed-bots'], queryFn: () => api.telegramManagedStatus(workspaceId), enabled: allowed });
  const identities = useQuery({ queryKey: [workspaceId, 'telegram-identities'], queryFn: () => api.telegramIdentities(workspaceId), enabled: allowed });
  const [identity, setIdentity] = useState('');
  const [username, setUsername] = useState('');
  const [name, setName] = useState('');
  const [creationUrl, setCreationUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return <section className='space-y-3 rounded-xl border p-4' aria-label='Official managed Telegram bots'>
    <h2 className='font-medium'>Create a Telegram bot</h2>
    <p className='text-muted-foreground text-sm'>Create a bot you own through Telegram, then authorize Rafii to connect it. Confirm the creation in Telegram before returning here.</p>
    {status.data?.available === false && <p role='status' className='text-sm'>Managed bot creation is awaiting Rafii’s BotFather configuration.</p>}
    {error && <p role='alert' className='text-sm'>{error}</p>}
    {status.isError && <p role='alert' className='text-sm'>Managed bot status is unavailable.</p>}
    <Label>Your verified Telegram identity<select aria-label='Managed bot owner identity' className='bg-background w-full rounded border p-2' value={identity} onChange={e => setIdentity(e.target.value)}><option value=''>Choose an identity</option>{identities.data?.identities.map(i => <option key={i.id} value={i.id}>{i.name || i.username || 'Telegram identity'}</option>)}</select></Label>
    <Label>Bot display name<input aria-label='Bot display name' className='bg-background w-full rounded border p-2' maxLength={64} value={name} onChange={e => { setName(e.target.value); setCreationUrl(''); }} /></Label>
    <Label>Bot username<input aria-label='Bot username' className='bg-background w-full rounded border p-2' maxLength={32} placeholder='YourNameBot' value={username} onChange={e => { setUsername(e.target.value); setCreationUrl(''); }} /></Label>
    <Button variant='glass' disabled={!allowed || busy || !status.data?.available || !identity || !name.trim() || !username} onClick={() => {
      setBusy(true); setError('');
      void api.telegramManagedStart(workspaceId, { identityId: identity, name: name.trim(), username, confirmed: true }).then(result => { setCreationUrl(result.creationUrl); return status.refetch(); })
        .catch(e => setError(e instanceof Error ? e.message : 'Could not prepare managed bot creation.')).finally(() => setBusy(false));
    }}>Continue to Telegram bot creation</Button>
    {creationUrl && <a className='block text-sm underline' target='_blank' rel='noopener noreferrer' href={creationUrl}>Open Telegram and confirm creation</a>}
    {status.data?.requests.map(request => <div className='space-y-2 rounded border p-3 text-sm' key={request.username}>
      <p>@{request.username} · Awaiting Telegram confirmation</p>
      <p className='text-muted-foreground text-xs'>Connect this bot and configure its Rafii webhook after Telegram confirms the selected owner.</p>
      <Button variant='action' disabled={!allowed || busy} onClick={() => {
        setBusy(true); setError('');
        void api.telegramManagedConnect(workspaceId, { username: request.username, confirmed: true }).then(result => { if (result.status === 'webhook_outcome_unknown') setError('Webhook outcome is unknown. Inspect the bot connection before retrying.'); return status.refetch(); })
          .catch(e => setError(e instanceof Error ? e.message : 'Managed bot connection is unavailable.')).finally(() => setBusy(false));
      }}>Confirm @{request.username} and Rafii webhook</Button>
    </div>)}
    {status.data?.bots?.map(bot => <TelegramManagedAccessPanel key={bot.botId} {...bot} />)}
  </section>;
}

function TelegramManagedAccessPanel({ botId, username }: { botId: string; username: string }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [loaded, setLoaded] = useState(false);
  const [restricted, setRestricted] = useState(true);
  const [users, setUsers] = useState('');
  const [preview, setPreview] = useState<TelegramBotAccessPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const audience = (value: { restricted: boolean; addedUserIds: number[] }) => value.restricted
    ? `Owner only${value.addedUserIds.length ? `, plus Telegram user IDs ${value.addedUserIds.join(', ')}` : ''}`
    : 'Everyone on Telegram';
  async function read() {
    setBusy(true); setNotice(''); setPreview(null);
    try {
      const value = await api.telegramManagedAccess(workspaceId, botId);
      setRestricted(value.restricted); setUsers(value.addedUserIds.join(', ')); setLoaded(true);
      setNotice(`Current access: ${audience(value)}`);
    } catch (e) { setNotice(e instanceof Error ? e.message : 'Bot access settings are unavailable.'); }
    finally { setBusy(false); }
  }
  async function prepare() {
    const ids = users.trim() ? users.split(',').map(id => Number(id.trim())) : [];
    if (restricted && (ids.length > 10 || ids.some(id => !Number.isSafeInteger(id) || id <= 0 || id >= 2 ** 52))) {
      setNotice('Enter up to ten positive Telegram user IDs, separated by commas.'); return;
    }
    setBusy(true); setNotice('');
    try { setPreview(await api.telegramManagedAccessPrepare(workspaceId, botId, { restricted, addedUserIds: restricted ? ids : [] })); }
    catch (e) { setNotice(e instanceof Error ? e.message : 'Could not prepare bot access settings.'); }
    finally { setBusy(false); }
  }
  async function execute() {
    if (!preview) return;
    setBusy(true); setNotice('');
    try {
      const result = await api.telegramManagedAccessExecute(workspaceId, botId, { proof: preview.proof, keyId: preview.keyId, confirmed: true });
      setRestricted(result.settings.restricted); setUsers(result.settings.addedUserIds.join(', '));
      setNotice(`Telegram confirmed access: ${audience(result.settings)}`);
    } catch (e) { setNotice(`${e instanceof Error ? e.message : 'Bot access change could not be confirmed.'} Read current access before retrying.`); }
    finally { setPreview(null); setBusy(false); }
  }
  return <div className='space-y-3 rounded border p-3 text-sm' aria-label={`Managed bot access for @${username}`}>
    <p className='font-medium'>@{username} · Who can use this bot?</p>
    <Button variant='quiet' disabled={busy} onClick={() => void read()}>Read @{username} access</Button>
    {notice && <p role='status'>{notice}</p>}
    {loaded && <>
      <Label>Bot access<select aria-label={`Access audience for @${username}`} className='bg-background w-full rounded border p-2' disabled={busy} value={restricted ? 'restricted' : 'public'} onChange={e => { setRestricted(e.target.value === 'restricted'); setPreview(null); }}>
        <option value='restricted'>Owner and selected users</option><option value='public'>Everyone on Telegram</option>
      </select></Label>
      {restricted && <Label>Additional Telegram user IDs (optional, maximum ten)<input aria-label={`Additional users for @${username}`} className='bg-background w-full rounded border p-2' disabled={busy} maxLength={180} value={users} onChange={e => { setUsers(e.target.value); setPreview(null); }} /></Label>}
      <p className='text-muted-foreground text-xs'>The bot owner always retains access. Changes affect who can use this bot on Telegram.</p>
      <Button variant='glass' disabled={busy} onClick={() => void prepare()}>Preview @{username} access change</Button>
    </>}
    {preview && <div className='space-y-2 rounded border p-3' aria-label={`Access preview for @${username}`}>
      <p>Current: {audience(preview.preview.before)}</p><p>Proposed: {audience(preview.preview.after)}</p>
      <Button variant='action' disabled={busy} onClick={() => void execute()}>Confirm @{username} access change</Button>
      <Button variant='quiet' disabled={busy} onClick={() => setPreview(null)}>Cancel @{username} access change</Button>
    </div>}
  </div>;
}

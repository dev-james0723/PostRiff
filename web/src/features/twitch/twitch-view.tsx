'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import Link from 'next/link';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useQueryState } from 'nuqs';
import PageContainer from '@/components/layout/page-container';
import { ChannelIcon } from '@/components/channel-icon';
import { StateMessage, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useChannels } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { OAuthStart, ProviderView } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { useSiteAgentPageContext } from '@/features/site-agent/use-page-context';
import { NativeFields, TWITCH_SELECT_CLASS } from './native-fields';
import { SensitiveTwitchControls } from './sensitive-controls';
import { ActionReceipts, DataReceipt, NativeReadResult, displayTime } from './receipts';
import {
  TWITCH_GROUPS, actionStateLabel, capabilityAvailable, capabilityGroup,
  effectsList, parseFields, reviewCanApprove, reviewScheduledInstant, safeDisplay, scheduledInstant,
  submissionSignature, timestampMillis, twitchAuthorizeUrl, verificationLabel,
  type TwitchGroupId
} from './contracts';
import type { TwitchAction, TwitchCapability, TwitchConnection, TwitchReadiness, TwitchReadResult } from './types';

const EMPTY_CAPABILITIES: TwitchCapability[] = [];

const INFO = {
  title: 'Twitch workspace',
  sections: [
    { title: 'A permission for each action', description: 'Twitch account permissions, channel roles, account eligibility and Rafii workspace access are checked separately. An account connection does not grant all operations.' },
    { title: 'Review, approve, then execute', description: 'Rafii prepares the exact change first. Your approval is bound to that payload, time, account and authorization. Editing any of them requires a new review.' },
    { title: 'Schedule and streaming', description: 'A Twitch schedule entry announces a broadcast. Starting the encoder and handling ingest credentials are separate operations.' },
    { title: 'Analytics coverage', description: 'Reports show only fields Twitch exposes. Snapshot counts and limited game or extension reports do not establish channel watch time, unique viewers or complete revenue.' }
  ]
};

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Twitch could not complete this request.';
}

function Readiness({ readiness }: { readiness: TwitchReadiness }) {
  const items = [
    ['Public connection', readiness.publicConnect === true ? 'Available' : 'Not released'],
    ['Production verification', readiness.productionVerified === true ? 'Verified' : 'Unverified'],
    ['Commercial clearance', readiness.commercialApproved === true ? 'Recorded' : 'Not recorded']
  ];
  return (
    <div className='grid gap-3'>
      <dl className='flex flex-wrap gap-x-7 gap-y-3'>
        {items.map(([name, status]) => <div key={name} className='grid gap-1'><dt className='text-muted-foreground text-xs'>{name}</dt><dd className='text-sm font-medium'>{status}</dd></div>)}
      </dl>
      {Boolean(readiness.reasons?.length) && <ul className='text-muted-foreground list-inside list-disc text-xs leading-relaxed'>{readiness.reasons?.map((reason) => <li key={reason}>{reason}</li>)}</ul>}
    </div>
  );
}

function ScopeDetails({ capability }: { capability: TwitchCapability }) {
  const scopes = capability.requiredScopes ?? [];
  const alternatives: string[][] = scopes.length && Array.isArray(scopes[0]) ? scopes as string[][] : [scopes as string[]];
  return (
    <details className='text-muted-foreground rounded-lg border p-3 text-xs'>
      <summary className='rafii-focus cursor-pointer rounded-sm'>Permissions & availability</summary>
      <div className='mt-3 grid gap-2'>
        {alternatives.map((set, index) => <p key={index}>{alternatives.length > 1 ? `Permission option ${index + 1}: ` : 'Twitch scopes: '}{set.length ? set.join(', ') : 'No additional Twitch scopes'}</p>)}
        {effectsList(capability.eligibility).map((item) => <p key={item}>Account requirement: {item}</p>)}
        {capability.subjectPolicy && <p>Channel role: {capability.subjectPolicy.replaceAll('_', ' ')}</p>}
        <p>Live verification: {capability.liveVerified === true && capability.verification === 'verified' ? 'Recorded' : 'Not recorded'}</p>
        {capability.status === 'implemented_offline' && <p>Engineering status: implementation available for offline validation. Live behavior still needs verification.</p>}
      </div>
    </details>
  );
}

function OAuthReview({ request, dismiss }: { request: OAuthStart; dismiss: () => void }) {
  const authorizeUrl = twitchAuthorizeUrl(request.authorizeUrl);
  const expiry = timestampMillis(request.expiresAt);
  const valid = authorizeUrl && expiry !== null && expiry > Date.now();
  return (
    <Surface as='section' material='selected' className='grid gap-4' aria-labelledby='twitch-oauth-heading'>
      <h2 id='twitch-oauth-heading' className='font-medium'>Review Twitch authorization</h2>
      <p className='text-sm leading-relaxed'>{request.permissionExplanation}</p>
      <div className='grid gap-2'>
        <p className='text-muted-foreground text-xs'>Requested permissions</p>
        {request.scopes.length ? <ul className='flex flex-wrap gap-2'>{request.scopes.map((scope) => <li key={scope} className='rounded-full border px-2.5 py-1 font-mono text-xs'>{scope}</li>)}</ul> : <p className='text-sm'>Account identity only. Native operations request their own additional permissions.</p>}
      </div>
      <p className='text-muted-foreground text-xs'>Continue on Twitch to choose your account and grant access. This step does not perform a channel action.</p>
      <div className='flex flex-wrap items-center gap-3'>
        {valid ? <a className='rafii-focus bg-primary text-primary-foreground inline-flex min-h-10 items-center rounded-md px-4 text-sm font-medium' href={authorizeUrl} rel='noreferrer'>Continue on Twitch</a> : <p role='alert' className='text-destructive text-sm'>This authorization link is unavailable or expired. Prepare a new request.</p>}
        <Button type='button' variant='ghost' onClick={dismiss}>Dismiss</Button>
      </div>
    </Surface>
  );
}

export function TwitchWorkspaceView() {
  const { workspaceId } = useWorkspaceApi();
  // Remount all local UI state when the selected workspace changes, including pending OAuth.
  return <WorkspaceTwitch key={workspaceId} />;
}

function WorkspaceTwitch() {
  const { api, workspaceId } = useWorkspaceApi();
  const channels = useChannels();
  const access = useWorkspaceAccess();
  const [selected, setSelected] = useQueryState('connection', { defaultValue: '' });
  const [oauth, setOAuth] = useState<OAuthStart>();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const list = useQuery({
    queryKey: ['twitch-connections', workspaceId],
    queryFn: () => api.twitchConnections(workspaceId),
    enabled: Boolean(workspaceId), retry: false, staleTime: 30_000
  });
  const provider = channels.data?.providers.find((item) => item.id === 'twitch');
  const connections = list.data?.connections ?? [];
  const connection = selected ? connections.find((item) => item.id === selected) : connections[0];
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const connectReady = provider?.connectReady === true && provider.featureFlagEnabled !== false && provider.executionPaused !== true;

  async function startConnect() {
    setBusy(true);
    setError('');
    setOAuth(undefined);
    try { setOAuth(await api.oauthStart(workspaceId, 'twitch', 'identity')); }
    catch (err) { setError(errorMessage(err)); }
    finally { setBusy(false); }
  }

  return (
    <PageContainer pageTitle='Twitch' pageDescription='Your channel, community and live operations.' infoContent={INFO} pageHeaderAction={<Link href='/app/channels' className='rafii-focus text-muted-foreground rounded-sm text-sm underline underline-offset-4'>All channels</Link>}>
      {/* Native Agent tools enforce content consent. Generic screen context receives only registered local IDs and operation names. */}
      <div className='grid gap-5' data-private>
      <Surface className='grid gap-5'>
        <div className='flex flex-wrap items-center justify-between gap-4'>
          <div className='flex min-w-0 items-center gap-3'>
            <ChannelIcon slug='twitch' name='Twitch' size='lg' />
            <div className='grid gap-1'><h2 className='font-medium'>Twitch workspace</h2><p className='text-muted-foreground text-sm'>Every change has its own review and approval.</p></div>
          </div>
          {canManage && <Button type='button' variant='outline' disabled={busy || !connectReady} onClick={() => void startConnect()}>{busy ? 'Preparing authorization…' : connections.length ? 'Connect another Twitch account' : 'Connect Twitch'}</Button>}
        </div>
        {list.data && <Readiness readiness={list.data.readiness} />}
        {!connectReady && <p className='text-muted-foreground text-sm'>{provider?.setupIssues?.[0] || 'Twitch connection is not available for this workspace yet. Setup and release verification are still required.'}</p>}
        {connections.length > 0 && <div className='grid max-w-md gap-1.5'><Label htmlFor='twitch-connection'>Twitch account</Label><select id='twitch-connection' className={TWITCH_SELECT_CLASS} value={connection?.id ?? ''} onChange={(event) => { setOAuth(undefined); void setSelected(event.target.value); }}>{!connection && <option value=''>Choose an account in this workspace</option>}{connections.map((item) => <option key={item.id} value={item.id}>{item.account || item.handle || item.id} · {item.status}</option>)}</select></div>}
      </Surface>
      {error && <StateMessage kind='error' title='Authorization could not be prepared' description={error} />}
      {oauth && <OAuthReview request={oauth} dismiss={() => setOAuth(undefined)} />}
      {list.isPending && <StateMessage kind='loading' title='Loading Twitch connections…' />}
      {list.isError && <StateMessage kind={list.error instanceof ApiError && list.error.status === 404 ? 'unsupported' : 'error'} title='Twitch workspace is unavailable' description={errorMessage(list.error)} action={<Button type='button' variant='outline' onClick={() => void list.refetch()}>Check again</Button>} />}
      {list.data && !connection && <Surface as='section' material='quiet' className='grid gap-4'><h2 className='font-medium'>Native Twitch operations</h2><p className='text-muted-foreground text-sm'>Choose a connected account to see its exact scopes, eligibility and available actions.</p><ul className='grid gap-4 md:grid-cols-2 xl:grid-cols-3'>{TWITCH_GROUPS.map((group) => <li key={group.id} className='grid gap-1'><h3 className='text-sm font-medium'>{group.label}</h3><p className='text-muted-foreground text-xs leading-relaxed'>{group.description}</p></li>)}</ul></Surface>}
      {connection && <ConnectionTwitch key={`${workspaceId}:${connection.id}`} connection={connection} provider={provider} />}
      {Boolean(list.data?.limitations.length) && <details className='text-muted-foreground rounded-lg border p-4 text-sm'><summary className='rafii-focus cursor-pointer rounded-sm'>Twitch API limits</summary><ul className='mt-3 list-inside list-disc space-y-2'>{list.data?.limitations.map((note) => <li key={note}>{note}</li>)}</ul></details>}
      </div>
    </PageContainer>
  );
}

function ConnectionTwitch({ connection, provider }: { connection: TwitchConnection; provider?: ProviderView }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const canManage = checkAccess(access, { permission: 'manage_connections' });
  const [group, setGroup] = useState<TwitchGroupId>('channel');
  const [actionId, setActionId] = useState('');
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [executeAt, setExecuteAt] = useState('');
  const [pastBroadcastsEnabled, setPastBroadcastsEnabled] = useState(false);
  const [review, setReview] = useState<{ action: TwitchAction; signature: string }>();
  const [acknowledged, setAcknowledged] = useState(false);
  const [result, setResult] = useState<{ label: string; value: TwitchReadResult }>();
  const [oauth, setOAuth] = useState<OAuthStart>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [clock, setClock] = useState(Date.now());
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (!review) return;
    const timer = setInterval(() => setClock(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [review]);

  const overview = useQuery({
    queryKey: ['twitch-overview', workspaceId, connection.id],
    queryFn: () => api.twitchOverview(workspaceId, connection.id),
    retry: false, staleTime: 15_000,
    // This endpoint only reads stored Rafii state, not Twitch. Helix reads remain explicit.
    refetchInterval: (query) => query.state.data?.actions.some((item) => ['approved', 'queued', 'scheduled', 'claimed', 'running', 'executing', 'dispatching', 'reconciling'].includes(item.state)) ? 10_000 : false
  });
  const capabilities = overview.data?.capabilities ?? EMPTY_CAPABILITIES;
  const grouped = useMemo(() => TWITCH_GROUPS.map((item) => ({ ...item, operations: capabilities.filter((capability) => capabilityGroup(capability) === item.id) })), [capabilities]);
  const activeGroup = grouped.find((item) => item.id === group)!;
  const active = activeGroup.operations.find((item) => item.action === actionId) ?? activeGroup.operations[0];
  const actualConnection = overview.data?.connection ?? connection;
  const canPerform = capabilityAvailable(active) && (!active?.workspacePermission || access.permissions.includes(active.workspacePermission));
  const verifyCapability = capabilities.find((item) => item.action === 'twitch.account.verify');
  const canVerifyAccount = capabilityAvailable(verifyCapability) && access.permissions.includes('read');
  function canControl(action: TwitchAction): boolean {
    const capability = capabilities.find((item) => item.action === action.action);
    return Boolean(capability?.workspacePermission && access.permissions.includes(capability.workspacePermission));
  }
  useSiteAgentPageContext({ selectedEntity: { type: 'connection', id: connection.id }, visibleState: { group, action: active?.action ?? '' } });

  function clearReview() { setReview(undefined); setAcknowledged(false); setError(''); setNotice(''); }
  function selectGroup(next: TwitchGroupId) { setGroup(next); setActionId(''); setValues({}); setExecuteAt(''); setPastBroadcastsEnabled(false); setResult(undefined); clearReview(); }
  function selectAction(next: string) { setActionId(next); setValues({}); setExecuteAt(''); setPastBroadcastsEnabled(false); setResult(undefined); clearReview(); }

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await work(); }
    catch (err) { if (mounted.current) setError(errorMessage(err)); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function refreshStoredState() {
    await queryClient.invalidateQueries({ queryKey: ['twitch-overview', workspaceId, connection.id] });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!active || !canPerform) return;
    await run(async () => {
      const payload = parseFields(active.fields, values);
      const instant = active.write && active.schedulable ? scheduledInstant(executeAt) : undefined;
      const isMarker = active.action === 'twitch.marker.create';
      if (isMarker && !pastBroadcastsEnabled) throw new Error('Confirm that Store past broadcasts is enabled in Twitch before preparing a stream marker.');
      const declarations = isMarker ? { pastBroadcastsEnabled: true } : undefined;
      if (active.write) {
        clearReview();
        const prepared = await api.twitchPreview(workspaceId, connection.id, { action: active.action, payload, ...(instant ? { executeAt: instant } : {}), ...(isMarker ? { pastBroadcastsEnabled: true as const } : {}) });
        if (!mounted.current) return;
        if (prepared.action !== active.action) throw new Error('The preview did not match the selected Twitch operation. Prepare it again.');
        setClock(Date.now());
        setReview({ action: prepared, signature: submissionSignature(active.action, payload, instant, declarations) });
        await refreshStoredState();
      } else {
        const response = await api.twitchRead(workspaceId, connection.id, active.action, payload);
        if (mounted.current) setResult({ label: active.label, value: response });
        await refreshStoredState();
      }
    });
  }

  let signature = '';
  try { if (active) signature = submissionSignature(active.action, parseFields(active.fields, values), active.write && active.schedulable ? scheduledInstant(executeAt, 0) : undefined, active.action === 'twitch.marker.create' ? { pastBroadcastsEnabled } : undefined); } catch { /* The form will explain incomplete fields on submit. */ }
  const currentReview = review && review.signature === signature && review.action.action === active?.action ? review.action : undefined;
  const sameActor = Boolean(user?.id && currentReview?.actorId === user.id);
  const declarationReady = active?.action !== 'twitch.marker.create' || currentReview?.declarations?.pastBroadcastsEnabled === true;
  const approvalAvailable = currentReview && reviewCanApprove(currentReview, actualConnection.authorizationGeneration, clock) && canPerform && sameActor && declarationReady;

  async function approve() {
    if (!currentReview || !approvalAvailable || !acknowledged || busy) return;
    await run(async () => {
      try {
        const receipt = await api.twitchApprove(workspaceId, connection.id, currentReview.id, currentReview.payloadHash);
        if (mounted.current) setNotice(actionStateLabel(receipt.state));
      } finally {
        // A lost response is not a rejected action. Reload its durable state before any new approval.
        if (mounted.current) { setReview(undefined); setAcknowledged(false); }
        await refreshStoredState();
      }
    });
  }

  async function control(id: string, command: 'pause' | 'cancel') {
    await run(async () => {
      const receipt = await (command === 'pause' ? api.twitchPause(workspaceId, connection.id, id) : api.twitchCancel(workspaceId, connection.id, id));
      if (mounted.current) { if (review?.action.id === id) clearReview(); setNotice(actionStateLabel(receipt.state)); }
      await refreshStoredState();
    });
  }

  async function reconcile(id: string) {
    await run(async () => {
      try {
        const receipt = await api.twitchReconcile(workspaceId, connection.id, id);
        if (mounted.current) setNotice(actionStateLabel(receipt.state));
      } finally { await refreshStoredState(); }
    });
  }

  async function verifyAccount() {
    if (!verifyCapability || !canVerifyAccount || busy) return;
    await run(async () => {
      const response = await api.twitchRead(workspaceId, connection.id, verifyCapability.action, {});
      if (mounted.current) { setGroup('channel'); setActionId(verifyCapability.action); setValues({}); setExecuteAt(''); clearReview(); setResult({ label: verifyCapability.label, value: response }); }
      await refreshStoredState();
    });
  }

  function recoverDraft(draft: TwitchAction) {
    const capability = capabilities.find((item) => item.action === draft.action);
    if (!capability) { setError('This operation is no longer available. Refresh the connection before continuing.'); return; }
    setGroup(capabilityGroup(capability)); setActionId(draft.action); setValues(draft.payload);
    const scheduled = reviewScheduledInstant(draft, capability);
    const at = timestampMillis(scheduled);
    // Date inputs use local time; the approval signature retains the same instant.
    const local = at === null ? '' : new Date(at - new Date(at).getTimezoneOffset() * 60_000).toISOString().slice(0, 19);
    setExecuteAt(local); setAcknowledged(false); setClock(Date.now()); setError('');
    const markerConfirmed = draft.declarations?.pastBroadcastsEnabled === true;
    setPastBroadcastsEnabled(markerConfirmed);
    setReview({ action: draft, signature: submissionSignature(draft.action, draft.payload, scheduled, draft.action === 'twitch.marker.create' ? { pastBroadcastsEnabled: markerConfirmed } : undefined) });
  }

  async function upgrade(capability: string) {
    await run(async () => {
      const started = await api.oauthStart(workspaceId, 'twitch', capability, { connectionId: connection.id });
      if (mounted.current) { clearReview(); setOAuth(started); }
    });
  }

  if (overview.isPending) return <StateMessage kind='loading' title={`Loading ${connection.account || 'Twitch'} permissions…`} />;
  if (overview.isError) return <StateMessage kind='error' title='Twitch permissions could not be loaded' description={errorMessage(overview.error)} action={<Button type='button' variant='outline' onClick={() => void overview.refetch()}>Try again</Button>} />;

  return (
    <div className='grid gap-5'>
      <div className='flex flex-wrap items-center justify-between gap-3'>
        <p className='text-muted-foreground text-sm'>{actualConnection.account || actualConnection.handle} · {actualConnection.status}</p>
        <div className='flex flex-wrap gap-2'>
          <Button type='button' variant='ghost' size='sm' disabled={overview.isFetching || busy} onClick={() => void overview.refetch()}>{overview.isFetching ? 'Updating…' : 'Refresh status'}</Button>
          {verifyCapability && <Button type='button' variant='outline' size='sm' disabled={busy || !canVerifyAccount} onClick={() => void verifyAccount()}>Verify account eligibility</Button>}
          {canManage && <Button type='button' variant='outline' size='sm' disabled={busy || provider?.connectReady !== true} onClick={() => void upgrade('identity')}>Reconnect</Button>}
          <Link href='/app/channels' className='rafii-focus text-muted-foreground inline-flex min-h-9 items-center rounded-md px-2 text-sm underline'>Manage or disconnect</Link>
        </div>
      </div>
      {oauth && <OAuthReview request={oauth} dismiss={() => setOAuth(undefined)} />}
      <nav aria-label='Twitch feature groups' className='flex flex-wrap gap-2'>
        {grouped.map((item) => <button key={item.id} type='button' disabled={busy} aria-pressed={group === item.id} onClick={() => selectGroup(item.id)} className={cn('rafii-focus min-h-10 rounded-full border px-3.5 py-2 text-sm transition-colors disabled:opacity-60', group === item.id ? 'rafii-glass-selected text-foreground' : 'text-muted-foreground hover:text-foreground')}>
          {item.label}<span className='ml-1.5 text-xs opacity-65'>{item.operations.length}</span>
        </button>)}
      </nav>
      <div className='grid items-start gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]'>
        <Surface as='section' className='grid gap-5' aria-labelledby='twitch-feature-heading'>
          <div className='grid gap-1.5'><h2 id='twitch-feature-heading' className='font-medium'>{activeGroup.label}</h2><p className='text-muted-foreground text-sm leading-relaxed'>{activeGroup.description}</p></div>
          {!active ? <StateMessage kind='unsupported' title='No operations available in this group' description='The server has not supplied a supported operation for this account.' layout='inline' /> : (
            <form onSubmit={(event) => void submit(event)} className='grid gap-4'>
              <div className='grid gap-1.5'><Label htmlFor='twitch-operation'>Action</Label><select id='twitch-operation' className={TWITCH_SELECT_CLASS} value={active.action} disabled={busy} onChange={(event) => selectAction(event.target.value)}>{activeGroup.operations.map((item) => <option key={item.action} value={item.action}>{item.label} · {verificationLabel(item)}</option>)}</select></div>
              <div className='flex flex-wrap items-center gap-2'><span className='rounded-full border px-2.5 py-1 text-xs'>{active.write ? 'Change on Twitch' : 'Read from Twitch'}</span><span className='rounded-full border px-2.5 py-1 text-xs'>{verificationLabel(active)}</span>{active.risk && <span className='text-muted-foreground text-xs'>Impact: {active.risk.replaceAll('_', ' ')}</span>}</div>
              {!capabilityAvailable(active) && <StateMessage kind='permission' title='This action is unavailable' description={active.availability?.reasons?.join(' ') || 'Permission, account eligibility or live execution access has not been verified.'} layout='inline' action={canManage && active.canUpgrade === true && provider?.connectReady === true ? <Button type='button' size='sm' variant='outline' disabled={busy} onClick={() => void upgrade(active.action)}>Review additional Twitch access</Button> : undefined} />}
              <NativeFields fields={active.fields} values={values} disabled={busy || !canPerform} onChange={(next) => { setValues(next); clearReview(); }} />
              {active.action === 'twitch.marker.create' && <Label id='twitch-marker-declaration-label' className='flex items-start gap-2 text-sm font-normal leading-relaxed'><input type='checkbox' aria-labelledby='twitch-marker-declaration-label' className='rafii-focus mt-1 size-4 shrink-0' checked={pastBroadcastsEnabled} disabled={busy || !canPerform} onChange={(event) => { setPastBroadcastsEnabled(event.target.checked); clearReview(); }} />I have enabled Store past broadcasts in this Twitch channel. This is my declaration; Rafii cannot verify that setting through Helix.</Label>}
              {active.write && active.schedulable === true && <div className='grid gap-1.5'><Label htmlFor='twitch-run-at'>Run this action later <span className='text-muted-foreground font-normal'>(optional)</span></Label><Input id='twitch-run-at' type='datetime-local' step={1} value={executeAt} disabled={busy || !canPerform} onChange={(event) => { setExecuteAt(event.target.value); clearReview(); }} /><p className='text-muted-foreground text-xs'>Shown in {Intl.DateTimeFormat().resolvedOptions().timeZone}. Leave empty to run after approval. This schedules the API action; it does not start an encoder.</p></div>}
              <ScopeDetails capability={active} />
              <Button type='submit' disabled={busy || !canPerform} className='justify-self-start'>{busy ? 'Working…' : active.write ? 'Prepare review' : 'Read from Twitch'}</Button>
            </form>
          )}
          {group === 'events' && overview.data?.eventSub && <DataReceipt label='EventSub delivery and worker status' data={overview.data.eventSub} />}
          {result && <div className='grid gap-3'><h3 className='text-sm font-medium'>{result.label}</h3><NativeReadResult result={result.value} /></div>}
        </Surface>
        <Surface as='section' material={currentReview ? 'selected' : 'quiet'} className='grid gap-4' aria-labelledby='twitch-review-heading'>
          <h2 id='twitch-review-heading' className='font-medium'>Review & approve</h2>
          {!currentReview ? <p className='text-muted-foreground text-sm leading-relaxed'>Prepare an action to review its exact account, content, audience and timing before approving it.</p> : (
            <>
              <dl className='grid gap-3 text-sm'><div><dt className='text-muted-foreground text-xs'>Twitch account</dt><dd className='mt-1 font-medium'>{actualConnection.account || actualConnection.handle} {actualConnection.providerAccountId ? `(${actualConnection.providerAccountId})` : ''}</dd></div><div><dt className='text-muted-foreground text-xs'>Action</dt><dd className='mt-1'>{active?.label}</dd></div><div><dt className='text-muted-foreground text-xs'>Execution</dt><dd className='mt-1'>{currentReview.scheduled === true && currentReview.executeAt ? displayTime(currentReview.executeAt) : 'After this approval, when the worker is available'}</dd></div><div><dt className='text-muted-foreground text-xs'>Approval expires</dt><dd className='mt-1'>{displayTime(currentReview.expiresAt)}</dd></div></dl>
              <div className='grid gap-2'><h3 className='text-sm font-medium'>Exact change</h3><pre data-private className='max-h-96 overflow-auto rounded-lg border p-3 whitespace-pre-wrap break-words text-xs leading-relaxed'>{JSON.stringify(safeDisplay(currentReview.payload), null, 2)}</pre></div>
              {effectsList(currentReview.effects).length > 0 && <ul className='text-muted-foreground list-inside list-disc space-y-1 text-sm'>{effectsList(currentReview.effects).map((effect) => <li key={effect}>{effect}</li>)}</ul>}
              {currentReview.declarations?.pastBroadcastsEnabled === true && <p className='text-sm'>Included in this approval: your declaration that Store past broadcasts is enabled.</p>}
              {group === 'chat' && <p className='text-sm'>Confirm the message audience above. A Shared Chat session may include viewers in other participating channels.</p>}
              {!approvalAvailable && <p role='alert' className='text-destructive text-sm'>{!sameActor ? 'Only the signed-in person who prepared this action can approve it.' : !canPerform ? 'Your current permissions or account state do not allow this action.' : !declarationReady ? 'The server has not included the required broadcast-setting declaration. Prepare a new review.' : 'This preview is expired or the account authorization changed. Refresh status and prepare a new review.'}</p>}
              <Label id='twitch-action-approval-label' className='flex items-start gap-2 text-sm font-normal leading-relaxed'><input aria-labelledby='twitch-action-approval-label' className='rafii-focus mt-1 size-4 shrink-0' type='checkbox' checked={acknowledged} disabled={busy || !approvalAvailable} onChange={(event) => setAcknowledged(event.target.checked)} />I approve this exact action, account, content and execution time.</Label>
              <div className='flex flex-wrap gap-2'><Button type='button' disabled={busy || !approvalAvailable || !acknowledged} onClick={() => void approve()}>{busy ? 'Submitting…' : 'Approve this action'}</Button><Button type='button' variant='ghost' disabled={busy || !canControl(currentReview)} onClick={() => void control(currentReview.id, 'cancel')}>Cancel draft</Button></div>
              <details className='text-muted-foreground text-xs'><summary className='rafii-focus cursor-pointer rounded-sm'>Approval receipt</summary><p className='mt-2 break-all'>ID: {currentReview.id}</p><p className='mt-1 break-all'>Payload SHA-256: {currentReview.payloadHash}</p><p className='mt-1'>Authorization generation: {currentReview.generation}</p></details>
            </>
          )}
        </Surface>
      </div>
      {error && <StateMessage kind='error' title='Action needs attention' description={error} />}
      {notice && <StateMessage kind='partial' title={notice} description='The saved action receipt below is the source of truth for execution.' layout='inline' />}
      {canManage && (group === 'media' || (group === 'channel' && active?.action === 'twitch.stream.key.get')) && <SensitiveTwitchControls key={`${connection.id}:${group}`} connection={actualConnection} capabilities={capabilities} mode={group === 'media' ? 'clips' : 'encoder'} refresh={refreshStoredState} />}
      <ActionReceipts actions={overview.data?.actions ?? []} busy={busy} canControl={canControl} onControl={control} onReview={recoverDraft} onReconcile={access.permissions.includes('read') ? reconcile : undefined} />
    </div>
  );
}

'use client';

import { useEffect, useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { isPostableVideo } from '@/lib/media/asset-kinds';
import type { YouTubeAgentDraft, YouTubeAgentPolicy, YouTubeAgentArchiveResult } from '@/lib/youtube/types';
import type { OAuthStart } from '@/lib/api/types';

const control = 'border-input bg-background w-full min-w-0 rounded-md border px-3 py-2 text-sm';

export function canReviewYouTubeAgentDraft(draft: YouTubeAgentDraft, now = Date.now() / 1000) {
  return draft.status === 'proposed' && !draft.readOnly && Number.isFinite(draft.timing.timestamp) && draft.timing.timestamp > now;
}

function currentPolicy(policy: YouTubeAgentPolicy, now = Date.now() / 1000) {
  return policy.status !== 'expired' && policy.status !== 'revoked' && Number.isFinite(policy.endsAt) && policy.endsAt > now;
}

export function YouTubeAgentControls({ channel, canPublic }: { channel: string; canPublic: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const access = useWorkspaceAccess();
  const owner = checkAccess(access, { role: 'owner' });
  const canEdit = checkAccess(access, { permission: 'edit' });
  const canApprove = checkAccess(access, { permission: 'approve' });
  const snapshot = useSnapshot();
  const client = useQueryClient();
  const prefix = useId();
  const pageScope = `${workspaceId}:${channel}`;
  const emptyPages = () => ({ scope: pageScope, drafts: [] as string[], policies: [] as string[], history: [] as string[] });
  const [pageState, setPageState] = useState(emptyPages);
  const pages = pageState.scope === pageScope ? pageState : emptyPages();
  const draftCursor = pages.drafts.at(-1);
  const policyCursor = pages.policies.at(-1);
  const [showHistory, setShowHistory] = useState(false);
  const [historyKind, setHistoryKind] = useState<'draft' | 'policy'>('draft');
  const historyCursor = pages.history.at(-1);
  const [archiveResult, setArchiveResult] = useState<YouTubeAgentArchiveResult>();
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now() / 1000), 30_000);
    return () => clearInterval(timer);
  }, []);
  const query = useQuery({
    queryKey: ['youtube-agent', workspaceId, channel, draftCursor, policyCursor],
    queryFn: () => api.youtubeAgent(workspaceId, channel, { draftCursor, policyCursor, limit: 25 }),
    enabled: Boolean(channel), retry: false, staleTime: 30_000
  });
  const history = useQuery({
    queryKey: ['youtube-agent-history', workspaceId, channel, historyKind, historyCursor],
    queryFn: () => api.youtubeAgentHistory(workspaceId, channel, historyKind, { cursor: historyCursor, limit: 25 }),
    enabled: Boolean(channel) && showHistory, retry: false, staleTime: 30_000
  });
  const resetPages = () => setPageState(emptyPages());
  const movePage = (kind: 'drafts' | 'policies' | 'history', next?: string) => setPageState((current) => {
    const scoped = current.scope === pageScope ? current : emptyPages();
    return { ...scoped, [kind]: next ? [...scoped[kind], next] : scoped[kind].slice(0, -1) };
  });
  const assets = snapshot.data?.state.phase2?.assets.filter((a) => isPostableVideo(a, 'YouTube')) ?? [];
  const [asset, setAsset] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [goal, setGoal] = useState('');
  const [localTime, setLocalTime] = useState('');
  const [timeZone, setTimeZone] = useState('UTC');
  const [fold, setFold] = useState('');
  const [privacy, setPrivacy] = useState('private');
  const [mode, setMode] = useState('video');
  const [workflow, setWorkflow] = useState('upload_now');
  const [uploadTime, setUploadTime] = useState('');
  const [uploadFold, setUploadFold] = useState('');
  const [rights, setRights] = useState(false);
  const [kids, setKids] = useState('');
  const [synthetic, setSynthetic] = useState('');
  const [selected, setSelected] = useState<{ id: string; digest: string; plannedAt: number }[]>([]);
  const [maxDaily, setMaxDaily] = useState('1');
  const [endsAt, setEndsAt] = useState('');
  const [policyReview, setPolicyReview] = useState<YouTubeAgentPolicy>();
  const [confirmedPolicy, setConfirmedPolicy] = useState(false);
  const [agenticConsent, setAgenticConsent] = useState(false);
  const [agenticAuthorization, setAgenticAuthorization] = useState<OAuthStart>();
  const [confirmedDraft, setConfirmedDraft] = useState<{ id: string; digest: string }>();
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setSelected([]); setConfirmedDraft(undefined); setPolicyReview(undefined); setConfirmedPolicy(false);
    setAgenticAuthorization(undefined); setAgenticConsent(false); setShowHistory(false); setArchiveResult(undefined);
  }, [workspaceId, channel]);
  const selectedPlans = selected.filter((item) => {
    const visible = query.data?.drafts.find((draft) => draft.id === item.id);
    return item.plannedAt > now && (!visible || (visible.digest === item.digest && canReviewYouTubeAgentDraft(visible, now)));
  });
  async function reloadFirstPages() {
    resetPages();
    await client.invalidateQueries({ queryKey: ['youtube-agent', workspaceId, channel] });
  }
  async function run(work: () => Promise<unknown>, message: string) {
    setBusy(true); setError(''); setNotice('');
    try {
      await work();
      resetPages();
      await Promise.all([
        client.invalidateQueries({ queryKey: ['snapshot', workspaceId] }),
        client.invalidateQueries({ queryKey: ['youtube-agent', workspaceId, channel] }),
        client.invalidateQueries({ queryKey: ['youtube-agent-history', workspaceId, channel] })
      ]);
      setNotice(message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'The publishing-agent action failed.');
    } finally { setBusy(false); }
  }
  const revision = async () => (await api.snapshot(workspaceId)).revision;
  async function prepare() {
    if (!rights || !kids || !synthetic) throw new Error('Confirm video rights, audience and realistic synthetic media declarations.');
    const publishOptions = {
      title, description, privacyStatus: privacy, mode,
      madeForKids: kids === 'yes', containsSyntheticMedia: synthetic === 'yes'
    };
    await api.youtubeAgentPrepare(workspaceId, channel, {
      revision: await revision(), assetId: asset, publishOptions, goal,
      localTime, timeZone, fold: fold === '' ? null : Number(fold), rightsConfirmed: rights,
      uploadWorkflow: workflow, uploadLocalTime: uploadTime,
      uploadFold: uploadFold === '' ? null : Number(uploadFold)
    });
  }
  async function approve(draft: YouTubeAgentDraft) {
    if (!canReviewYouTubeAgentDraft(draft) || confirmedDraft?.id !== draft.id || confirmedDraft.digest !== draft.digest) throw new Error('Review a current future plan before approving it.');
    await api.youtubeAgentApprove(workspaceId, channel, draft.id, {
      revision: await revision(), digest: draft.digest, confirmed: true
    });
    setConfirmedDraft(undefined);
    setSelected((items) => items.filter((item) => item.id !== draft.id));
  }
  async function previewPolicy() {
    const expiry = Date.parse(endsAt);
    if (!Number.isFinite(expiry)) throw new Error('Choose an authority expiry with an explicit UTC offset, for example 2026-10-20T18:00:00Z.');
    const exactPlans = selectedPlans.filter((item) => item.plannedAt > Date.now() / 1000);
    if (!exactPlans.length) throw new Error('Select at least one current future plan.');
    const result = await api.youtubeAgentPolicyPreview(workspaceId, channel, {
      revision: await revision(), draftIds: exactPlans.map((item) => item.id),
      draftDigests: Object.fromEntries(exactPlans.map((item) => [item.id, item.digest])),
      maxDaily: Number(maxDaily), timeZone, endsAt: expiry / 1000
    });
    setPolicyReview(result.result); setConfirmedPolicy(false);
  }
  async function policyAction(policy: YouTubeAgentPolicy, action: 'activate' | 'pause' | 'revoke') {
    if (!currentPolicy(policy)) throw new Error('Expired or revoked authority is read-only. Prepare a new policy.');
    await api.youtubeAgentPolicyAction(workspaceId, channel, policy.id, action, {
      revision: await revision(), ...(action === 'activate' ? {
        digest: policy.digest, confirmed: true, confirmationChannelId: policy.channelId
      } : {})
    });
    setPolicyReview(undefined); setConfirmedPolicy(false);
  }
  const input = (name: string, value: string, change: (value: string) => void, type = 'text') => (
    <div className='grid min-w-0 grid-cols-1 gap-1.5'>
      <Label htmlFor={`${prefix}-${name}`}>{name}</Label>
      <Input id={`${prefix}-${name}`} aria-label={name} type={type} value={value} onChange={(event) => change(event.target.value)} />
    </div>
  );
  const selection = (name: string, value: string, change: (value: string) => void, options: [string, string][]) => (
    <div className='grid min-w-0 grid-cols-1 gap-1.5'>
      <Label htmlFor={`${prefix}-${name}`}>{name}</Label>
      <select className={control} id={`${prefix}-${name}`} aria-label={name} value={value} onChange={(event) => change(event.target.value)}>
        {options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
      </select>
    </div>
  );
  return (
    <section className='grid min-w-0 grid-cols-1 gap-4 rounded-lg border p-4 [overflow-wrap:anywhere]' aria-label='YouTube publishing agent'>
      <h2 className='font-medium'>Library publishing plans</h2>
      <p className='text-muted-foreground text-sm'>Prepare a video plan, then approve its exact channel, metadata and time. Draft suggestions use Library filenames and your inputs; no AI model has inspected the video.</p>
      {query.isError && <div className='grid gap-2'><p role='alert' className='text-destructive text-sm'>{query.error.message}</p><Button variant='outline' className='w-fit' onClick={reloadFirstPages}>Reload first publishing pages</Button></div>}
      <div className='grid min-w-0 grid-cols-1 gap-4 sm:grid-cols-2'>
        {selection('Library video', asset, (value) => {
          setAsset(value); setRights(false);
          const video = assets.find((item) => item.id === value);
          setTitle((video?.displayTitle || video?.originalFilename || '').replace(/\.[a-z0-9]+$/i, '').replace(/[_-]+/g, ' ').slice(0, 100));
        }, [['', 'Choose an inspected video'], ...assets.map((video): [string, string] => [video.id, video.displayTitle || video.originalFilename || video.id])])}
        {selection('Format', mode, setMode, [['video', 'Standard video'], ['short', 'Short (official format eligibility)']])}
        {input('Proposed title', title, setTitle)}
        {input('Channel goal (planning context)', goal, setGoal)}
        <div className='grid min-w-0 grid-cols-1 gap-1.5 sm:col-span-2'>
          <Label htmlFor={`${prefix}-description`}>Proposed description</Label>
          <textarea id={`${prefix}-description`} aria-label='Proposed description' className={control} rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
        </div>
        {selection('Intended visibility', privacy, setPrivacy, [['private', 'Private (stays private)'], ...(canPublic ? [['public', 'Public at planned time'] as [string, string]] : [])])}
        {input('Planned publication time', localTime, setLocalTime, 'datetime-local')}
        {input('IANA time zone', timeZone, setTimeZone)}
        {selection('Repeated clock time', fold, setFold, [['', 'Ask if the time occurs twice'], ['0', 'First occurrence'], ['1', 'Second occurrence']])}
        {selection('Upload workflow', workflow, setWorkflow, [['upload_now', 'Upload privately now, then schedule'], ['upload_later', 'Queue the upload itself for later']])}
        {workflow === 'upload_later' && <>
          {input('Begin upload at least ten minutes earlier', uploadTime, setUploadTime, 'datetime-local')}
          {selection('Upload repeated clock time', uploadFold, setUploadFold, [['', 'Ask if the time occurs twice'], ['0', 'First occurrence'], ['1', 'Second occurrence']])}
        </>}
        {selection('Made for kids', kids, setKids, [['', 'Choose explicitly'], ['no', 'No'], ['yes', 'Yes']])}
        {selection('Realistic altered or synthetic media', synthetic, setSynthetic, [['', 'Choose explicitly'], ['no', 'No'], ['yes', 'Yes']])}
      </div>
      <label htmlFor={`${prefix}-rights`} className='flex items-start gap-2 text-sm'>
        <input id={`${prefix}-rights`} aria-label='Confirm rights to this exact Library video and metadata' type='checkbox' checked={rights} onChange={(event) => setRights(event.target.checked)} />
        I have the rights to upload this exact Library video and its metadata.
      </label>
      <Button className='w-fit' disabled={busy || !canEdit || !asset || !title || !localTime || !rights || !kids || !synthetic}
        onClick={() => run(prepare, 'Plan prepared. Review it below before approving publication.')}>Prepare reviewable plan</Button>
      <div className='grid min-w-0 grid-cols-1 gap-3' aria-label='Publishing calendar'>
        <h3 className='font-medium'>Publishing calendar</h3>
        <p className='text-muted-foreground text-sm'>Plan page {pages.drafts.length + 1}. Up to 25 records per page; {selectedPlans.length} exact future plans selected across pages.</p>
        {query.data?.drafts.map((draft) => <article key={draft.id} data-youtube-agent-draft={draft.id} className='grid min-w-0 grid-cols-1 gap-2 rounded-md border p-3 text-sm'>
          <div className='flex items-start gap-2'>
            {owner && canReviewYouTubeAgentDraft(draft, now) && <input id={`${prefix}-include-${draft.id}`} type='checkbox' aria-label={`Include ${draft.publishOptions.title} in autopilot policy`}
              checked={selectedPlans.some((item) => item.id === draft.id && item.digest === draft.digest)} onChange={(event) => {
                const checked = event.target.checked;
                if (checked && !canReviewYouTubeAgentDraft(draft)) return;
                if (checked && selectedPlans.length >= 100) { setError('Select at most 100 exact future plans.'); return; }
                setSelected((items) => {
                  const others = items.filter((item) => item.id !== draft.id && item.plannedAt > Date.now() / 1000);
                  return checked ? (others.length >= 100 ? items : [...others, { id: draft.id, digest: draft.digest, plannedAt: draft.timing.timestamp }]) : others;
                });
              }} />}
            <div className='min-w-0'><p className='font-medium'>{draft.publishOptions.title}</p>
              <p className='text-muted-foreground'>{draft.timing.local.replace('T', ' ')} · {draft.timing.timeZone} · {draft.publishOptions.privacyStatus} · {draft.status}</p></div>
          </div>
          <p className='whitespace-pre-wrap'>{draft.publishOptions.description || '(Empty description)'}</p>
          {draft.metadataOrigin && <p className='text-muted-foreground'>{draft.metadataOrigin === 'chat_model_proposal_requires_video_review' ? 'AI chat proposal. Review it against the actual video before approval.' : 'Metadata from your inputs or the Library filename. Review it against the actual video before approval.'}</p>}
          <p>Channel: {draft.channelId} · Library video: {draft.assetId}</p>
          <p>{draft.uploadWorkflow === 'upload_now' ? 'Upload privately after approval.' : `Upload begins ${new Date(draft.uploadAt * 1000).toISOString()}.`} {draft.publishOptions.privacyStatus === 'private' ? 'There is no automatic public transition.' : 'YouTube applies the native future publication schedule.'}</p>
          {!canReviewYouTubeAgentDraft(draft, now) && <p className='text-muted-foreground'>Read-only plan record. This view grants no new publishing approval.</p>}
          {canReviewYouTubeAgentDraft(draft, now) && <>
            <label htmlFor={`${prefix}-approve-${draft.id}`} className='flex items-start gap-2'><input id={`${prefix}-approve-${draft.id}`} aria-label={`Approve the exact video, metadata, channel, time and visibility for ${draft.publishOptions.title}`} type='checkbox' checked={confirmedDraft?.id === draft.id && confirmedDraft.digest === draft.digest} onChange={(event) => setConfirmedDraft(event.target.checked ? { id: draft.id, digest: draft.digest } : undefined)} />I approve this exact video, metadata, channel, time and visibility.</label>
            <Button className='w-fit' disabled={busy || !canApprove || confirmedDraft?.id !== draft.id || confirmedDraft.digest !== draft.digest} onClick={() => run(() => approve(draft), 'Approved and queued. Publication is complete only when the provider receipt verifies it.')}>Approve and queue this plan</Button>
          </>}
          {draft.jobId && <p>Queue receipt: {draft.jobId} · {draft.approvalMode}</p>}
        </article>)}
        <nav aria-label='Publishing plan pages' className='flex flex-wrap items-center gap-2'>
          <Button variant='outline' disabled={busy || query.isFetching || !pages.drafts.length} onClick={() => movePage('drafts')}>Previous publishing plans</Button>
          <Button variant='outline' disabled={busy || query.isFetching || !query.data?.pagination?.drafts.hasMore || !query.data.pagination.drafts.nextCursor} onClick={() => movePage('drafts', query.data!.pagination.drafts.nextCursor!)}>Next publishing plans</Button>
        </nav>
      </div>
      {owner && <div className='grid min-w-0 grid-cols-1 gap-3 border-t pt-4'>
        <h3 className='font-medium'>Bounded authorized autopilot</h3>
        <p className='text-muted-foreground text-sm'>Standing authority covers only the selected exact plans and Library videos on this channel. Changes require fresh owner approval. Authority expires within 30 days.</p>
        {!query.data?.autopilotGate.canActivate && <p className='text-sm'>{query.data?.autopilotGate.reason || 'Checking Google approval and agentic OAuth availability.'}</p>}
        {!query.data?.autopilotGate.canActivate && <div className='grid min-w-0 grid-cols-1 gap-3 rounded-md border p-3 text-sm'>
          <label htmlFor={`${prefix}-agentic-consent`} className='flex items-start gap-2'><input id={`${prefix}-agentic-consent`} aria-label='Request separate Google authorization for owner-authorized Rafii publishing plans' type='checkbox' checked={agenticConsent} onChange={(event) => { setAgenticConsent(event.target.checked); setAgenticAuthorization(undefined); }} />I want a separate Google authorization for Rafii to execute owner-authorized publishing plans. Connecting does not activate autopilot or grant permission to delete content.</label>
          <Button variant='outline' className='w-fit' disabled={busy || !agenticConsent} onClick={() => run(async () => {
            setAgenticAuthorization(await api.oauthStart(workspaceId, 'youtube', 'autopilot', { authorizationLane: 'agentic', agenticConsent: true }));
          }, 'Review the Google permissions below, then authorize your own channel.')}>Prepare separate agentic Google consent</Button>
          {agenticAuthorization && <>
            <p>{agenticAuthorization.permissionExplanation}</p>
            <p>Scopes: {agenticAuthorization.scopes.join(', ')}</p>
            {agenticAuthorization.authorizeUrl && <a className='w-fit underline' href={agenticAuthorization.authorizeUrl} aria-label='Continue to Google to select and authorize your channel'>Continue to Google to select and authorize your channel</a>}
          </>}
        </div>}
        <div className='grid min-w-0 grid-cols-1 gap-3 sm:grid-cols-2'>
          {input('Maximum publications per day (1–20)', maxDaily, setMaxDaily, 'number')}
          {input('Authority expires (ISO date with UTC offset)', endsAt, setEndsAt)}
        </div>
        <Button variant='outline' className='w-fit' disabled={busy || !selectedPlans.length || !endsAt} onClick={() => run(previewPolicy, 'Policy prepared. Review its exact scope before activation.')}>Review standing authority for {selectedPlans.length} plans</Button>
        {policyReview && currentPolicy(policyReview, now) && <div className='grid min-w-0 grid-cols-1 gap-3 rounded-md border p-3 text-sm'>
          <p>Channel {policyReview.channelId} · {policyReview.drafts.length} exact plans · {policyReview.assetIds.length} Library videos · maximum {policyReview.maxDaily}/day in {policyReview.timeZone} · expires {new Date(policyReview.endsAt * 1000).toISOString()}</p>
          <ul className='grid min-w-0 gap-1' aria-label='Exact plans covered by this policy'>
            {policyReview.drafts.map((draft) => <li key={draft.id} data-youtube-policy-scope-draft={draft.id}>Plan {draft.id} · digest {draft.digest}</li>)}
          </ul>
          <label htmlFor={`${prefix}-policy-consent`} className='flex items-start gap-2'><input id={`${prefix}-policy-consent`} aria-label='Authorize only the reviewed exact publishing plans within their limits until expiry or revocation' type='checkbox' checked={confirmedPolicy} onChange={(event) => setConfirmedPolicy(event.target.checked)} />I authorize Rafii to execute only these exact plans within these limits until expiry or revocation.</label>
          <Button className='w-fit' disabled={busy || !confirmedPolicy || !query.data?.autopilotGate.canActivate} onClick={() => run(() => policyAction(policyReview, 'activate'), 'Bounded authority activated. The worker still verifies credentials, quotas and each publishing receipt.')}>Enable bounded autopilot</Button>
        </div>}
        <h3 className='font-medium'>Standing authority records</h3>
        <p className='text-muted-foreground text-sm'>Policy page {pages.policies.length + 1}. Expired and revoked records are read-only.</p>
        {query.data?.policies.map((policy) => <div key={policy.id} data-youtube-agent-policy={policy.id} className='grid min-w-0 grid-cols-1 gap-2 rounded-md border p-3 text-sm'>
          <p>{policy.status} · {policy.drafts.length} plans · {policy.maxDaily}/day · expires {new Date(policy.endsAt * 1000).toISOString()}</p>
          {policy.intervention && <p role='alert'>{policy.intervention.message}</p>}
          {policy.status === 'paused' && <p>Restarting this policy permits new plan dispatch only. Held jobs require separate review and do not resume automatically. Creator recovery is available only for recoverable journaled uploads.</p>}
          {!currentPolicy(policy, now) && <p className='text-muted-foreground'>Read-only authority record. Prepare new authority to approve different future plans.</p>}
          {currentPolicy(policy, now) && <div className='flex flex-wrap gap-2'>
            {policy.status === 'active' && <Button variant='outline' disabled={busy} onClick={() => run(() => policyAction(policy, 'pause'), 'Autopilot paused. Already accepted native YouTube schedules need separate cancellation.')}>Pause new execution</Button>}
            {policy.status === 'paused' && <Button variant='outline' disabled={busy || !query.data?.autopilotGate.canActivate} onClick={() => { setPolicyReview(policy); setConfirmedPolicy(false); }}>Review policy restart</Button>}
            {policy.status !== 'revoked' && <Button variant='outline' disabled={busy} onClick={() => run(() => policyAction(policy, 'revoke'), 'Standing authority revoked. Already accepted native YouTube schedules need separate cancellation.')}>Revoke authority</Button>}
          </div>}
        </div>)}
        <nav aria-label='Standing authority pages' className='flex flex-wrap items-center gap-2'>
          <Button variant='outline' disabled={busy || query.isFetching || !pages.policies.length} onClick={() => movePage('policies')}>Previous authority records</Button>
          <Button variant='outline' disabled={busy || query.isFetching || !query.data?.pagination?.policies.hasMore || !query.data.pagination.policies.nextCursor} onClick={() => movePage('policies', query.data!.pagination.policies.nextCursor!)}>Next authority records</Button>
        </nav>
        <p className='text-muted-foreground text-sm'>{query.data?.pauseNotice}</p>
      </div>}
      <div className='grid min-w-0 grid-cols-1 gap-3 border-t pt-4'>
        <Button variant='outline' className='w-fit' onClick={() => setShowHistory((open) => !open)}>{showHistory ? 'Close publishing history' : 'Open publishing history'}</Button>
        {showHistory && <section className='grid min-w-0 grid-cols-1 gap-3' aria-label='Archived publishing history'>
          <h3 className='font-medium'>Archived publishing history</h3>
          <p className='text-muted-foreground text-sm'>These records cannot reactivate authority or approve publication. Only the current page is loaded.</p>
          <div className='flex flex-wrap gap-2'>
            <Button variant='outline' disabled={historyKind === 'draft'} onClick={() => { setHistoryKind('draft'); setPageState((current) => ({ ...(current.scope === pageScope ? current : emptyPages()), history: [] })); }}>Plan history</Button>
            <Button variant='outline' disabled={historyKind === 'policy'} onClick={() => { setHistoryKind('policy'); setPageState((current) => ({ ...(current.scope === pageScope ? current : emptyPages()), history: [] })); }}>Authority history</Button>
          </div>
          {history.isError && <div className='grid gap-2'><p role='alert'>{history.error.message}</p><Button variant='outline' className='w-fit' onClick={() => { setPageState((current) => ({ ...(current.scope === pageScope ? current : emptyPages()), history: [] })); void client.invalidateQueries({ queryKey: ['youtube-agent-history', workspaceId, channel] }); }}>Reload first history page</Button></div>}
          {history.isFetching && <p role='status'>Loading history page…</p>}
          {history.data?.items.map((record) => <article key={`${record.recordKind}:${record.id}`} className='grid min-w-0 grid-cols-1 gap-1 rounded-md border p-3 text-sm' data-youtube-agent-history={record.id}>
            <p>{record.recordKind} {record.id} · archived · previous state {record.historicalStatus}</p>
            <p>Archived {record.archivedAt}</p>
            {Number.isFinite(record.plannedAt) && record.plannedAt !== undefined && <p>Planned time {new Date(record.plannedAt * 1000).toISOString()} · {record.timeZone || 'UTC'}</p>}
            {Number.isFinite(record.authorityEndedAt) && record.authorityEndedAt !== undefined && <p>Authority ended {new Date(record.authorityEndedAt * 1000).toISOString()}</p>}
            {record.channelId && <p>Channel {record.channelId}</p>}
            <p className='text-muted-foreground'>Read-only history; no reactivation is available.</p>
          </article>)}
          <nav aria-label='Archived history pages' className='flex flex-wrap items-center gap-2'>
            <Button variant='outline' disabled={busy || history.isFetching || !pages.history.length} onClick={() => movePage('history')}>Previous history records</Button>
            <Button variant='outline' disabled={busy || history.isFetching || !history.data?.nextCursor} onClick={() => movePage('history', history.data!.nextCursor!)}>Next history records</Button>
          </nav>
          {owner && <div className='grid gap-2'>
            <p className='text-muted-foreground text-sm'>Archive up to 50 inert records: expired unqueued plans and ended policies. Media, variants and Queue jobs are retained; no authority is reactivated.</p>
            <Button variant='outline' className='w-fit' disabled={busy} onClick={() => run(async () => {
              const result = await api.youtubeAgentArchive(workspaceId, channel, { revision: await revision() });
              setArchiveResult(result.result);
            }, 'Inert records archived. No publication or authority was activated.')}>Archive expired unqueued plans</Button>
            {archiveResult && <p role='status'>{archiveResult.draftsArchived} plans and {archiveResult.policiesArchived} policies archived. {archiveResult.residualGrowth.join(' ')}</p>}
          </div>}
        </section>}
      </div>
      {notice && <p role='status'  className='text-sm'>{notice}</p>}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
    </section>
  );
}
